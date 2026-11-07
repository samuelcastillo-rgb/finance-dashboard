# scripts/actualizar_datos.py
# Proceso diario (lo ejecuta el GitHub Action .github/workflows/actualizar_datos.yml,
# pero también se puede correr a mano: python -m scripts.actualizar_datos).
#
# 1. Lee la lista de tickers de la base de datos.
# 2. Descarga 5 años de precios de cierre ajustados (de los tickers analizados y de los
#    del portafolio personal) y los guarda en precios_diarios.
# 3. Calcula el registro de cada ticker (nombre, categoría/sector, fundamentales,
#    ratios de estados financieros) con datos_mercado.py y lo guarda en la tabla
#    metricas. Esto también actualiza los metadatos. Si Yahoo falla con un ticker,
#    se conserva su registro anterior.
#
# La app lee todo esto de la base, así que no consulta a Yahoo en cada visita.
#
# Necesita la conexión en .streamlit/secrets.toml ([connections.postgresql]).

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from finanzas import almacenamiento
from finanzas import datos_mercado as dm

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
    return len(precios.columns)


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
    con_precios = actualizar_precios(list(dict.fromkeys(tickers + almacenamiento.tickers_de_posiciones())))

    n_ok, n_total = actualizar_metricas(etfs, acciones)
    if n_ok == 0:
        print("AVISO: Yahoo no devolvió datos de ningún ticker. Se conservan los registros guardados.")

    # Falla el proceso (y GitHub te avisa por correo) solo si no se pudo bajar ningún precio
    return 0 if con_precios > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
