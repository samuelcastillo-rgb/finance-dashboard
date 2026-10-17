# app.py
import streamlit as st
import pandas as pd
import yfinance as yf
import numpy as np
import plotly.express as px
import etf_ratios as er
import stock_ratios as sr

# Carga automática del respaldo consolidado
try:
    with open("metadata_cache.json", "r", encoding="utf-8") as f:
        CACHE_GLOBAL = json.load(f)
except Exception:
    CACHE_GLOBAL = {"etf_list": {}, "stock_list": {}}

# ------------------------------------------------------------------------------
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS CSS CORREGIDOS
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
        font-family: 'DM Sans', sans-serif !important;
        background-color: #F8FAFC !important;
        color: #0F172A !important;
    }

    /* Títulos principales */
    h1, h2, h3, h4, h5, h6 {
        font-family: 'DM Sans', sans-serif !important;
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
    [data-baseweb="tab-highlight"] {
        background-color: #1dbe83 !important;
    }

    /* --- BARRA LATERAL (SIDEBAR) --- */
    [data-testid="stSidebar"] {
        background-color: #0F172A !important;
    }
    
    /* Aplicar fuente solo a textos reales, NO a los iconos */
    [data-testid="stSidebar"] p, 
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] .stCaption {
        font-family: 'DM Sans', sans-serif !important;
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

    /* Tarjetas KPI */
    .kpi-card {
        background-color: #FFFFFF;
        padding: 18px;
        border-radius: 14px;
        border: 1px solid #E2E8F0;
        box-shadow: 0px 4px 12px rgba(15, 23, 42, 0.03);
        text-align: center;
    }
    .kpi-title { font-size: 12px; color: #64748B; font-weight: 700; text-transform: uppercase; }
    .kpi-value { font-size: 26px; color: #0F172A; font-weight: 800; }
    .kpi-sub { font-size: 13px; color: #1dbe83; font-weight: 700; margin-top: 2px; }
    
    .leader-card {
        background-color: #FFFFFF;
        padding: 12px 16px;
        border-radius: 12px;
        margin-bottom: 10px;
        border: 1px solid #E2E8F0;
        border-left: 5px solid #1dbe83;
    }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 2. GESTIÓN PERSISTENTE DE TICKERS EN DISCO (JSON) Y CANDADO ANTI-DUPLICADOS
# ------------------------------------------------------------------------------
import json
import os

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

# ------------------------------------------------------------------------------
# 3. FUNCIONES DE CARGA DE DATOS CON CACHÉ DINÁMICO
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# CARGA ROBUSTA DE ETFS (CON EXTRACCIÓN DIRECTA Y NORMALIZACIÓN)
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def obtener_metrica_etf_individual(symbol):
    try:
        etf = yf.Ticker(symbol)
        
        # 1. Intentar leer info en vivo
        try:
            info = etf.info or {}
        except Exception:
            info = {}

        # 2. Respaldo base desde metadata_cache.json
        # (Asegúrate de que la llave "etf_list" coincida con tu JSON, o cámbiala por "etfs")
        fallback = CACHE_GLOBAL.get("etf_list", {}).get(symbol.upper(), {
            'Nombre': symbol,
            'Category': 'General',
            'Expense_Ratio_%': 0.0,
            'AUM_BUSD': 0.0
        })

        # 3. Extracción de Nombre (si info en vivo no lo tiene, usa fallback)
        nombre = info.get('shortName') or info.get('longName') or fallback['Nombre']

        # 4. Extracción de Categoría (si info en vivo falla, usa fallback)
        categoria = (
            info.get('category') or 
            info.get('legalType') or 
            info.get('quoteType') or 
            info.get('fundFamily')
        )
        if not categoria or categoria in ['General', 'Sin Categoría']:
            categoria = fallback['Category']

        # 5. Extracción de Expense Ratio (si info falla o es nulo, usa fallback)
        exp_raw = info.get('netExpenseRatio') or info.get('annualReportExpenseRatio') or info.get('expenseRatio')
        if exp_raw is not None and float(exp_raw) > 0:
            exp_float = float(exp_raw)
            exp_ratio = round(exp_float * 100, 3) if exp_float < 0.005 else round(exp_float, 3)
        else:
            exp_ratio = fallback['Expense_Ratio_%']

        # 6. Extracción de AUM (si info falla, usa fallback)
        aum_raw = info.get('totalAssets')
        if aum_raw and float(aum_raw) > 0:
            aum_busd = round(float(aum_raw) / 1e9, 2)
        else:
            aum_busd = fallback['AUM_BUSD']

        # 7. 52-Week Change (esta no suele estar en el fallback, así que si falla es 0.0)
        raw_52w = info.get('52WeekChange')
        change_52w = round(float(raw_52w) * 100, 2) if raw_52w is not None else 0.0

        # Ahora sí, armamos el diccionario fund usando las variables validadas
        fund = {
            'Nombre': nombre,
            'Category': categoria,
            'Expense_Ratio_%': exp_ratio,
            'AUM_BUSD': aum_busd,
            '52W_Change_%': change_52w
        }

        # Rendimiento histórico (5 años)
        try:
            perf = sr.calculate_etf_performance(symbol, period="5y") if hasattr(sr, 'calculate_etf_performance') else {}
        except:
            perf = {}

        reg = {'Ticker': symbol}
        reg.update(fund)
        reg.update(perf)
        return reg
    except Exception:
        return None


def cargar_datos_etfs(universo_tuple):
    """Consolida el DataFrame de ETFs y garantiza la existencia de todas las columnas."""
    resultados = []
    for symbol in universo_tuple:
        datos_etf = obtener_metrica_etf_individual(symbol)
        if datos_etf:
            resultados.append(datos_etf)
            
    if not resultados:
        return pd.DataFrame()
        
    df = pd.DataFrame(resultados)
    
    # --- GARANTÍA DE CATEGORÍA ---
    col_cat = next((c for c in ['Category', 'Categoria', 'category', 'Sector'] if c in df.columns), None)
    df['Category'] = df[col_cat].fillna('General') if col_cat else 'General'

    # --- GARANTÍA DE EXPENSE RATIO ---
    col_exp = next((c for c in ['Expense_Ratio_%', 'Expense_Ratio', 'expenseRatio', 'netExpenseRatio'] if c in df.columns), None)
    if col_exp and col_exp != 'Expense_Ratio_%':
        df['Expense_Ratio_%'] = pd.to_numeric(df[col_exp], errors='coerce').fillna(0.0)
    elif 'Expense_Ratio_%' not in df.columns:
        df['Expense_Ratio_%'] = 0.0
    else:
        df['Expense_Ratio_%'] = pd.to_numeric(df['Expense_Ratio_%'], errors='coerce').fillna(0.0)

    # 1. Percentil Expense Ratio (Menor comisión es mejor -> Rango inverso)
    df['Pctl_Exp_Ratio_Inv'] = (1 - df['Expense_Ratio_%'].rank(pct=True, ascending=True)) * 100

    # 2. Percentiles de Rendimiento y Riesgo
    df['Pctl_Sortino'] = df['Sortino'].rank(pct=True, ascending=True) * 100 if 'Sortino' in df.columns else 50.0
    df['Pctl_CAGR'] = df['CAGR_%'].rank(pct=True, ascending=True) * 100 if 'CAGR_%' in df.columns else 50.0

    # 3. Score Ponderado
    df['Score_Final'] = (
        (0.40 * df['Pctl_Sortino']) +
        (0.40 * df['Pctl_CAGR']) +
        (0.20 * df['Pctl_Exp_Ratio_Inv'])
    ).round(1)
    
    return df.sort_values(by='Score_Final', ascending=False)

# ------------------------------------------------------------------------------
# CARGA INDIVIDUAL DE ACCIONES (BLINDADA CON CACHÉ Y FALLBACK)
# ------------------------------------------------------------------------------

@st.cache_data(ttl=3600)
def obtener_metrica_individual(symbol):
    try:
        stock = yf.Ticker(symbol)
        
        # 1. Intentar leer info en vivo
        try:
            info = stock.info or {}
        except Exception:
            info = {}

        # 2. Respaldo base desde metadata_cache.json
        # (Asegúrate de que la llave coincida con la que usaste en tu JSON: "stocks" o "stock_list")
        fallback = CACHE_GLOBAL.get("stock_list", {}).get(symbol.upper(), {
            'Empresa': symbol,
            'Sector': 'General'
        })

        # 3. Extracción de Nombre (si info en vivo falla, usa fallback)
        empresa = info.get('shortName') or info.get('longName') or fallback.get('Empresa', symbol)

        # 4. Extracción de Sector (si info en vivo falla o viene vacío, usa fallback)
        sector = info.get('sector') or info.get('industry')
        if not sector or sector in ['General', 'Sin Sector']:
            sector = fallback.get('Sector', 'General')

        # 5. 52-Week Change (%)
        try:
            raw_52w = info.get('52WeekChange')
            change_52w = round(float(raw_52w) * 100, 2) if raw_52w is not None else 0.0
        except Exception:
            change_52w = 0.0

        # 6. Extracción de Estados Financieros para CAGRs
        try:
            bs = stock.balance_sheet
            cf = stock.cashflow
            fin = stock.financials
        except Exception:
            bs, cf, fin = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        
        # CAGR Stockholders' Equity
        try:
            clave_eq = next((k for k in ['Stockholders Equity', 'Total Equity Gross Minority Interest', 'Common Stock Equity'] if k in bs.index), None)
            cagr_equity = sr.calcular_cagr_serie(bs.loc[clave_eq]) if clave_eq is not None else 0.0
        except Exception:
            cagr_equity = 0.0

        # CAGR Free Cash Flow
        try:
            clave_fcf = next((k for k in ['Free Cash Flow', 'FreeCashFlow'] if k in cf.index), None)
            cagr_fcf = sr.calcular_cagr_serie(cf.loc[clave_fcf]) if clave_fcf is not None else 0.0
        except Exception:
            cagr_fcf = 0.0

        # CAGR EBITDA
        try:
            clave_ebitda = next((k for k in ['Normalized EBITDA', 'EBITDA'] if k in fin.index), None)
            cagr_ebitda = sr.calcular_cagr_serie(fin.loc[clave_ebitda]) if clave_ebitda is not None else 0.0
        except Exception:
            cagr_ebitda = 0.0

        # 7. Fundamentales base (ROIC, Margen Neto, etc.) y Performance
        try:
            fund = sr.get_stock_fundamentals(stock) if hasattr(sr, 'get_stock_fundamentals') else {}
        except Exception:
            fund = {}
            
        try:
            perf = sr.calculate_stock_performance(symbol, period="5y") if hasattr(sr, 'calculate_stock_performance') else {}
        except Exception:
            perf = {}
        
        # 8. Consolidación de todos los datos en un solo registro
        reg = {
            'Ticker': symbol,
            'Empresa': empresa,
            'Sector': sector,
            '52W_Change_%': change_52w,
            'CAGR_Equity_%': cagr_equity,
            'CAGR_FCF_%': cagr_fcf,
            'CAGR_EBITDA_%': cagr_ebitda
        }
        
        # Actualizamos el registro sobrescribiendo de ser necesario, pero asegurando que 
        # Empresa y Sector no queden vacíos si la librería 'sr' no los obtuvo bien.
        if 'Empresa' in fund:
            del fund['Empresa']
        if 'Sector' in fund:
            del fund['Sector']

        reg.update(fund)
        reg.update(perf)
        return reg

    except Exception:
        # En caso de fallo crítico, retorna un registro mínimo para que la aplicación no colapse
        return {'Ticker': symbol, 'Score_Final': 0, 'Sector': 'General', 'Empresa': symbol}

# 2. Orquestador: Itera la lista recuperando del caché instantáneo lo existente
def cargar_datos_acciones(universo_tuple):
    resultados = []
    for symbol in universo_tuple:
        datos_accion = obtener_metrica_individual(symbol)
        if datos_accion:
            resultados.append(datos_accion)
            
    if not resultados:
        return pd.DataFrame()
        
    df = pd.DataFrame(resultados)
    
    # Asegurar tamaño positivo para Plotly
    df['EBITDA_Size'] = df['EBITDA_MUSD'].apply(lambda x: max(x, 0.1))
    
    # Percentiles y Score
    df['Pctl_ROIC'] = df['ROIC_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Sortino'] = df['Sortino'].rank(pct=True, ascending=True) * 100
    df['Pctl_CAGR'] = df['CAGR_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Margin'] = df['Net_Margin_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_ROE'] = df['ROE_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Debt_Inv'] = (1 - df['Debt_to_Equity'].rank(pct=True, ascending=True)) * 100
    df['Pctl_ROA'] = df['ROA_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_EBITDA'] = df['EBITDA_MUSD'].rank(pct=True, ascending=True) * 100
    
    df['Score_Final'] = (
        (0.20 * df['Pctl_ROIC']) +
        (0.20 * df['Pctl_Sortino']) +
        (0.15 * df['Pctl_CAGR']) +
        (0.15 * df['Pctl_Margin']) +
        (0.10 * df['Pctl_ROE']) +
        (0.10 * df['Pctl_Debt_Inv']) +
        (0.05 * df['Pctl_ROA']) +
        (0.05 * df['Pctl_EBITDA'])
    ).round(1)
    
    return df.sort_values(by='Score_Final', ascending=False)

@st.cache_data(ttl=3600)
def generar_grafico_tendencia_6m(tickers_lista, titulo_grafico):
    if not tickers_lista:
        return None
        
    # Descargar precios de cierre de 6 meses
    datos = yf.download(tickers_lista, period="6mo", progress=False)
    if datos.empty:
        return None
        
    precios = datos['Adj Close'] if 'Adj Close' in datos else datos['Close']
    if isinstance(precios, pd.Series):
        precios = precios.to_frame(name=tickers_lista[0])
        
    precios = precios.dropna(axis=1, how='all')
    if precios.empty:
        return None
        
    # Normalizar a retorno porcentual (%) desde el día 1
    retornos_pct = ((precios / precios.iloc[0]) - 1) * 100

    fig = px.line(
        retornos_pct, 
        x=retornos_pct.index, 
        y=retornos_pct.columns,
        title=titulo_grafico,
        labels={'value': 'Rendimiento Acumulado (%)', 'Date': 'Fecha', 'variable': 'Activo'}
    )
    
    fig.update_layout(
        font=dict(family="DM Sans, sans-serif", color="#334155", size=12),
        title_font=dict(color="#0F172A", size=15),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        xaxis=dict(gridcolor="#E2E8F0", linecolor="#CBD5E1", tickfont=dict(color="#334155")),
        yaxis=dict(gridcolor="#E2E8F0", linecolor="#CBD5E1", tickfont=dict(color="#334155"), zeroline=True, zerolinecolor="#94A3B8"),
        legend=dict(font=dict(color="#334155"), title_font=dict(color="#0F172A"))
    )
    return fig

@st.cache_data(ttl=3600)
def calcular_matriz_correlacion(tickers_list):
    if not tickers_list or len(tickers_list) < 2:
        return pd.DataFrame()
    data = yf.download(tickers_list, period="1y", progress=False, auto_adjust=True)['Close']
    returns = data.pct_change().dropna()
    return returns.corr().round(2)

# Carga de data usando las listas del session_state
df_etfs = cargar_datos_etfs(tuple(st.session_state.etf_list))
df_stocks = cargar_datos_acciones(tuple(st.session_state.stock_list))

# ------------------------------------------------------------------------------
# 4. BARRA LATERAL (CONTROL DE PORTAFOLIO Y FILTROS)
# ------------------------------------------------------------------------------
st.sidebar.header("Menu")
st.sidebar.caption("Control de Portafolio")
st.sidebar.write("---")

with st.sidebar.expander("⚙️ Gestor de Activos", expanded=True):
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

# --- FILTROS DE ANÁLISIS RESTAURADOS ---
st.sidebar.markdown("<hr style='margin: 15px 0px; border-color: #334155;'>", unsafe_allow_html=True)
st.sidebar.caption("Filtros de Análisis")

if not df_etfs.empty and 'Category' in df_etfs.columns:
    categorias_validas = [str(c) for c in df_etfs['Category'].dropna().unique() if str(c).strip()]
    if categorias_validas:
        categorias_opt = ["Todas"] + sorted(categorias_validas)
        categoria_sel = st.sidebar.selectbox("Sector / Categoría (ETFs):", categorias_opt)
        if categoria_sel != "Todas":
            df_etfs = df_etfs[df_etfs['Category'] == categoria_sel] 

if not df_stocks.empty:
    sectores_opt = ["Todos"] + sorted(list(df_stocks['Sector'].unique()))
    sector_sel = st.sidebar.selectbox("Sector (Acciones):", sectores_opt)
    if sector_sel != "Todos":
        df_stocks = df_stocks[df_stocks['Sector'] == sector_sel]
        
def aplicar_estilo_grafico(fig):
    """Aplica contraste alto y tipografía uniforme a cualquier gráfico Plotly."""
    fig.update_layout(
        font=dict(family="DM Sans, sans-serif", color="#334155", size=12),
        title_font=dict(family="DM Sans, sans-serif", color="#0F172A", size=16),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        xaxis=dict(
            title_font=dict(color="#0F172A", size=13),
            tickfont=dict(color="#06152B", size=11),
            gridcolor="#E2E8F0",
            linecolor="#CBD5E1"
        ),
        yaxis=dict(
            title_font=dict(color="#0F172A", size=13),
            tickfont=dict(color="#06152B", size=11),
            gridcolor="#E2E8F0",
            linecolor="#CBD5E1"
        ),
        legend=dict(
            font=dict(color="#334155", size=11),
            title_font=dict(color="#0F172A", size=12)
        )
    )
    # Oscurece los textos impresos junto a cada punto/burbuja (ej. Ticker)
    fig.update_traces(
        textposition="top center",
        textfont=dict(family="DM Sans, sans-serif", color="#0F172A", size=11)
    )
    return fig

# ------------------------------------------------------------------------------
# 5. ESTRUCTURA CON PESTAÑAS (ETFs Y ACCIONES)
# ------------------------------------------------------------------------------
st.title("Finance Quantitative Dashboard")

tab_etf, tab_stock = st.tabs(["📊 Análisis de ETFs", "🏢 Acciones Individuales"])

# ==============================================================================
# PESTAÑA 1: ETFs
# ==============================================================================
with tab_etf:
    st.caption("Evaluación de ETFs por comisiones, masa crítica de capital y ratio de Sortino.")
    if df_etfs.empty:
        st.warning("No hay ETFs en el listado activo. Agrega al menos uno desde el gestor lateral.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        top_e = df_etfs.iloc[0]
        best_s = df_etfs.sort_values(by='Sortino', ascending=False).iloc[0]
        min_t = df_etfs.sort_values(by='Expense_Ratio_%', ascending=True).iloc[0]
        
        col1.markdown(f'<div class="kpi-card"><div class="kpi-title">Top ETF</div><div class="kpi-value">{top_e["Ticker"]}</div><div class="kpi-sub">Score: {top_e["Score_Final"]}</div></div>', unsafe_allow_html=True)
        col2.markdown(f'<div class="kpi-card"><div class="kpi-title">Mayor Sortino</div><div class="kpi-value">{best_s["Ticker"]}</div><div class="kpi-sub">Ratio: {best_s["Sortino"]}</div></div>', unsafe_allow_html=True)
        col3.markdown(f'<div class="kpi-card"><div class="kpi-title">Menor TER</div><div class="kpi-value">{min_t["Expense_Ratio_%"]}%</div><div class="kpi-sub">{min_t["Ticker"]}</div></div>', unsafe_allow_html=True)
        col4.markdown(f'<div class="kpi-card"><div class="kpi-title">ETFs Analizados</div><div class="kpi-value">{len(df_etfs)}</div><div class="kpi-sub">Universo Activo</div></div>', unsafe_allow_html=True)
        
        st.write("")
        c_left, c_right = st.columns([2.2, 1])
        
        with c_left:
            st.subheader("Relación Riesgo vs. Retorno (5 Años)")
            fig = px.scatter(df_etfs, x='Volatilidad_%', y='CAGR_%', size='AUM_BUSD', color='Score_Final', hover_name='Ticker', text='Ticker', color_continuous_scale=['#EF4444', '#F59E0B', '#1dbe83'])
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='#FFFFFF', font=dict(family="DM Sans", color="#0F172A"), height=360)
            st.plotly_chart(fig, width='stretch')
            
            st.subheader("Tabla General de ETFs")
            # 1. Definimos las columnas que NOS GUSTARÍA mostrar (incluyendo 'Nombre' como respaldo)
            cols_deseadas_etf = ['Ticker', 'Nombre', 'Category', 'Score_Final', 'Expense_Ratio_%', 'AUM_BUSD', 'Sortino', 'CAGR_%']
            cols_etf_final = [col for col in cols_deseadas_etf if col in df_etfs.columns]
            
            # 1. Gráfica de tendencia 6 meses de ETFs
            tickers_sector_etfs = df_etfs['Ticker'].tolist()
            if tickers_sector_etfs:
                fig_6m_etfs = generar_grafico_tendencia_6m(
                    tickers_sector_etfs, 
                    f"Tendencia Relativa (Últimos 6 Meses) - Categoría: {categoria_sel if 'categoria_sel' in locals() else 'Portafolio'}"
                )
                if fig_6m_etfs:
                    st.plotly_chart(fig_6m_etfs, use_container_width=True)

            # 2. Tabla final de ETFs actualizada
            cols_deseadas_etf = ['Ticker', 'Nombre', 'Category', 'Score_Final', 'Expense_Ratio_%', 'AUM_BUSD', 'Sortino', 'CAGR_%']
            cols_etf_final = [col for col in cols_deseadas_etf if col in df_etfs.columns]

            st.dataframe(
                df_etfs[cols_etf_final].style
                .format({
                    'Score_Final': '{:.1f}',
                    'Expense_Ratio_%': '{:.2f}%',
                    'Sortino': '{:.2f}',
                    'CAGR_%': '{:.2f}%',
                    'AUM_BUSD': '${:,.2f}B'
                })
                .highlight_max(axis=0, subset=['Score_Final'], color='#D1FAE5'), 
                use_container_width=True, 
                height=280
            )
            
        with c_right:
            st.subheader("Líderes por Sector")
            for _, r in df_etfs.groupby('Category').head(1).head(5).iterrows():
                st.markdown(f'<div class="leader-card"><b>{r["Ticker"]}</b> | Score: <b style="color:#1dbe83;">{r["Score_Final"]}</b><br><small>{r["Category"]} | TER: {r["Expense_Ratio_%"]}%</small></div>', unsafe_allow_html=True)

# ==============================================================================
# PESTAÑA 2: ACCIONES INDIVIDUALES
# ==============================================================================
with tab_stock:
    st.caption("Evaluación fundamental por ROIC (20%), Sortino (20%), CAGR (15%), Margen Neto (15%), ROE (10%), Deuda/Equity (10%), ROA (5%) y EBITDA (5%).")
    if df_stocks.empty:
        st.warning("No hay acciones en el listado activo. Agrega al menos una desde el gestor lateral.")
    else:
        s1, s2, s3, s4 = st.columns(4)
        top_stk = df_stocks.iloc[0]
        best_roic = df_stocks.sort_values(by='ROIC_%', ascending=False).iloc[0]
        min_debt = df_stocks.sort_values(by='Debt_to_Equity', ascending=True).iloc[0]
        
        s1.markdown(f'<div class="kpi-card"><div class="kpi-title">Top Acción</div><div class="kpi-value">{top_stk["Ticker"]}</div><div class="kpi-sub">Score: {top_stk["Score_Final"]}</div></div>', unsafe_allow_html=True)
        s2.markdown(f'<div class="kpi-card"><div class="kpi-title">Mayor ROIC</div><div class="kpi-value">{best_roic["Ticker"]}</div><div class="kpi-sub">{best_roic["ROIC_%"]}%</div></div>', unsafe_allow_html=True)
        s3.markdown(f'<div class="kpi-card"><div class="kpi-title">Menor Deuda/Equity</div><div class="kpi-value">{min_debt["Ticker"]}</div><div class="kpi-sub">D/E: {min_debt["Debt_to_Equity"]}</div></div>', unsafe_allow_html=True)
        s4.markdown(f'<div class="kpi-card"><div class="kpi-title">Acciones Analizadas</div><div class="kpi-value">{len(df_stocks)}</div><div class="kpi-sub">Empresas</div></div>', unsafe_allow_html=True)
        
        st.write("")
        sc_left, sc_right = st.columns([2.2, 1])
        
        with sc_left:
            st.subheader("Calidad de Capital: ROIC (%) vs. Sortino Ratio")
            fig_stk = px.scatter(
                df_stocks, 
                x='Sortino', 
                y='ROIC_%', 
                size='EBITDA_Size',  # Usamos la columna limpia sin negativos
                color='Score_Final',
                hover_name='Ticker', 
                hover_data={'EBITDA_Size': False, 'EBITDA_MUSD': True}, # Muestra el EBITDA real en el hover
                text='Ticker',
                color_continuous_scale=['#EF4444', '#F59E0B', '#1dbe83'],
                labels={'Sortino': 'Ratio Sortino (Riesgo)', 'ROIC_%': 'ROIC (%)', 'EBITDA_MUSD': 'EBITDA (MUSD)'}
            )
            fig_stk.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='#FFFFFF', font=dict(family="DM Sans", color="#0F172A"), height=360)
            st.plotly_chart(fig_stk, width='stretch')
            
            st.subheader("Matriz de Correlación entre Acciones (1 Año)")
            corr_stks = df_stocks['Ticker'].tolist()[:8]
            df_c = calcular_matriz_correlacion(corr_stks)
            if not df_c.empty:
                fig_c = px.imshow(df_c, text_auto=True, aspect="auto", color_continuous_scale=['#FFFFFF', '#A7F3D0', '#1dbe83'])
                fig_c.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='#FFFFFF', font=dict(family="DM Sans", color="#0F172A"), height=320)
                st.plotly_chart(fig_c, width='stretch')
            
            # 1. Gráfica de tendencia 6 meses filtrada por el sector seleccionado
            tickers_sector_stocks = df_stocks['Ticker'].tolist()
            if tickers_sector_stocks:
                fig_6m_stocks = generar_grafico_tendencia_6m(
                    tickers_sector_stocks, 
                    f"Tendencia de Precios (Últimos 6 Meses) - Sector: {sector_sel if 'sector_sel' in locals() else 'Portafolio'}"
                )
                if fig_6m_stocks:
                    st.plotly_chart(fig_6m_stocks, use_container_width=True)

            # 2. Tabla final con las nuevas métricas fundamentales
            cols_deseadas_stocks = [
                'Ticker', 'Empresa', 'Sector', 'Score_Final', '52W_Change_%', 
                'CAGR_%', 'CAGR_Equity_%', 'CAGR_FCF_%', 'CAGR_EBITDA_%', 
                'ROIC_%', 'Sortino', 'Net_Margin_%', 'Debt_to_Equity'
            ]
            cols_stocks_final = [c for c in cols_deseadas_stocks if c in df_stocks.columns]
            
            st.dataframe(
                df_stocks[cols_stocks_final].style
                .format({
                    'Score_Final': '{:.1f}',
                    '52W_Change_%': '{:+.2f}%',
                    'CAGR_%': '{:.2f}%',
                    'CAGR_Equity_%': '{:.2f}%',
                    'CAGR_FCF_%': '{:.2f}%',
                    'CAGR_EBITDA_%': '{:.2f}%',
                    'ROIC_%': '{:.2f}%',
                    'Sortino': '{:.2f}',
                    'Net_Margin_%': '{:.2f}%',
                    'Debt_to_Equity': '{:.2f}'
                })
                .highlight_max(axis=0, subset=['Score_Final', 'ROIC_%', 'CAGR_%'], color='#D1FAE5'),
                use_container_width=True,
                height=320
            )

        with sc_right:
            st.subheader("Líderes por Sector GICS")
            for _, r in df_stocks.groupby('Sector').head(1).iterrows():
                st.markdown(f'<div class="leader-card"><b>{r["Ticker"]}</b> ({r["Empresa"]})<br>Score: <b style="color:#1dbe83;">{r["Score_Final"]}</b> | ROIC: <b>{r["ROIC_%"]}%</b><br><small>Sector: {r["Sector"]}</small></div>', unsafe_allow_html=True)