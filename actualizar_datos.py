# actualizar_datos.py
# Proceso diario (lo ejecuta el GitHub Action .github/workflows/actualizar_datos.yml,
# pero también se puede correr a mano: python actualizar_datos.py).
#
# 1. Lee la lista de tickers de la base de datos.
# 2. Descarga 5 años de precios de cierre ajustados y los guarda en precios_diarios.
# 3. Intenta actualizar los metadatos (nombre, categoría, sector). Si Yahoo bloquea
#    `info` desde el servidor, se conservan los metadatos que ya había.
#
# Necesita la conexión en .streamlit/secrets.toml ([connections.postgresql]).

import sys

import pandas as pd
import yfinance as yf

import almacenamiento
from actualizar_metadatos import actualizar_metadatos

PERIODO_PRECIOS = "5y"  # el mismo periodo que usa app.py


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


def main():
    if not almacenamiento.hay_base_de_datos():
        print("ERROR: no hay base de datos configurada en .streamlit/secrets.toml")
        return 1

    datos = almacenamiento.cargar_tickers({"etf_list": [], "stock_list": []})
    tickers = list(dict.fromkeys(datos.get("etf_list", []) + datos.get("stock_list", [])))
    if not tickers:
        print("ERROR: la lista de tickers está vacía")
        return 1

    con_precios = actualizar_precios(tickers)

    # En el servidor no tiene sentido escribir metadata_cache.json (no se sube al repo)
    n_ok, n_total = actualizar_metadatos(escribir_json=False)
    if n_ok == 0:
        print("AVISO: Yahoo no devolvió metadatos (probablemente bloquea `info` desde "
              "este servidor). Se conservan los metadatos guardados.")

    # Falla el proceso (y GitHub te avisa por correo) solo si no se pudo bajar ningún precio
    return 0 if con_precios > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
