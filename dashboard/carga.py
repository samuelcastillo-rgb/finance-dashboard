"""Carga de datos con caché: registros del proceso diario (base) y Yahoo en vivo para lo que falte."""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
import yfinance as yf
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

from finanzas import almacenamiento
from finanzas import datos_mercado as dm
from finanzas import etf_ratios as er
from finanzas import stock_ratios as sr
from finanzas.score import puntuar_acciones, puntuar_etfs

# Hilos simultáneos para consultar Yahoo en vivo (solo para tickers que aún no están en la base).
# La lógica de consulta a Yahoo vive en datos_mercado.py.
MAX_HILOS_YAHOO = dm.MAX_HILOS_YAHOO


@st.cache_data(ttl=600, show_spinner=False)
def metadatos():
    """Respaldo de metadatos (nombre, categoría, sector) para cuando Yahoo bloquea `info`:
    datos/metadata_cache.json + lo guardado en la base de datos (ver almacenamiento.py)."""
    return almacenamiento.cargar_metadatos()


# --- DATOS DEL PROCESO DIARIO (BASE DE DATOS) ---
# scripts/actualizar_datos.py (GitHub Action) guarda cada día precios y registros por ticker.
# La app los lee de la base y solo consulta a Yahoo en vivo los tickers que aún no
# están (por ejemplo, uno recién agregado). Sin base configurada, todo va en vivo.
@st.cache_data(ttl=600, show_spinner="Leyendo datos guardados…")
def cargar_metricas_guardadas():
    return almacenamiento.cargar_metricas()


@st.cache_data(ttl=600, show_spinner="Leyendo precios guardados…")
def leer_precios_guardados(universo_tuple):
    return almacenamiento.cargar_precios(list(universo_tuple))


@st.cache_data(ttl=3600, show_spinner="Descargando precios históricos…")
def descargar_precios_yahoo(universo_tuple, period="5y"):
    """Precios de cierre ajustados de los tickers dados en una sola descarga (columnas = tickers)."""
    if not universo_tuple:
        return pd.DataFrame()
    try:
        precios = yf.download(list(universo_tuple), period=period, progress=False,
                              auto_adjust=True, threads=True)['Close']
    except Exception:
        return pd.DataFrame()
    if isinstance(precios, pd.Series):
        precios = precios.to_frame(name=universo_tuple[0])
    return precios


def descargar_precios_cierre(universo_tuple):
    """Precios de cierre de TODOS los tickers (columnas = tickers): los guardados en la base
    y, solo para los que falten, una descarga en vivo de Yahoo."""
    guardados = leer_precios_guardados(universo_tuple)
    faltan = tuple(t for t in universo_tuple if t not in guardados.columns)
    if not faltan:
        return guardados
    en_vivo = descargar_precios_yahoo(faltan)
    if guardados.empty:
        return en_vivo
    if en_vivo.empty:
        return guardados
    en_vivo = en_vivo.copy()
    en_vivo.index = pd.to_datetime(en_vivo.index).tz_localize(None).normalize()
    return guardados.join(en_vivo, how='outer')


def serie_precios(precios, symbol):
    """Columna de precios de un ticker; None si no se descargó."""
    if precios is None or symbol not in getattr(precios, 'columns', []):
        return None
    return precios[symbol]


def obtener_en_paralelo(funcion, simbolos, texto_barra):
    """Ejecuta funcion(simbolo) en varios hilos y devuelve los resultados en el orden de simbolos."""
    total = len(simbolos)
    resultados = [None] * total
    if not total:
        return resultados
    ctx = get_script_run_ctx()

    def tarea(simbolo):
        # Los hilos necesitan el contexto de Streamlit para usar st.cache_data sin avisos
        add_script_run_ctx(threading.current_thread(), ctx)
        try:
            return funcion(simbolo)
        except Exception:
            return None

    barra = st.progress(0.0, text=f"{texto_barra}…")
    with ThreadPoolExecutor(max_workers=MAX_HILOS_YAHOO) as pool:
        futuros = {pool.submit(tarea, s): i for i, s in enumerate(simbolos)}
        for n, futuro in enumerate(as_completed(futuros), 1):
            i = futuros[futuro]
            resultados[i] = futuro.result()
            barra.progress(n / total, text=f"{texto_barra} {n}/{total}: {simbolos[i]}")
    barra.empty()
    return resultados


@st.cache_data(ttl=3600)
def obtener_metrica_etf_individual(symbol):
    return dm.obtener_metrica_etf(symbol, metadatos())


def cargar_datos_etfs(universo_tuple, precios):
    # Registros del proceso diario; solo los ETFs que falten se consultan en vivo a Yahoo
    guardados = cargar_metricas_guardadas()[0].get('etf_list', {})
    faltan = [s for s in universo_tuple if s not in guardados]
    en_vivo = dict(zip(faltan, obtener_en_paralelo(obtener_metrica_etf_individual, faltan, "Cargando ETFs")))

    resultados = []
    for symbol in universo_tuple:
        datos_etf = guardados.get(symbol) or en_vivo.get(symbol)
        if datos_etf:
            # etf_ratios calcula CAGR, Volatilidad, Sharpe, Sortino y Max Drawdown con las
            # mismas fórmulas que stock_ratios para CAGR/Volatilidad/Sortino.
            datos_etf = dict(datos_etf)
            datos_etf.update(er.calculate_etf_performance_from_prices(serie_precios(precios, symbol)))
            resultados.append(datos_etf)

    if not resultados:
        return pd.DataFrame()

    df = pd.DataFrame(resultados)
    return puntuar_etfs(df)


@st.cache_data(ttl=3600)
def obtener_metrica_individual(symbol):
    return dm.obtener_metrica_accion(symbol, metadatos())


def cargar_datos_acciones(universo_tuple, precios):
    # Registros del proceso diario; solo las acciones que falten se consultan en vivo a Yahoo
    guardados = cargar_metricas_guardadas()[0].get('stock_list', {})
    faltan = [s for s in universo_tuple if s not in guardados]
    en_vivo = dict(zip(faltan, obtener_en_paralelo(obtener_metrica_individual, faltan, "Cargando acciones")))

    resultados = []
    for symbol in universo_tuple:
        datos_accion = guardados.get(symbol) or en_vivo.get(symbol)
        if datos_accion:
            datos_accion = dict(datos_accion)
            datos_accion.update(sr.calculate_stock_performance_from_prices(serie_precios(precios, symbol)))
            resultados.append(datos_accion)

    if not resultados:
        return pd.DataFrame()

    df = pd.DataFrame(resultados)
    return puntuar_acciones(df)


@st.cache_data(ttl=900, show_spinner="Consultando precios actuales…")
def precios_recientes(tickers_tuple):
    """Último precio disponible de cada ticker a la fecha de consulta (el del día en curso si el
    mercado está abierto) y su fecha. Si Yahoo no responde, usa el último cierre guardado."""
    if not tickers_tuple:
        return {}, None
    try:
        recientes = yf.download(list(tickers_tuple), period="5d", progress=False,
                                auto_adjust=True, threads=True)['Close']
        if isinstance(recientes, pd.Series):
            recientes = recientes.to_frame(name=tickers_tuple[0])
        recientes = recientes.dropna(axis=1, how='all')
        recientes.index = pd.to_datetime(recientes.index).tz_localize(None)
    except Exception:
        recientes = pd.DataFrame()
    faltan = tuple(t for t in tickers_tuple if t not in recientes.columns)
    if faltan:
        guardados = leer_precios_guardados(faltan)
        recientes = guardados if recientes.empty else recientes.join(guardados, how='outer')
    precios, fechas = {}, []
    for t in tickers_tuple:
        if t in recientes.columns and not recientes[t].dropna().empty:
            serie = recientes[t].dropna()
            precios[t] = float(serie.iloc[-1])
            fechas.append(serie.index[-1])
    return precios, (max(fechas) if fechas else None)
