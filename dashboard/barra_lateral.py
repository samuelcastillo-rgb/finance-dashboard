"""Barra lateral: gestor de tickers, botón de actualizar y filtros de análisis."""
from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from dashboard.config import TICKERS_DEFECTO
from finanzas import almacenamiento


@dataclass
class Filtros:
    top_n: int
    score_minimo: int
    categoria_sel: str
    sector_sel: str


def cargar_tickers():
    return almacenamiento.cargar_tickers(TICKERS_DEFECTO)


def guardar_tickers_disco():
    almacenamiento.guardar_tickers({
        'etf_list': st.session_state.etf_list,
        'stock_list': st.session_state.stock_list
    })


def inicializar_estado():
    """Carga la lista de tickers en session_state (una vez por sesión) quitando duplicados."""
    # Cargar tickers y ELIMINAR DUPLICADOS automáticamente
    if 'etf_list' not in st.session_state or 'stock_list' not in st.session_state:
        tickers_guardados = cargar_tickers()

        # Candado 1: Limpieza de duplicados al iniciar (dict.fromkeys borra repetidos y mantiene el orden)
        lista_etf_limpia = list(dict.fromkeys(tickers_guardados.get('etf_list', TICKERS_DEFECTO['etf_list'])))
        lista_stock_limpia = list(dict.fromkeys(tickers_guardados.get('stock_list', TICKERS_DEFECTO['stock_list'])))

        st.session_state.etf_list = lista_etf_limpia
        st.session_state.stock_list = lista_stock_limpia

        # Si se encontraron y borraron duplicados desde el JSON, forzamos un guardado del archivo limpio
        if (len(lista_etf_limpia) < len(tickers_guardados.get('etf_list', []))
                or len(lista_stock_limpia) < len(tickers_guardados.get('stock_list', []))):
            guardar_tickers_disco()

    if 'ultima_actualizacion' not in st.session_state:
        st.session_state.ultima_actualizacion = datetime.now()


def mostrar(df_etfs, df_stocks):
    """Dibuja la barra lateral y devuelve (df_etfs, df_stocks, filtros) ya filtrados."""
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
    st.sidebar.markdown("<hr class='separador-lateral'>", unsafe_allow_html=True)
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

    return df_etfs, df_stocks, Filtros(top_n, score_minimo, categoria_sel, sector_sel)
