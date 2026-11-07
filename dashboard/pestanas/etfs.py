"""Pestaña de ETFs."""
import streamlit as st

from dashboard.config import COLUMNAS_EXPLORADOR_ETFS, NOTA_REESCALADO
from dashboard.explorador import explorador_metricas
from dashboard.formato import _f
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
from finanzas.score import COMPONENTES_ETFS, nivel_score


def mostrar(df_etfs, n_etfs_universo, filtros, precios_cierre):
    top_n = filtros.top_n
    categoria_sel = filtros.categoria_sel
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

        sub_res, sub_score, sub_mercado, sub_explorar, sub_datos = st.tabs(
            ["Resumen", "Desglose del score", "Mercado", "Explorador", "Datos"])

        with sub_res:
            izq, der = st.columns([2.2, 1])
            with izq:
                with st.container(border=True):
                    titulo_seccion("Ranking por score",
                                   f"Top {min(top_n, len(df_etfs))} ETFs · color = nivel del score")
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
                            r["Ticker"],
                            f'{r["Category"]} · TER {_f(r["Expense_Ratio_%"], 2, "%")}{marca_cobertura(r)}',
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
                fig_c = grafico_correlacion(precios_cierre, df_etfs.head(min(top_n, 12))['Ticker'].tolist())
                if fig_c:
                    st.plotly_chart(fig_c, width='stretch', key='corr_etf')
                else:
                    st.info("Se necesitan al menos 2 ETFs para calcular la correlación.")

        with sub_explorar:
            with st.container(border=True):
                titulo_seccion("Explorador de métricas",
                               "Elige la gráfica y qué comparar en cada eje · respeta los filtros del menú lateral")
                explorador_metricas(df_etfs, COLUMNAS_EXPLORADOR_ETFS, nombre_col='Nombre', key='explorador_etf',
                                    inicial={'tipo': 'dispersion', 'x': 'Volatilidad_%', 'y': 'CAGR_%',
                                             'color': 'Score_Final', 'tamano': 'AUM_BUSD'})

        with sub_datos:
            mostrar_tabla(
                df_etfs,
                ['Ticker', 'Nombre', 'Category', 'Score_Final', 'Cobertura_%', '52W_Change_%', 'Expense_Ratio_%',
                 'AUM_BUSD', 'Yield_%', 'Sortino', 'Sharpe', 'CAGR_%', 'Volatilidad_%', 'Max_Drawdown_%'],
                {'Score_Final': '{:.1f}', 'Cobertura_%': '{:.0f}%', '52W_Change_%': '{:+.2f}%',
                 'Expense_Ratio_%': '{:.2f}%', 'Yield_%': '{:.2f}%', 'Sortino': '{:.2f}', 'Sharpe': '{:.2f}',
                 'CAGR_%': '{:.2f}%',
                 'Volatilidad_%': '{:.2f}%', 'Max_Drawdown_%': '{:.1f}%', 'AUM_BUSD': '${:,.2f}B'},
                'etfs.csv')
