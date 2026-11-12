# scripts/actualizar_datos.py
# Proceso diario (lo ejecuta el GitHub Action .github/workflows/actualizar_datos.yml,
# pero también se puede correr a mano: python -m scripts.actualizar_datos).
#
# 1. Lee la lista de tickers de la base de datos.
# 2. Descarga 5 años de precios de cierre ajustados (de los tickers analizados, de los
#    del portafolio personal y del S&P 500) y los guarda en precios_diarios.
# 3. Calcula el registro de cada ticker (nombre, categoría/sector, fundamentales,
#    ratios de estados financieros) con datos_mercado.py y lo guarda en la tabla
#    metricas. Esto también actualiza los metadatos. Si Yahoo falla con un ticker,
#    se conserva su registro anterior.
# 4. Calcula la frontera eficiente de los ETFs y de las acciones con el optimizador en
#    Rust (optimizador/, hay que compilarlo antes: cargo build --release) y la guarda en
#    la tabla fronteras. Si el programa no está compilado o falla, solo avisa.
#
# La app lee todo esto de la base, así que no consulta a Yahoo en cada visita.
#
# Necesita la conexión en .streamlit/secrets.toml ([connections.postgresql]).

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from finanzas import almacenamiento, frontera
from finanzas import datos_mercado as dm
from finanzas.comparar import INDICE_REFERENCIA

PERIODO_PRECIOS = "5y"  # el mismo periodo que usa dashboard/carga.py


def actualizar_precios(tickers):
    print(f"Descargando precios de {len(tickers)} tickers ({PERIODO_PRECIOS})...")
    precios = yf.download(tickers, period=PERIODO_PRECIOS, progress=False,
                          auto_adjust=True, threads=True)['Close']
    if isinstance(precios, pd.Series):
        precios = precios.to_frame(name=tickers[0])
    precios = precios.dropna(axis=1, how='all')
    sin_precios = sorted(set(tickers) - set(precios.columns))
    if sin_precios:
        print(f"  Sin precios para: {', '.join(sin_precios)}")
    filas = almacenamiento.guardar_precios(precios)
    print(f"Precios guardados: {len(precios.columns)} tickers, {filas} filas.")
    return precios


def _en_paralelo(funcion, simbolos):
    with ThreadPoolExecutor(max_workers=dm.MAX_HILOS_YAHOO) as pool:
        return dict(zip(simbolos, pool.map(funcion, simbolos), strict=True))


def actualizar_metricas(etfs, acciones):
    """Calcula y guarda el registro de cada ticker. Devuelve (n_ok, n_total)."""
    metadatos = almacenamiento.cargar_metadatos()
    ahora = datetime.now(UTC).replace(tzinfo=None)  # se guarda en UTC

    print(f"Calculando métricas de {len(etfs)} ETFs...")
    reg_etfs = _en_paralelo(lambda s: dm.obtener_metrica_etf(s, metadatos), etfs)
    reg_etfs = {s: r for s, r in reg_etfs.items() if r}

    print(f"Calculando métricas de {len(acciones)} acciones...")
    reg_acciones = _en_paralelo(lambda s: dm.obtener_metrica_accion(s, metadatos), acciones)
    reg_acciones = {s: r for s, r in reg_acciones.items() if not dm.es_registro_de_emergencia(r)}

    fallidos = sorted((set(etfs) - set(reg_etfs)) | (set(acciones) - set(reg_acciones)))
    if fallidos:
        print(f"  Sin datos (se conserva el registro anterior): {', '.join(fallidos)}")

    n_ok = (almacenamiento.guardar_metricas('etf_list', reg_etfs, ahora)
            + almacenamiento.guardar_metricas('stock_list', reg_acciones, ahora))
    n_total = len(etfs) + len(acciones)
    print(f"Métricas guardadas: {n_ok} de {n_total} tickers.")
    return n_ok, n_total


def actualizar_fronteras(precios, etfs, acciones):
    """Frontera eficiente de cada lista con el optimizador en Rust. Nunca hace fallar el proceso."""
    if not frontera.BINARIO.exists():
        print(f"AVISO: no está compilado el optimizador ({frontera.BINARIO}); se omite la frontera eficiente.")
        return
    ahora = datetime.now(UTC).replace(tzinfo=None)
    for clave, tickers, nombre in (('etf_list', etfs, 'ETFs'), ('stock_list', acciones, 'acciones')):
        try:
            resultado = frontera.calcular_frontera(precios, tickers)
            almacenamiento.guardar_frontera(clave, resultado, ahora)
        except Exception as e:
            print(f"AVISO: no se pudo calcular o guardar la frontera de {nombre}: {e}")
            continue
        ms = resultado['max_sharpe']
        print(f"Frontera de {nombre}: {len(resultado['activos'])} tickers, {len(resultado['frontera'])} puntos, "
              f"máximo Sharpe {ms['sharpe']:.2f} con {len(ms['pesos'])} tickers"
              + (f" ({len(resultado['excluidos'])} excluidos)" if resultado['excluidos'] else ""))


def main():
    if not almacenamiento.hay_base_de_datos():
        print("ERROR: no hay base de datos configurada en .streamlit/secrets.toml")
        return 1

    datos = almacenamiento.cargar_tickers({"etf_list": [], "stock_list": []})
    etfs = list(dict.fromkeys(datos.get("etf_list", [])))
    acciones = list(dict.fromkeys(datos.get("stock_list", [])))
    tickers = list(dict.fromkeys(etfs + acciones))
    if not tickers:
        print("ERROR: la lista de tickers está vacía")
        return 1

    # También los precios de los tickers del portafolio personal que no estén en las listas
    # y el S&P 500, que la pestaña Comparar usa como referencia.
    precios = actualizar_precios(list(dict.fromkeys(
        tickers + almacenamiento.tickers_de_posiciones() + [INDICE_REFERENCIA])))
    con_precios = len(precios.columns)

    n_ok, n_total = actualizar_metricas(etfs, acciones)
    if n_ok == 0:
        print("AVISO: Yahoo no devolvió datos de ningún ticker. Se conservan los registros guardados.")

    if con_precios > 0:
        actualizar_fronteras(precios, etfs, acciones)

    # Falla el proceso (y GitHub te avisa por correo) solo si no se pudo bajar ningún precio
    return 0 if con_precios > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
