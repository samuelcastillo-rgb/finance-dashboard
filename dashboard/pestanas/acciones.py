"""Pestaña de acciones."""
import streamlit as st

from dashboard.config import COLUMNAS_EXPLORADOR_ACCIONES, NOTA_REESCALADO
from dashboard.explorador import explorador_metricas
from dashboard.formato import _f
from dashboard.frontera import mostrar_frontera
from dashboard.graficos import (
    generar_grafico_tendencia_6m,
    grafico_contribuciones,
    grafico_correlacion,
    grafico_dispersion,
    grafico_ranking,
)
from dashboard.tarjetas import (
    fila_extrema,
    marca_cobertura,
    mostrar_aviso_cobertura,
    mostrar_explicacion_score,
    mostrar_inspector,
    mostrar_kpis,
    mostrar_tabla,
    nota_omitidos,
    tarjeta_lider,
    titulo_seccion,
)
from finanzas.score import COMPONENTES_ACCIONES, nivel_score


def mostrar(df_stocks, n_stocks_universo, filtros, precios_cierre):
    top_n = filtros.top_n
    sector_sel = filtros.sector_sel
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

        s_res, s_score, s_mercado, s_explorar, s_optimo, s_datos = st.tabs(
            ["Resumen", "Desglose del score", "Mercado", "Explorador", "Portafolio óptimo", "Datos"])

        with s_res:
            izq, der = st.columns([2.2, 1])
            with izq:
                with st.container(border=True):
                    titulo_seccion("Ranking por score",
                                   f"Top {min(top_n, len(df_stocks))} acciones · color = nivel del score")
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
                    precios_cierre, tickers_top_stk,
                    f"Rendimiento acumulado, 6 meses · Top {len(tickers_top_stk)} por score"
                    + ("" if sector_sel == "Todos" else f" · {sector_sel}"))
                if fig_6m_stk:
                    st.plotly_chart(fig_6m_stk, width='stretch', key='trend_stk')
                else:
                    st.info("No se pudo descargar la tendencia de precios.")
            with st.container(border=True):
                titulo_seccion("Correlación entre acciones (1 año)",
                               "Valores cercanos a 1 indican que se mueven igual: poca diversificación entre ellas")
                fig_cs = grafico_correlacion(precios_cierre, df_stocks.head(min(top_n, 12))['Ticker'].tolist())
                if fig_cs:
                    st.plotly_chart(fig_cs, width='stretch', key='corr_stk')
                else:
                    st.info("Se necesitan al menos 2 acciones para calcular la correlación.")

        with s_explorar:
            with st.container(border=True):
                titulo_seccion("Explorador de métricas",
                               "Elige la gráfica y qué comparar en cada eje · respeta los filtros del menú lateral")
                explorador_metricas(df_stocks, COLUMNAS_EXPLORADOR_ACCIONES, nombre_col='Empresa', key='explorador_stk',
                                    inicial={'tipo': 'dispersion', 'x': 'Debt_to_Equity', 'y': 'ROIC_%',
                                             'color': 'Sector', 'tamano': 'EBITDA_MUSD'})

        with s_optimo:
            mostrar_frontera('stock_list', 'acciones', df_stocks)

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
