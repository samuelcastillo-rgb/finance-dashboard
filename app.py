# app.py
# Capa de presentación del Finance Quantitative Dashboard.
# Tipografía de la UI: DM Sans (Google Fonts). Fallback: system-ui, -apple-system,
# 'Segoe UI', Roboto, sans-serif. Las decisiones visuales viven solo en este archivo;
# los módulos de cálculo (etf_ratios.py, stock_ratios.py) no conocen la presentación.

import html
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

import etf_ratios as er
import stock_ratios as sr

# Carga automática del respaldo consolidado
try:
    with open("metadata_cache.json", "r", encoding="utf-8") as f:
        CACHE_GLOBAL = json.load(f)
except Exception:
    CACHE_GLOBAL = {"etf_list": {}, "stock_list": {}}

# ------------------------------------------------------------------------------
# 0. CONSTANTES: PALETA, NIVELES DE SCORE Y DEFINICIÓN ÚNICA DE LAS FÓRMULAS
# ------------------------------------------------------------------------------
FUENTE_GRAFICOS = "DM Sans, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"

PALETA = {
    'primario': '#1dbe83',
    'tinta': '#0F172A',
    'texto': '#334155',
    'suave': '#64748B',
    'borde': '#E2E8F0',
    'fondo': '#F8FAFC',
    'alerta': '#F59E0B',
    'riesgo': '#EF4444',
}
ESCALA_SCORE = [PALETA['riesgo'], PALETA['alerta'], PALETA['primario']]
ESCALA_CORR = [PALETA['riesgo'], '#F8FAFC', PALETA['primario']]
COLORES_COMPONENTES = ['#0F172A', '#1dbe83', '#38BDF8', '#F59E0B',
                       '#A78BFA', '#F472B6', '#94A3B8', '#FB923C']

# (umbral mínimo, nombre, clase CSS). El orden importa: de mayor a menor.
NIVELES_SCORE = [(80, 'Excelente', 'excelente'), (60, 'Bueno', 'bueno'),
                 (40, 'Neutral', 'neutral'), (0, 'Débil', 'debil')]

# Cobertura mínima (fracción del peso total con dato) para calcular un score. Por debajo,
# el score reflejaría muy pocos criterios y se deja sin calcular.
MIN_COBERTURA = 0.5

NOTA_REESCALADO = ('Si a un activo le falta un criterio (sin dato en Yahoo Finance), su peso se reparte '
                   'entre los demás: cada barra siempre suma su score.')

# Cada componente: (etiqueta, columna de percentil, peso, columna con el valor real).
# Estas listas son la ÚNICA fuente de verdad de la fórmula: se usan para calcular el
# score, para el gráfico de aportes, para el inspector y para los textos explicativos.
COMPONENTES_ETFS = [
    ('Sortino', 'Pctl_Sortino', 0.34, 'Sortino'),
    ('CAGR 5a', 'Pctl_CAGR', 0.34, 'CAGR_%'),
    ('Costo (TER inv.)', 'Pctl_Exp_Ratio_Inv', 0.17, 'Expense_Ratio_%'),
    ('AUM (tamaño)', 'Pctl_AUM', 0.15, 'AUM_BUSD'),
]
COMPONENTES_ACCIONES = [
    ('ROIC', 'Pctl_ROIC', 0.20, 'ROIC_%'),
    ('Sortino', 'Pctl_Sortino', 0.20, 'Sortino'),
    ('CAGR 5a', 'Pctl_CAGR', 0.15, 'CAGR_%'),
    ('Margen neto', 'Pctl_Margin', 0.15, 'Net_Margin_%'),
    ('ROE', 'Pctl_ROE', 0.10, 'ROE_%'),
    ('Deuda/Equity (inv.)', 'Pctl_Debt_Inv', 0.10, 'Debt_to_Equity'),
    ('ROA', 'Pctl_ROA', 0.05, 'ROA_%'),
    ('EBITDA', 'Pctl_EBITDA', 0.05, 'EBITDA_MUSD'),
]


def nivel_score(score):
    """Devuelve (nombre, clase_css) del nivel cualitativo de un score 0-100."""
    try:
        valor = float(score)
    except (TypeError, ValueError):
        return 'Sin dato', 'neutral'
    if pd.isna(valor):
        return 'Sin dato', 'neutral'
    for umbral, nombre, clase in NIVELES_SCORE:
        if valor >= umbral:
            return nombre, clase
    return 'Débil', 'debil'


def _f(valor, decimales=1, sufijo=''):
    """Formatea un número para mostrarlo; '—' si el dato falta."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return '—'
    if not np.isfinite(v):
        return '—'
    return f'{v:.{decimales}f}{sufijo}'


def peso_disponible(df, componentes):
    """Suma de los pesos de los criterios CON dato, por fila (un NaN no aporta peso)."""
    disponible = 0
    for _, col_pctl, peso, _ in componentes:
        disponible = disponible + peso * df[col_pctl].notna()
    return disponible.round(10)


def cobertura_pct(df, componentes):
    """% del peso total del score que tiene dato (100 = todos los criterios disponibles)."""
    total_pesos = round(sum(c[2] for c in componentes), 10)
    return (peso_disponible(df, componentes) / total_pesos * 100).round(0)


def calcular_score(df, componentes):
    """Score 0-100 = promedio ponderado de percentiles sobre los criterios CON dato.

    Si a un activo le falta un criterio (NaN) no se le castiga con 0: su peso se reparte
    proporcionalmente entre los criterios disponibles. Con todos los datos el resultado es
    idéntico a la suma ponderada clásica. Si el peso disponible es menor que MIN_COBERTURA
    del total, no hay base suficiente y el score es NaN.
    """
    total_pesos = round(sum(c[2] for c in componentes), 10)
    disponible = peso_disponible(df, componentes)
    suma = 0
    for _, col_pctl, peso, _ in componentes:
        suma = suma + peso * df[col_pctl].fillna(0)
    score = suma / disponible.where(disponible > 0)
    score = score.where(disponible / total_pesos >= MIN_COBERTURA)
    return score.round(1)


def fila_extrema(df, columna, mayor=True):
    """Fila con el mayor (o menor) valor de la columna ignorando datos faltantes; None si no hay."""
    serie = pd.to_numeric(df[columna], errors='coerce').dropna()
    if serie.empty:
        return None
    return df.loc[serie.idxmax() if mayor else serie.idxmin()]


def marca_cobertura(fila):
    """Texto ' · datos parciales (65%)' para activos a los que les falta algún criterio."""
    cob = fila.get('Cobertura_%')
    if cob is None or pd.isna(cob) or cob >= 100:
        return ''
    return f' · datos parciales ({cob:.0f}%)'


# ------------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS CSS
# ------------------------------------------------------------------------------
st.set_page_config(page_title="Finance Quantitative Dashboard", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;800&display=swap');

/* Color primario del tema */
:root {
    --primary-color: #1dbe83 !important;
}

/* Fuente general de la app */
html, body, [class*="css"], .stApp {
    font-family: 'DM Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif !important;
    background-color: #F8FAFC !important;
    color: #0F172A !important;
}

.block-container { padding-top: 4.5rem !important; max-width: 1600px; }
footer { visibility: hidden; }

/* Avisos (st.warning/info) en el área principal: texto oscuro legible sobre fondo claro */
[data-testid="stMain"] [data-testid="stAlertContainer"] p,
[data-testid="stMain"] [data-testid="stAlertContainer"] li {
    color: #0F172A !important;
}

/* Etiquetas de pestañas no seleccionadas siempre visibles */
[data-baseweb="tab-list"] button[aria-selected="false"] p { color: #334155 !important; }

/* Títulos principales */
h1, h2, h3, h4, h5, h6 {
    font-family: 'DM Sans', system-ui, sans-serif !important;
    color: #0F172A !important;
    font-weight: 800 !important;
}

/* Pestañas (Tabs) */
[data-baseweb="tab"] p, button[data-baseweb="tab"] * {
    color: #334155 !important;
    font-size: 15px !important;
    font-weight: 700 !important;
}
[aria-selected="true"] p, button[aria-selected="true"] * {
    color: #1dbe83 !important;
    font-weight: 800 !important;
}
[data-baseweb="tab-highlight"] { background-color: #1dbe83 !important; }

/* --- BARRA LATERAL (SIDEBAR) --- */
[data-testid="stSidebar"] { background-color: #0F172A !important; }

/* Aplicar fuente solo a textos reales, NO a los iconos */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] .stCaption {
    font-family: 'DM Sans', system-ui, sans-serif !important;
    color: #F8FAFC !important;
}

/* RESTAURAR FUENTE DE ICONOS DE STREAMLIT (MATERIAL SYMBOLS) */
[data-testid="stIconMaterial"],
.material-symbols-rounded,
.material-icons,
[data-testid="stSidebar"] [data-testid="stIconMaterial"],
[data-testid="stSidebar"] span[translate="no"] {
    font-family: "Material Symbols Rounded", "Material Symbols Outlined", "Material Icons" !important;
}

/* Encabezado de la app */
.app-header {
    display: flex; justify-content: space-between; align-items: flex-end;
    gap: 16px; margin-bottom: 14px; flex-wrap: wrap;
}
.app-title { font-size: 30px; font-weight: 800; color: #0F172A; line-height: 1.1; }
.app-subtitle { font-size: 14px; color: #64748B; margin-top: 4px; }
.app-stamp {
    font-size: 12px; font-weight: 700; color: #64748B; background: #FFFFFF;
    border: 1px solid #E2E8F0; border-radius: 999px; padding: 5px 12px;
}

/* Títulos de sección dentro de tarjetas */
.section-title { font-size: 16px; font-weight: 800; color: #0F172A; margin-bottom: 2px; }
.section-help { font-size: 12.5px; color: #64748B; margin-bottom: 8px; }

/* Tarjetas KPI */
.kpi-card {
    background-color: #FFFFFF; padding: 16px 14px; border-radius: 14px;
    border: 1px solid #E2E8F0; border-top: 4px solid #1dbe83;
    box-shadow: 0px 4px 12px rgba(15, 23, 42, 0.03); text-align: center;
}
.kpi-title { font-size: 11.5px; color: #64748B; font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
.kpi-value { font-size: 26px; color: #0F172A; font-weight: 800; line-height: 1.25; }
.kpi-sub { font-size: 13px; color: #0F9D6B; font-weight: 700; margin-top: 2px; }

/* Píldoras de nivel de score (el color nunca es el único indicador: lleva texto) */
.pill { display: inline-block; font-size: 12px; font-weight: 800; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
.pill-excelente { background: #D1FAE5; color: #047857; }
.pill-bueno { background: #ECFDF5; color: #0F9D6B; border: 1px solid #A7F3D0; }
.pill-neutral { background: #FEF3C7; color: #B45309; }
.pill-debil { background: #FEE2E2; color: #B91C1C; }

/* Tarjetas de líderes con barra de score */
.leader-card {
    background-color: #FFFFFF; padding: 12px 16px; border-radius: 12px;
    margin-bottom: 10px; border: 1px solid #E2E8F0; border-left: 5px solid #1dbe83;
}
.leader-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.leader-ticker { font-size: 16px; font-weight: 800; color: #0F172A; }
.leader-sub { font-size: 12px; color: #64748B; margin-top: 2px; }
.bar { height: 6px; background: #E2E8F0; border-radius: 999px; margin-top: 8px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; }
.bar-excelente { background: #1dbe83; }
.bar-bueno { background: #6EE7B7; }
.bar-neutral { background: #F59E0B; }
.bar-debil { background: #EF4444; }

.inspector-ticker { font-size: 24px; font-weight: 800; color: #0F172A; margin-right: 8px; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 2. GESTIÓN PERSISTENTE DE TICKERS EN DISCO (JSON) Y CANDADO ANTI-DUPLICADOS
# ------------------------------------------------------------------------------
ARCH_TICKERS = 'portfolio_tickers.json'
TICKERS_DEFECTO = {
    'etf_list': ['VOO', 'IVV', 'SPY'],
    'stock_list': ['AAPL', 'MSFT', 'GOOGL']
}


def cargar_tickers():
    if os.path.exists(ARCH_TICKERS):
        try:
            with open(ARCH_TICKERS, 'r') as f:
                return json.load(f)
        except Exception:
            return TICKERS_DEFECTO
    return TICKERS_DEFECTO


def guardar_tickers_disco():
    datos = {
        'etf_list': st.session_state.etf_list,
        'stock_list': st.session_state.stock_list
    }
    with open(ARCH_TICKERS, 'w') as f:
        json.dump(datos, f, indent=4)


# Cargar tickers y ELIMINAR DUPLICADOS automáticamente
if 'etf_list' not in st.session_state or 'stock_list' not in st.session_state:
    tickers_guardados = cargar_tickers()

    # Candado 1: Limpieza de duplicados al iniciar (dict.fromkeys borra repetidos y mantiene el orden)
    lista_etf_limpia = list(dict.fromkeys(tickers_guardados.get('etf_list', TICKERS_DEFECTO['etf_list'])))
    lista_stock_limpia = list(dict.fromkeys(tickers_guardados.get('stock_list', TICKERS_DEFECTO['stock_list'])))

    st.session_state.etf_list = lista_etf_limpia
    st.session_state.stock_list = lista_stock_limpia

    # Si se encontraron y borraron duplicados desde el JSON, forzamos un guardado del archivo limpio
    if len(lista_etf_limpia) < len(tickers_guardados.get('etf_list', [])) or len(lista_stock_limpia) < len(tickers_guardados.get('stock_list', [])):
        guardar_tickers_disco()

if 'ultima_actualizacion' not in st.session_state:
    st.session_state.ultima_actualizacion = datetime.now()

# ------------------------------------------------------------------------------
# 3. FUNCIONES DE CARGA DE DATOS CON CACHÉ DINÁMICO
# ------------------------------------------------------------------------------

# --- CONEXIÓN CON YAHOO FINANCE DESDE LA NUBE ---
# No se pasa una sesión propia: yfinance usa curl_cffi, que imita la huella TLS de un navegador.
# Una sesión de `requests` con cabeceras falsas no la imita, y Yahoo suele bloquear `info`
# (error 429) desde servidores en la nube aunque los precios sí se descarguen.

# Hilos simultáneos para consultar Yahoo (info y estados financieros son E/S de red).
# Más hilos acelera la carga inicial pero aumenta el riesgo de que Yahoo limite peticiones.
MAX_HILOS_YAHOO = 4
INTENTOS_INFO = 3


def obtener_info(ticker):
    """`ticker.info` con reintentos y espera creciente (Yahoo rechaza ráfagas con 429).
    Devuelve {} si no hay respuesta útil tras todos los intentos."""
    for intento in range(INTENTOS_INFO):
        try:
            info = ticker.info or {}
            # Una respuesta bloqueada suele traer solo un par de claves sin datos
            if len(info) > 5:
                return info
        except Exception:
            pass
        if intento < INTENTOS_INFO - 1:
            time.sleep(1.5 * (intento + 1))
    return {}


@st.cache_data(ttl=3600, show_spinner="Descargando precios históricos…")
def descargar_precios_cierre(universo_tuple, period="5y"):
    """Precios de cierre ajustados de TODOS los tickers en una sola descarga (columnas = tickers).
    Sustituye a una descarga por ticker: es la parte más lenta de la carga inicial."""
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


# ------------------------------------------------------------------------------
# CARGA ROBUSTA DE ETFS (CON EXTRACCIÓN DIRECTA Y NORMALIZACIÓN)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def obtener_metrica_etf_individual(symbol):
    try:
        etf = yf.Ticker(symbol)
        info = obtener_info(etf)

        # Soportar ambas formas posibles en las que se pudo haber guardado el JSON
        dict_etfs = CACHE_GLOBAL.get("etfs") or CACHE_GLOBAL.get("etf_list") or {}
        fallback = dict_etfs.get(symbol.upper(), {
            'Nombre': symbol, 'Category': 'General', 'Expense_Ratio_%': 0.0, 'AUM_BUSD': 0.0
        })

        nombre = info.get('shortName') or info.get('longName') or fallback.get('Nombre', symbol)

        categoria = (
            info.get('category') or info.get('legalType') or
            info.get('quoteType') or info.get('fundFamily')
        )
        if not categoria or categoria in ['General', 'Sin Categoría']:
            categoria = fallback.get('Category', 'General')

        exp_raw = info.get('netExpenseRatio') or info.get('annualReportExpenseRatio') or info.get('expenseRatio')
        if exp_raw is not None and float(exp_raw) > 0:
            exp_float = float(exp_raw)
            exp_ratio = round(exp_float * 100, 3) if exp_float < 0.005 else round(exp_float, 3)
        else:
            exp_ratio = fallback.get('Expense_Ratio_%', 0.0)

        aum_raw = info.get('totalAssets')
        if aum_raw and float(aum_raw) > 0:
            aum_busd = round(float(aum_raw) / 1e9, 2)
        else:
            aum_busd = fallback.get('AUM_BUSD', 0.0)

        raw_52w = info.get('52WeekChange')
        change_52w = round(float(raw_52w) * 100, 2) if raw_52w is not None else 0.0

        fund = {
            'Nombre': nombre,
            'Category': categoria,
            'Expense_Ratio_%': exp_ratio,
            'AUM_BUSD': aum_busd,
            '52W_Change_%': change_52w
        }

        # El rendimiento (CAGR, Sortino, etc.) se calcula en cargar_datos_etfs a partir de la
        # descarga conjunta de precios.

        # Rendimiento por dividendo (informativo, no entra al score)
        try:
            rendimiento = er.get_etf_fundamentals(etf).get('Yield_%', 0.0)
        except Exception:
            rendimiento = 0.0

        reg = {'Ticker': symbol}
        reg.update(fund)
        reg['Yield_%'] = rendimiento
        return reg
    except Exception:
        return None


def cargar_datos_etfs(universo_tuple, precios):
    resultados = []
    for symbol, datos_etf in zip(universo_tuple,
                                 obtener_en_paralelo(obtener_metrica_etf_individual, universo_tuple, "Cargando ETFs")):
        if datos_etf:
            # etf_ratios calcula CAGR, Volatilidad, Sharpe, Sortino y Max Drawdown con las
            # mismas fórmulas que stock_ratios para CAGR/Volatilidad/Sortino.
            datos_etf = dict(datos_etf)
            datos_etf.update(er.calculate_etf_performance_from_prices(serie_precios(precios, symbol)))
            resultados.append(datos_etf)

    if not resultados:
        return pd.DataFrame()

    df = pd.DataFrame(resultados)

    # Columnas informativas: sin dato = 0.
    columnas_default = {
        'Category': 'General', '52W_Change_%': 0.0, 'Yield_%': 0.0
    }
    for col, default_val in columnas_default.items():
        if col not in df.columns:
            df[col] = default_val
        else:
            if isinstance(default_val, (int, float)):
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(default_val)
            else:
                df[col] = df[col].fillna(default_val)

    # Las que alimentan el score o el análisis de riesgo se quedan como NaN = "sin dato":
    # ni 0 (que puntuaría como un valor real) ni el mejor percentil.
    for col in ['Expense_Ratio_%', 'AUM_BUSD', 'Sortino', 'CAGR_%', 'Volatilidad_%', 'Sharpe', 'Max_Drawdown_%']:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors='coerce')
    # TER = 0 es el valor de relleno de un dato no reportado (como "mejor costo" falsearía el score)
    df.loc[df['Expense_Ratio_%'] <= 0, 'Expense_Ratio_%'] = np.nan
    # Igual con el AUM: 0 es el relleno de "no reportado", y ahora el AUM puntúa
    df.loc[df['AUM_BUSD'] <= 0, 'AUM_BUSD'] = np.nan

    df['Pctl_Exp_Ratio_Inv'] = (1 - df['Expense_Ratio_%'].rank(pct=True, ascending=True)) * 100
    df['Pctl_AUM'] = df['AUM_BUSD'].rank(pct=True, ascending=True) * 100
    df['Pctl_Sortino'] = df['Sortino'].rank(pct=True, ascending=True) * 100
    df['Pctl_CAGR'] = df['CAGR_%'].rank(pct=True, ascending=True) * 100

    df['Score_Final'] = calcular_score(df, COMPONENTES_ETFS)
    df['Cobertura_%'] = cobertura_pct(df, COMPONENTES_ETFS)

    return df.sort_values(by='Score_Final', ascending=False)


# ------------------------------------------------------------------------------
# CARGA INDIVIDUAL DE ACCIONES (BLINDADA CON CACHÉ Y FALLBACK)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def obtener_metrica_individual(symbol):
    try:
        stock = yf.Ticker(symbol)
        info = obtener_info(stock)

        dict_stocks = CACHE_GLOBAL.get("stocks") or CACHE_GLOBAL.get("stock_list") or {}
        fallback = dict_stocks.get(symbol.upper(), {
            'Empresa': symbol, 'Sector': 'General'
        })

        empresa = info.get('shortName') or info.get('longName') or fallback.get('Empresa', symbol)

        sector = info.get('sector') or info.get('industry')
        if not sector or sector in ['General', 'Sin Sector']:
            sector = fallback.get('Sector', 'General')

        # Sin dato de Yahoo -> None ("—" en la tabla), no un +0.00% engañoso
        try:
            raw_52w = info.get('52WeekChange')
            change_52w = round(float(raw_52w) * 100, 2) if raw_52w is not None else None
        except Exception:
            change_52w = None

        try:
            bs = stock.balance_sheet
            cf = stock.cashflow
            fin = stock.financials
        except Exception:
            bs, cf, fin = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # Columnas informativas (no entran al score): si Yahoo no trae la fila, "sin dato" (None)
        try:
            clave_eq = next((k for k in ['Stockholders Equity', 'Total Equity Gross Minority Interest', 'Common Stock Equity'] if k in bs.index), None)
            cagr_equity = sr.calcular_cagr_serie(bs.loc[clave_eq]) if clave_eq is not None else None
        except Exception:
            cagr_equity = None

        try:
            clave_fcf = next((k for k in ['Free Cash Flow', 'FreeCashFlow'] if k in cf.index), None)
            cagr_fcf = sr.calcular_cagr_serie(cf.loc[clave_fcf]) if clave_fcf is not None else None
        except Exception:
            cagr_fcf = None

        try:
            clave_ebitda = next((k for k in ['Normalized EBITDA', 'EBITDA'] if k in fin.index), None)
            cagr_ebitda = sr.calcular_cagr_serie(fin.loc[clave_ebitda]) if clave_ebitda is not None else None
        except Exception:
            cagr_ebitda = None

        try:
            fund = sr.get_stock_fundamentals(stock) if hasattr(sr, 'get_stock_fundamentals') else {}
        except Exception:
            fund = {}

        # El rendimiento (CAGR, Sortino) se calcula en cargar_datos_acciones a partir de la
        # descarga conjunta de precios.
        reg = {
            'Ticker': symbol,
            'Empresa': empresa,
            'Sector': sector,
            '52W_Change_%': change_52w,
            'CAGR_Equity_%': cagr_equity,
            'CAGR_FCF_%': cagr_fcf,
            'CAGR_EBITDA_%': cagr_ebitda
        }

        if 'Empresa' in fund: del fund['Empresa']
        if 'Sector' in fund: del fund['Sector']

        reg.update(fund)

        return reg
    except Exception:
        return {'Ticker': symbol, 'Score_Final': 0, 'Sector': 'General', 'Empresa': symbol}


# 2. Orquestador: consulta en paralelo los tickers (los ya cacheados vuelven al instante)
def cargar_datos_acciones(universo_tuple, precios):
    resultados = []
    for symbol, datos_accion in zip(universo_tuple,
                                    obtener_en_paralelo(obtener_metrica_individual, universo_tuple, "Cargando acciones")):
        if datos_accion:
            datos_accion = dict(datos_accion)
            datos_accion.update(sr.calculate_stock_performance_from_prices(serie_precios(precios, symbol)))
            resultados.append(datos_accion)

    if not resultados:
        return pd.DataFrame()

    df = pd.DataFrame(resultados)

    # Un criterio sin dato (Yahoo no lo entrega, p. ej. EBITDA/ROIC en bancos) queda como NaN:
    # no puntúa como 0 ni como el mejor, y el score re-escala los pesos de los demás.
    # Un ticker que falló por completo trae solo su registro de emergencia: todo NaN.
    for _, _, _, col_valor in COMPONENTES_ACCIONES:
        if col_valor not in df.columns:
            df[col_valor] = np.nan
        df[col_valor] = pd.to_numeric(df[col_valor], errors='coerce')
    for col in ['52W_Change_%', 'CAGR_Equity_%', 'CAGR_FCF_%', 'CAGR_EBITDA_%', 'Volatilidad_%']:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Asegurar tamaño positivo para Plotly (sin dato -> tamaño mínimo)
    df['EBITDA_Size'] = df['EBITDA_MUSD'].fillna(0).clip(lower=0.1)

    # Percentiles y Score
    df['Pctl_ROIC'] = df['ROIC_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Sortino'] = df['Sortino'].rank(pct=True, ascending=True) * 100
    df['Pctl_CAGR'] = df['CAGR_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Margin'] = df['Net_Margin_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_ROE'] = df['ROE_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Debt_Inv'] = (1 - df['Debt_to_Equity'].rank(pct=True, ascending=True)) * 100
    df['Pctl_ROA'] = df['ROA_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_EBITDA'] = df['EBITDA_MUSD'].rank(pct=True, ascending=True) * 100

    df['Score_Final'] = calcular_score(df, COMPONENTES_ACCIONES)
    df['Cobertura_%'] = cobertura_pct(df, COMPONENTES_ACCIONES)

    return df.sort_values(by='Score_Final', ascending=False)


def ultimos_meses(precios, tickers, meses):
    """Recorta la descarga conjunta a los tickers y a los últimos `meses` (sin nueva descarga)."""
    columnas = [t for t in tickers if t in precios.columns]
    if not columnas:
        return pd.DataFrame()
    recorte = precios[columnas]
    recorte = recorte[recorte.index >= recorte.index.max() - pd.DateOffset(months=meses)]
    return recorte.dropna(axis=0, how='all').dropna(axis=1, how='all')


def generar_grafico_tendencia_6m(precios_todos, tickers_lista, titulo_grafico):
    if not tickers_lista:
        return None

    # Precios de cierre de 6 meses, recortados de la descarga conjunta
    precios = ultimos_meses(precios_todos, tickers_lista, 6)
    if precios.empty:
        return None

    # Normalizar a retorno porcentual (%) desde el primer precio disponible de cada activo
    retornos_pct = ((precios / precios.bfill().iloc[0]) - 1) * 100

    fig = px.line(
        retornos_pct,
        x=retornos_pct.index,
        y=retornos_pct.columns,
        title=titulo_grafico,
        labels={'value': 'Rendimiento acumulado (%)', 'Date': 'Fecha', 'variable': 'Activo'}
    )
    fig.update_yaxes(zeroline=True, zerolinecolor="#94A3B8")
    return aplicar_estilo_grafico(fig, altura=380, leyenda_abajo=True)


def calcular_matriz_correlacion(precios_todos, tickers_list):
    if not tickers_list or len(tickers_list) < 2:
        return pd.DataFrame()
    # Precios de 1 año recortados de la descarga conjunta (vacía si falló: sin matriz)
    data = ultimos_meses(precios_todos, tickers_list, 12)
    if data.shape[1] < 2:
        return pd.DataFrame()
    returns = data.pct_change().dropna()
    return returns.corr().round(2)


# Carga de data usando las listas del session_state. Una única descarga de precios para
# ETFs y acciones; info y estados financieros se piden en paralelo.
universo_precios = tuple(dict.fromkeys(st.session_state.etf_list + st.session_state.stock_list))
precios_cierre = descargar_precios_cierre(universo_precios)
df_etfs = cargar_datos_etfs(tuple(st.session_state.etf_list), precios_cierre)
df_stocks = cargar_datos_acciones(tuple(st.session_state.stock_list), precios_cierre)
n_etfs_universo = len(df_etfs)
n_stocks_universo = len(df_stocks)


# ------------------------------------------------------------------------------
# 4. BARRA LATERAL (CONTROL DE PORTAFOLIO Y FILTROS)
# ------------------------------------------------------------------------------
st.sidebar.header("Menu")
st.sidebar.caption("Control de Portafolio")
st.sidebar.write("---")

with st.sidebar.expander("⚙️ Gestor de Activos", expanded=False):
    tipo_activo = st.radio("Tipo de activo a gestionar:", ["ETF", "Acción Individual"])

    if tipo_activo == "ETF":
        nuevo_etf = st.text_input("Ingresar Ticker ETF:", placeholder="Ej. ARKK").strip().upper()
        if st.button("➕ Añadir ETF", width='stretch'):
            if nuevo_etf:
                # Candado 2: Verificar si ya existe antes de añadir
                if nuevo_etf not in st.session_state.etf_list:
                    st.session_state.etf_list.append(nuevo_etf)
                    guardar_tickers_disco()
                    st.sidebar.success(f"ETF '{nuevo_etf}' agregado.")
                    st.rerun()
                else:
                    st.sidebar.error(f"⚠️ El ETF '{nuevo_etf}' ya está en la lista.")

        if st.session_state.etf_list:
            etf_borrar = st.selectbox("Seleccionar ETF a borrar:", st.session_state.etf_list)
            if st.button("🗑️ Borrar ETF", width='stretch'):
                st.session_state.etf_list.remove(etf_borrar)
                guardar_tickers_disco()
                st.sidebar.warning(f"ETF '{etf_borrar}' eliminado.")
                st.rerun()
    else:
        nueva_stock = st.text_input("Ingresar Ticker Acción:", placeholder="Ej. AMD").strip().upper()
        if st.button("➕ Añadir Acción", width='stretch'):
            if nueva_stock:
                # Candado 2: Verificar si ya existe antes de añadir
                if nueva_stock not in st.session_state.stock_list:
                    st.session_state.stock_list.append(nueva_stock)
                    guardar_tickers_disco()
                    st.sidebar.success(f"Acción '{nueva_stock}' agregada.")
                    st.rerun()
                else:
                    st.sidebar.error(f"⚠️ La acción '{nueva_stock}' ya está en la lista.")

        if st.session_state.stock_list:
            stock_borrar = st.selectbox("Seleccionar Acción a borrar:", st.session_state.stock_list)
            if st.button("🗑️ Borrar Acción", width='stretch'):
                st.session_state.stock_list.remove(stock_borrar)
                guardar_tickers_disco()
                st.sidebar.warning(f"Acción '{stock_borrar}' eliminada.")
                st.rerun()

if st.sidebar.button("🔄 Actualizar datos", width='stretch'):
    st.cache_data.clear()
    st.session_state.ultima_actualizacion = datetime.now()
    st.rerun()

# --- FILTROS DE ANÁLISIS ---
st.sidebar.markdown("<hr style='margin: 15px 0px; border-color: #334155;'>", unsafe_allow_html=True)
st.sidebar.caption("Filtros de Análisis")

top_n = st.sidebar.slider("Top N en gráficos", min_value=5, max_value=30, value=10, step=1,
                          help="Cuántos activos mostrar en rankings, etiquetas, tendencia y correlación.")
score_minimo = st.sidebar.slider("Score mínimo", min_value=0, max_value=100, value=0, step=5,
                                 help="Oculta activos con score menor. El score se calcula antes de filtrar.")

categoria_sel = "Todas"
if not df_etfs.empty and 'Category' in df_etfs.columns:
    categorias_validas = [str(c) for c in df_etfs['Category'].dropna().unique() if str(c).strip()]
    if categorias_validas:
        categorias_opt = ["Todas"] + sorted(categorias_validas)
        categoria_sel = st.sidebar.selectbox("Sector / Categoría (ETFs):", categorias_opt)
        if categoria_sel != "Todas":
            df_etfs = df_etfs[df_etfs['Category'] == categoria_sel]

sector_sel = "Todos"
if not df_stocks.empty:
    sectores_opt = ["Todos"] + sorted(df_stocks['Sector'].dropna().astype(str).unique().tolist())
    sector_sel = st.sidebar.selectbox("Sector (Acciones):", sectores_opt)
    if sector_sel != "Todos":
        df_stocks = df_stocks[df_stocks['Sector'] == sector_sel]

# Con score mínimo 0 no se filtra nada: así los activos sin score (cobertura insuficiente)
# siguen visibles en vez de desaparecer en silencio.
if score_minimo > 0:
    if not df_etfs.empty:
        df_etfs = df_etfs[df_etfs['Score_Final'] >= score_minimo]
    if not df_stocks.empty:
        df_stocks = df_stocks[df_stocks['Score_Final'] >= score_minimo]


# ------------------------------------------------------------------------------
# 4.1 COMPONENTES VISUALES REUTILIZABLES
# ------------------------------------------------------------------------------
def aplicar_estilo_grafico(fig, altura=None, leyenda_abajo=False):
    """Aplica contraste alto y tipografía uniforme a cualquier gráfico Plotly."""
    hay_titulo = bool(fig.layout.title.text)
    fig.update_layout(
        font=dict(family=FUENTE_GRAFICOS, color=PALETA['texto'], size=12),
        title_font=dict(family=FUENTE_GRAFICOS, color=PALETA['tinta'], size=15),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        margin=dict(l=10, r=10, t=50 if hay_titulo else 20, b=10),
        hoverlabel=dict(font_family=FUENTE_GRAFICOS),
        legend=dict(font=dict(color=PALETA['texto'], size=11),
                    title_font=dict(color=PALETA['tinta'], size=12)),
    )
    fig.update_xaxes(title_font=dict(color=PALETA['tinta'], size=13),
                     tickfont=dict(color="#06152B", size=11),
                     gridcolor=PALETA['borde'], linecolor="#CBD5E1")
    fig.update_yaxes(title_font=dict(color=PALETA['tinta'], size=13),
                     tickfont=dict(color="#06152B", size=11),
                     gridcolor=PALETA['borde'], linecolor="#CBD5E1")
    if altura:
        fig.update_layout(height=altura)
    if leyenda_abajo:
        fig.update_layout(legend=dict(orientation='h', yanchor='top', y=-0.18, x=0))
    return fig


def nota_omitidos(df, columnas):
    """Aviso bajo un gráfico de dispersión: activos sin dato en algún eje no se dibujan."""
    faltan = int(df[columnas].isna().any(axis=1).sum())
    if faltan:
        st.caption(f"{faltan} sin dato en algún eje: no aparecen en este gráfico.")


def titulo_seccion(titulo, ayuda=""):
    bloque = f'<div class="section-title">{html.escape(titulo)}</div>'
    if ayuda:
        bloque += f'<div class="section-help">{html.escape(ayuda)}</div>'
    st.markdown(bloque, unsafe_allow_html=True)


def tarjeta_kpi(titulo, valor, sub=""):
    return (f'<div class="kpi-card"><div class="kpi-title">{html.escape(str(titulo))}</div>'
            f'<div class="kpi-value">{html.escape(str(valor))}</div>'
            f'<div class="kpi-sub">{html.escape(str(sub))}</div></div>')


def mostrar_kpis(items):
    columnas = st.columns(len(items))
    for col, (titulo, valor, sub) in zip(columnas, items):
        col.markdown(tarjeta_kpi(titulo, valor, sub), unsafe_allow_html=True)


def tarjeta_lider(ticker, linea_secundaria, score):
    nombre, clase = nivel_score(score)
    valor = 0.0 if pd.isna(score) else float(score)
    ancho = max(0.0, min(100.0, valor))
    return (f'<div class="leader-card"><div class="leader-top">'
            f'<span class="leader-ticker">{html.escape(str(ticker))}</span>'
            f'<span class="pill pill-{clase}">{valor:.1f} · {nombre}</span></div>'
            f'<div class="leader-sub">{html.escape(str(linea_secundaria))}</div>'
            f'<div class="bar"><div class="bar-fill bar-{clase}" style="width:{ancho}%"></div></div></div>')


def grafico_ranking(df, top_n):
    top = df.nlargest(top_n, 'Score_Final').sort_values('Score_Final', ascending=True)
    fig = px.bar(top, x='Score_Final', y='Ticker', orientation='h', color='Score_Final',
                 color_continuous_scale=ESCALA_SCORE, range_color=[0, 100], text='Score_Final',
                 labels={'Score_Final': 'Score', 'Ticker': ''})
    fig.update_traces(texttemplate='%{text:.1f}', textposition='outside', cliponaxis=False)
    fig.update_coloraxes(showscale=False)
    fig.update_xaxes(range=[0, 108])
    return aplicar_estilo_grafico(fig, altura=max(280, 34 * len(top) + 60))


def grafico_contribuciones(df, componentes, top_n):
    """Barras apiladas: cuántos puntos aporta cada criterio al score final.
    El peso aplicado es peso / peso disponible, así que cada barra suma exactamente su score."""
    top = df.nlargest(top_n, 'Score_Final').sort_values('Score_Final', ascending=True)
    disponible = peso_disponible(top, componentes).where(lambda s: s > 0)
    fig = go.Figure()
    for i, (etiqueta, col_pctl, peso, _) in enumerate(componentes):
        fig.add_bar(
            y=top['Ticker'], x=top[col_pctl].fillna(0) * peso / disponible, orientation='h',
            name=f'{etiqueta} ({peso:.0%})',
            marker_color=COLORES_COMPONENTES[i % len(COLORES_COMPONENTES)],
            hovertemplate='%{y}<br>' + etiqueta + ': %{x:.1f} pts<extra></extra>',
        )
    fig.update_layout(barmode='stack')
    fig.update_xaxes(title_text='Puntos de score aportados')
    return aplicar_estilo_grafico(fig, altura=max(320, 34 * len(top) + 140), leyenda_abajo=True)


def grafico_radar(fila, componentes, nombre):
    etiquetas = [c[0] for c in componentes]
    # Un criterio sin dato se deja como hueco (None), no como 0 (que se vería como "el peor")
    valores = [float(v) if pd.notna(v) else None for v in (fila[c[1]] for c in componentes)]
    cierre = etiquetas + [etiquetas[0]]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=valores + [valores[0]], theta=cierre, name=nombre, fill='toself',
        line=dict(color=PALETA['primario'], width=2), fillcolor='rgba(29,190,131,0.25)'))
    fig.add_trace(go.Scatterpolar(
        r=[50] * len(cierre), theta=cierre, name='Mediana del universo',
        line=dict(color=PALETA['suave'], dash='dot', width=1)))
    fig.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100], tickvals=[25, 50, 75, 100],
                                   gridcolor=PALETA['borde'], tickfont=dict(size=10)),
                   angularaxis=dict(tickfont=dict(size=11, color=PALETA['tinta']))),
        showlegend=True, legend=dict(orientation='h', yanchor='top', y=-0.08, x=0),
        font=dict(family=FUENTE_GRAFICOS, color=PALETA['texto']),
        paper_bgcolor="#FFFFFF", margin=dict(l=40, r=40, t=20, b=30), height=340)
    return fig


def grafico_dispersion(df, x, y, col_tamano, hover_data, labels, top_n):
    d = df.copy()
    d['_tam'] = pd.to_numeric(d[col_tamano], errors='coerce').fillna(0).clip(lower=0.1)
    d['_etq'] = np.where(np.arange(len(d)) < top_n, d['Ticker'], '')
    hover = {'_tam': False}
    hover.update({k: v for k, v in hover_data.items() if k in d.columns})
    fig = px.scatter(d, x=x, y=y, size='_tam', size_max=42, color='Score_Final',
                     range_color=[0, 100], hover_name='Ticker', text='_etq', hover_data=hover,
                     color_continuous_scale=ESCALA_SCORE, labels=labels)
    # Líneas de mediana solo si hay datos (con todo el eje sin dato la mediana es NaN)
    mediana_x, mediana_y = d[x].median(), d[y].median()
    if np.isfinite(mediana_x):
        fig.add_vline(x=float(mediana_x), line_dash='dot', line_color=PALETA['suave'], opacity=0.6)
    if np.isfinite(mediana_y):
        fig.add_hline(y=float(mediana_y), line_dash='dot', line_color=PALETA['suave'], opacity=0.6)
    fig.update_traces(textposition='top center',
                      textfont=dict(family=FUENTE_GRAFICOS, color=PALETA['tinta'], size=11),
                      marker=dict(opacity=0.85, line=dict(width=1, color='#FFFFFF')))
    fig.update_coloraxes(colorbar=dict(title='Score', thickness=12))
    return aplicar_estilo_grafico(fig, altura=400)


def grafico_correlacion(tickers):
    matriz = calcular_matriz_correlacion(precios_cierre, tickers)
    if matriz.empty:
        return None
    fig = px.imshow(matriz, text_auto=True, aspect="auto", zmin=-1, zmax=1,
                    color_continuous_scale=ESCALA_CORR)
    fig.update_coloraxes(colorbar=dict(title='ρ', thickness=12))
    return aplicar_estilo_grafico(fig, altura=420)


def _color_variacion(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return ''
    if v > 0:
        return 'color: #0F9D6B; font-weight: 600'
    if v < 0:
        return 'color: #DC2626; font-weight: 600'
    return ''


def _mapear(estilo, funcion, subset):
    # Styler.map existe desde pandas 2.1; antes se llamaba applymap.
    aplicar = getattr(estilo, 'map', None) or getattr(estilo, 'applymap')
    return aplicar(funcion, subset=subset)


def mostrar_tabla(df, columnas, formatos, nombre_archivo, altura=420):
    cols = [c for c in columnas if c in df.columns]
    vista = df[cols].copy()
    if 'Score_Final' in vista.columns:
        vista.insert(vista.columns.get_loc('Score_Final') + 1, 'Nivel',
                     vista['Score_Final'].apply(lambda s: nivel_score(s)[0]))
    fmt = {k: v for k, v in formatos.items() if k in vista.columns}
    estilo = vista.style.format(fmt, na_rep='—')
    if '52W_Change_%' in vista.columns:
        estilo = _mapear(estilo, _color_variacion, ['52W_Change_%'])
    config = None
    if 'Score_Final' in vista.columns:
        config = {'Score_Final': st.column_config.ProgressColumn(
            'Score', min_value=0, max_value=100, format='%.1f')}
    st.dataframe(estilo, hide_index=True, width='stretch', height=altura, column_config=config)
    st.download_button('⬇️ Descargar CSV', vista.to_csv(index=False).encode('utf-8'),
                       file_name=nombre_archivo, mime='text/csv', key=f'dl_{nombre_archivo}')


def mostrar_inspector(df, componentes, clave, col_nombre):
    """Desglose del score de un activo: radar de percentiles + aporte de cada criterio."""
    ticker = st.selectbox('Activo a inspeccionar', df['Ticker'].tolist(), key=f'insp_{clave}')
    fila = df[df['Ticker'] == ticker].iloc[0]
    nivel, clase = nivel_score(fila['Score_Final'])
    nombre = fila.get(col_nombre, ticker)
    izq, der = st.columns([1, 1])
    with izq:
        st.markdown(
            f'<span class="inspector-ticker">{html.escape(str(ticker))}</span>'
            f'<span class="pill pill-{clase}">{_f(fila["Score_Final"])} · {nivel}</span>'
            f'<div class="leader-sub">{html.escape(str(nombre))}</div>', unsafe_allow_html=True)
        st.plotly_chart(grafico_radar(fila, componentes, ticker), width='stretch', key=f'radar_{clave}')
    with der:
        disponible = sum(peso for _, col_pctl, peso, _ in componentes if pd.notna(fila[col_pctl]))
        filas = []
        for etiqueta, col_pctl, peso, col_valor in componentes:
            hay_dato = pd.notna(fila[col_pctl]) and disponible > 0
            filas.append({
                'Criterio': etiqueta,
                'Valor': _f(fila[col_valor], 2),
                'Peso nominal': f'{peso:.0%}',
                'Peso aplicado': f'{peso / disponible:.1%}' if hay_dato else 'sin dato',
                'Percentil': _f(fila[col_pctl]),
                'Aporte (pts)': _f(fila[col_pctl] * peso / disponible) if hay_dato else '—',
            })
        st.dataframe(pd.DataFrame(filas), hide_index=True, width='stretch')
        st.caption('Percentil = posición del activo dentro del universo cargado (100 = el mejor). '
                   'En criterios "inv." menos es mejor, por eso el percentil se invierte. '
                   'Un criterio "sin dato" no suma ni resta: su peso se reparte entre los demás.')


def mostrar_aviso_cobertura(df, componentes, unidad):
    """Aviso plegable con los activos visibles a los que les falta algún criterio y cuál."""
    filas = []
    for _, r in df.iterrows():
        faltan = [c[0] for c in componentes if pd.isna(r[c[1]])]
        if faltan:
            filas.append({'Ticker': r['Ticker'], 'Score': _f(r['Score_Final']),
                          'Cobertura': _f(r['Cobertura_%'], 0, '%'),
                          'Criterios sin dato': ', '.join(faltan)})
    if not filas:
        return
    with st.expander(f"ℹ️ {len(filas)} {unidad} con criterios sin dato en Yahoo Finance"):
        st.markdown(
            "Su score se calcula solo con los criterios disponibles, re-escalando sus pesos: "
            "no se les castiga con 0. Es común en bancos y financieras (sin EBITDA/ROIC) y en "
            f"empresas recién listadas. Con menos de {MIN_COBERTURA:.0%} del peso con dato no se "
            "calcula score.")
        st.dataframe(pd.DataFrame(filas), hide_index=True, width='stretch')


def mostrar_explicacion_score(componentes, unidad):
    with st.expander('¿Cómo se calcula el score?'):
        st.markdown(
            f'Cada métrica se convierte en un **percentil (0–100) dentro de tu universo de {unidad}** '
            'y luego se pondera con estos pesos:')
        st.dataframe(pd.DataFrame(
            [{'Criterio': c[0], 'Peso': f'{c[2]:.0%}'} for c in componentes]),
            hide_index=True, width='stretch')
        st.markdown(
            'Niveles: **Excelente** ≥ 80 · **Bueno** 60–79 · **Neutral** 40–59 · **Débil** < 40.\n\n'
            '**Datos faltantes:** si Yahoo Finance no entrega un criterio (p. ej. EBITDA o ROIC en bancos), '
            'ese criterio se omite y los pesos de los demás se re-escalan; no se le asigna 0. '
            f'Si queda menos del {MIN_COBERTURA:.0%} del peso total con dato, no se calcula score.\n\n'
            '⚠️ El score es **relativo**: si agregas o quitas activos, el de todos cambia. '
            'Los filtros del menú lateral se aplican *después* de calcularlo.')


# ------------------------------------------------------------------------------
# 5. ESTRUCTURA CON PESTAÑAS (ETFs Y ACCIONES)
# ------------------------------------------------------------------------------
st.markdown(
    '<div class="app-header"><div>'
    '<div class="app-title">Finance Quantitative Dashboard</div>'
    '<div class="app-subtitle">Score cuantitativo de ETFs y acciones individuales, '
    'calculado por percentiles dentro de tu universo</div></div>'
    f'<div class="app-stamp">Actualizado {st.session_state.ultima_actualizacion:%d/%m/%Y %H:%M}</div></div>',
    unsafe_allow_html=True)

tab_etf, tab_stock = st.tabs([f"📊 ETFs ({len(st.session_state.etf_list)})",
                              f"🏢 Acciones ({len(st.session_state.stock_list)})"])

# ==============================================================================
# PESTAÑA 1: ETFs
# ==============================================================================
with tab_etf:
    if not st.session_state.etf_list:
        st.warning("No hay ETFs en el listado activo. Añade un ETF desde el menú lateral.")
    elif df_etfs.empty:
        st.warning("No hay ETFs para mostrar: ninguno cumple los filtros actuales o hubo un error en la carga.")
    else:
        st.caption("Evaluación por " + ", ".join(f"{c[0]} {c[2]:.0%}" for c in COMPONENTES_ETFS) +
                   f" · mostrando {len(df_etfs)} de {n_etfs_universo} ETFs")
        mostrar_aviso_cobertura(df_etfs, COMPONENTES_ETFS, "ETFs")

        top_e = df_etfs.iloc[0]
        best_s = fila_extrema(df_etfs, 'Sortino')
        ter_valido = df_etfs[df_etfs['Expense_Ratio_%'] > 0]
        min_t = ter_valido.loc[ter_valido['Expense_Ratio_%'].idxmin()] if not ter_valido.empty else None
        dd_valido = df_etfs[df_etfs['Max_Drawdown_%'] > 0]
        min_dd = dd_valido.loc[dd_valido['Max_Drawdown_%'].idxmin()] if not dd_valido.empty else None

        kpis_etf = [
            ("Top ETF", top_e["Ticker"], f'Score {_f(top_e["Score_Final"])} · {nivel_score(top_e["Score_Final"])[0]}'),
        ]
        if best_s is not None:
            kpis_etf.append(("Mayor Sortino", best_s["Ticker"], f'Ratio {best_s["Sortino"]:.2f}'))
        if min_t is not None:
            kpis_etf.append(("Menor TER", f'{min_t["Expense_Ratio_%"]:.2f}%', min_t["Ticker"]))
        if min_dd is not None:
            kpis_etf.append(("Menor caída máx.", f'{min_dd["Max_Drawdown_%"]:.1f}%', min_dd["Ticker"]))
        kpis_etf.append(("Score promedio", _f(df_etfs["Score_Final"].mean()),
                         f'{len(df_etfs)} ETFs mostrados'))
        mostrar_kpis(kpis_etf)
        st.write("")

        sub_res, sub_score, sub_mercado, sub_datos = st.tabs(
            ["Resumen", "Desglose del score", "Mercado", "Datos"])

        with sub_res:
            izq, der = st.columns([2.2, 1])
            with izq:
                with st.container(border=True):
                    titulo_seccion("Ranking por score", f"Top {min(top_n, len(df_etfs))} ETFs · color = nivel del score")
                    st.plotly_chart(grafico_ranking(df_etfs, top_n), width='stretch', key='rank_etf')
                if 'Volatilidad_%' in df_etfs.columns and 'CAGR_%' in df_etfs.columns:
                    with st.container(border=True):
                        titulo_seccion("Riesgo vs. retorno (5 años)",
                                       "Tamaño = AUM · líneas punteadas = medianas · etiquetas = Top N por score")
                        st.plotly_chart(grafico_dispersion(
                            df_etfs, 'Volatilidad_%', 'CAGR_%', 'AUM_BUSD',
                            {'AUM_BUSD': ':,.1f', 'Sortino': ':.2f', 'Expense_Ratio_%': ':.2f'},
                            {'Volatilidad_%': 'Volatilidad anual (%)', 'CAGR_%': 'CAGR 5a (%)'}, top_n),
                            width='stretch', key='disp_etf')
                        nota_omitidos(df_etfs, ['Volatilidad_%', 'CAGR_%'])
            with der:
                titulo_seccion("Líderes por categoría", "El mejor ETF de cada categoría")
                with st.container(height=700, border=False):
                    for _, r in df_etfs.groupby('Category').head(1).head(12).iterrows():
                        st.markdown(tarjeta_lider(
                            r["Ticker"], f'{r["Category"]} · TER {_f(r["Expense_Ratio_%"], 2, "%")}{marca_cobertura(r)}',
                            r["Score_Final"]),
                            unsafe_allow_html=True)

        with sub_score:
            with st.container(border=True):
                titulo_seccion("¿Qué criterios sostienen el score?",
                               f"Puntos que aporta cada criterio a los Top {min(top_n, len(df_etfs))} ETFs")
                st.plotly_chart(grafico_contribuciones(df_etfs, COMPONENTES_ETFS, top_n),
                                width='stretch', key='contrib_etf')
                st.caption(NOTA_REESCALADO)
            with st.container(border=True):
                titulo_seccion("Inspector de ETF", "Compara el perfil del ETF contra la mediana del universo")
                mostrar_inspector(df_etfs, COMPONENTES_ETFS, 'etf', 'Nombre')
            mostrar_explicacion_score(COMPONENTES_ETFS, 'ETFs')

        with sub_mercado:
            tickers_top = df_etfs.head(top_n)['Ticker'].tolist()
            with st.container(border=True):
                fig_6m = generar_grafico_tendencia_6m(
                    precios_cierre, tickers_top, f"Rendimiento acumulado, 6 meses · Top {len(tickers_top)} por score"
                                 + ("" if categoria_sel == "Todas" else f" · {categoria_sel}"))
                if fig_6m:
                    st.plotly_chart(fig_6m, width='stretch', key='trend_etf')
                else:
                    st.info("No se pudo descargar la tendencia de precios.")
            with st.container(border=True):
                titulo_seccion("Correlación entre ETFs (1 año)",
                               "Valores cercanos a 1 indican que se mueven igual: poca diversificación entre ellos")
                fig_c = grafico_correlacion(df_etfs.head(min(top_n, 12))['Ticker'].tolist())
                if fig_c:
                    st.plotly_chart(fig_c, width='stretch', key='corr_etf')
                else:
                    st.info("Se necesitan al menos 2 ETFs para calcular la correlación.")

        with sub_datos:
            mostrar_tabla(
                df_etfs,
                ['Ticker', 'Nombre', 'Category', 'Score_Final', 'Cobertura_%', '52W_Change_%', 'Expense_Ratio_%',
                 'AUM_BUSD', 'Yield_%', 'Sortino', 'Sharpe', 'CAGR_%', 'Volatilidad_%', 'Max_Drawdown_%'],
                {'Score_Final': '{:.1f}', 'Cobertura_%': '{:.0f}%', '52W_Change_%': '{:+.2f}%', 'Expense_Ratio_%': '{:.2f}%',
                 'Yield_%': '{:.2f}%', 'Sortino': '{:.2f}', 'Sharpe': '{:.2f}', 'CAGR_%': '{:.2f}%',
                 'Volatilidad_%': '{:.2f}%', 'Max_Drawdown_%': '{:.1f}%', 'AUM_BUSD': '${:,.2f}B'},
                'etfs.csv')

# ==============================================================================
# PESTAÑA 2: ACCIONES INDIVIDUALES
# ==============================================================================
with tab_stock:
    if not st.session_state.stock_list:
        st.warning("No hay acciones en el listado activo. Agrega al menos una desde el gestor lateral.")
    elif df_stocks.empty:
        st.warning("No hay acciones para mostrar: ninguna cumple los filtros actuales o hubo un error en la carga.")
    else:
        st.caption("Evaluación fundamental por " + ", ".join(f"{c[0]} {c[2]:.0%}" for c in COMPONENTES_ACCIONES) +
                   f" · mostrando {len(df_stocks)} de {n_stocks_universo} acciones")
        mostrar_aviso_cobertura(df_stocks, COMPONENTES_ACCIONES, "acciones")

        top_stk = df_stocks.iloc[0]
        best_roic = fila_extrema(df_stocks, 'ROIC_%')
        min_debt = fila_extrema(df_stocks, 'Debt_to_Equity', mayor=False)
        best_margin = fila_extrema(df_stocks, 'Net_Margin_%')

        kpis_stk = [("Top Acción", top_stk["Ticker"],
                     f'Score {_f(top_stk["Score_Final"])} · {nivel_score(top_stk["Score_Final"])[0]}')]
        if best_roic is not None:
            kpis_stk.append(("Mayor ROIC", best_roic["Ticker"], f'{best_roic["ROIC_%"]:.1f}%'))
        if min_debt is not None:
            kpis_stk.append(("Menor Deuda/Equity", min_debt["Ticker"], f'D/E {min_debt["Debt_to_Equity"]:.2f}'))
        if best_margin is not None:
            kpis_stk.append(("Mayor margen neto", best_margin["Ticker"], f'{best_margin["Net_Margin_%"]:.1f}%'))
        kpis_stk.append(("Score promedio", _f(df_stocks["Score_Final"].mean()),
                         f'{len(df_stocks)} acciones mostradas'))
        mostrar_kpis(kpis_stk)
        st.write("")

        s_res, s_score, s_mercado, s_datos = st.tabs(
            ["Resumen", "Desglose del score", "Mercado", "Datos"])

        with s_res:
            izq, der = st.columns([2.2, 1])
            with izq:
                with st.container(border=True):
                    titulo_seccion("Ranking por score", f"Top {min(top_n, len(df_stocks))} acciones · color = nivel del score")
                    st.plotly_chart(grafico_ranking(df_stocks, top_n), width='stretch', key='rank_stk')
                with st.container(border=True):
                    titulo_seccion("Calidad de capital: ROIC vs. Sortino",
                                   "Tamaño = EBITDA · líneas punteadas = medianas · arriba a la derecha = mejor")
                    st.plotly_chart(grafico_dispersion(
                        df_stocks, 'Sortino', 'ROIC_%', 'EBITDA_Size',
                        {'EBITDA_MUSD': ':,.0f', 'Net_Margin_%': ':.1f', 'Debt_to_Equity': ':.2f'},
                        {'Sortino': 'Ratio Sortino (riesgo)', 'ROIC_%': 'ROIC (%)',
                         'EBITDA_MUSD': 'EBITDA (MUSD)'}, top_n),
                        width='stretch', key='disp_stk')
                    nota_omitidos(df_stocks, ['Sortino', 'ROIC_%'])
            with der:
                titulo_seccion("Líderes por sector", "La mejor acción de cada sector")
                with st.container(height=700, border=False):
                    for _, r in df_stocks.groupby('Sector').head(1).iterrows():
                        st.markdown(tarjeta_lider(
                            r["Ticker"],
                            f'{r["Empresa"]} · {r["Sector"]} · ROIC {_f(r["ROIC_%"], 1, "%")}{marca_cobertura(r)}',
                            r["Score_Final"]), unsafe_allow_html=True)

        with s_score:
            with st.container(border=True):
                titulo_seccion("¿Qué criterios sostienen el score?",
                               f"Puntos que aporta cada criterio a las Top {min(top_n, len(df_stocks))} acciones")
                st.plotly_chart(grafico_contribuciones(df_stocks, COMPONENTES_ACCIONES, top_n),
                                width='stretch', key='contrib_stk')
                st.caption(NOTA_REESCALADO)
            with st.container(border=True):
                titulo_seccion("Inspector de acción", "Compara el perfil de la empresa contra la mediana del universo")
                mostrar_inspector(df_stocks, COMPONENTES_ACCIONES, 'stk', 'Empresa')
            mostrar_explicacion_score(COMPONENTES_ACCIONES, 'acciones')

        with s_mercado:
            tickers_top_stk = df_stocks.head(top_n)['Ticker'].tolist()
            with st.container(border=True):
                fig_6m_stk = generar_grafico_tendencia_6m(
                    precios_cierre, tickers_top_stk, f"Rendimiento acumulado, 6 meses · Top {len(tickers_top_stk)} por score"
                                     + ("" if sector_sel == "Todos" else f" · {sector_sel}"))
                if fig_6m_stk:
                    st.plotly_chart(fig_6m_stk, width='stretch', key='trend_stk')
                else:
                    st.info("No se pudo descargar la tendencia de precios.")
            with st.container(border=True):
                titulo_seccion("Correlación entre acciones (1 año)",
                               "Valores cercanos a 1 indican que se mueven igual: poca diversificación entre ellas")
                fig_cs = grafico_correlacion(df_stocks.head(min(top_n, 12))['Ticker'].tolist())
                if fig_cs:
                    st.plotly_chart(fig_cs, width='stretch', key='corr_stk')
                else:
                    st.info("Se necesitan al menos 2 acciones para calcular la correlación.")

        with s_datos:
            mostrar_tabla(
                df_stocks,
                ['Ticker', 'Empresa', 'Sector', 'Score_Final', 'Cobertura_%', '52W_Change_%',
                 'CAGR_%', 'CAGR_Equity_%', 'CAGR_FCF_%', 'CAGR_EBITDA_%',
                 'ROIC_%', 'ROE_%', 'ROA_%', 'Sortino', 'Net_Margin_%', 'Debt_to_Equity', 'EBITDA_MUSD'],
                {'Score_Final': '{:.1f}', 'Cobertura_%': '{:.0f}%', '52W_Change_%': '{:+.2f}%', 'CAGR_%': '{:.2f}%',
                 'CAGR_Equity_%': '{:.2f}%', 'CAGR_FCF_%': '{:.2f}%', 'CAGR_EBITDA_%': '{:.2f}%',
                 'ROIC_%': '{:.2f}%', 'ROE_%': '{:.2f}%', 'ROA_%': '{:.2f}%', 'Sortino': '{:.2f}',
                 'Net_Margin_%': '{:.2f}%', 'Debt_to_Equity': '{:.2f}', 'EBITDA_MUSD': '{:,.0f}'},
                'acciones.csv')
