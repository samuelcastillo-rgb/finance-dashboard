# app.py
# Punto de entrada del Finance Quantitative Dashboard (streamlit run app.py).
# Solo arma la página: la lógica vive en finanzas/ y la presentación en dashboard/.

import streamlit as st

st.set_page_config(page_title="Finance Quantitative Dashboard", layout="wide", initial_sidebar_state="expanded")

from dashboard import barra_lateral  # noqa: E402  (después de set_page_config)
from dashboard.carga import (  # noqa: E402
    cargar_datos_acciones,
    cargar_datos_etfs,
    cargar_metricas_guardadas,
    descargar_precios_cierre,
)
from dashboard.estilos import aplicar_estilos  # noqa: E402
from dashboard.pestanas import acciones, etfs, portafolio  # noqa: E402
from dashboard.tarjetas import encabezado  # noqa: E402

aplicar_estilos()
barra_lateral.inicializar_estado()

# Una única descarga de precios para ETFs y acciones; info y estados financieros en paralelo.
universo_precios = tuple(dict.fromkeys(st.session_state.etf_list + st.session_state.stock_list))
precios_cierre = descargar_precios_cierre(universo_precios)
df_etfs = cargar_datos_etfs(tuple(st.session_state.etf_list), precios_cierre)
df_stocks = cargar_datos_acciones(tuple(st.session_state.stock_list), precios_cierre)
n_etfs_universo, n_stocks_universo = len(df_etfs), len(df_stocks)

# Los filtros se aplican después de calcular el score
df_etfs, df_stocks, filtros = barra_lateral.mostrar(df_etfs, df_stocks)

# Fecha de los datos: la del último proceso diario si se leyó de la base
fecha_proceso_diario = cargar_metricas_guardadas()[1]
if fecha_proceso_diario is not None:
    texto_actualizado = f"Datos al {fecha_proceso_diario:%d/%m/%Y %H:%M} UTC"
else:
    texto_actualizado = f"Actualizado {st.session_state.ultima_actualizacion:%d/%m/%Y %H:%M}"
encabezado(texto_actualizado)

tab_etf, tab_stock, tab_portafolio = st.tabs([f"📊 ETFs ({len(st.session_state.etf_list)})",
                                             f"🏢 Acciones ({len(st.session_state.stock_list)})",
                                             "💼 Mi portafolio"])
with tab_etf:
    etfs.mostrar(df_etfs, n_etfs_universo, filtros, precios_cierre)
with tab_stock:
    acciones.mostrar(df_stocks, n_stocks_universo, filtros, precios_cierre)
with tab_portafolio:
    portafolio.mostrar()
