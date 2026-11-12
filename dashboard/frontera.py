"""Sub-pestaña "Portafolio óptimo": la frontera eficiente de Markowitz de los ETFs o de las
acciones. La calcula cada día el optimizador en Rust (optimizador/) dentro del proceso
diario; aquí solo se lee de la base y se dibuja."""
import pandas as pd
import streamlit as st

from dashboard.carga import cargar_frontera_guardada
from dashboard.graficos import grafico_frontera, grafico_pesos_cartera
from dashboard.tarjetas import mostrar_kpis, titulo_seccion
from finanzas import almacenamiento


def _pct(valor, decimales=1):
    return f"{valor * 100:.{decimales}f}%"


def mostrar_frontera(clave, nombre_plural, df):
    """`clave` = 'etf_list' o 'stock_list'; `df` (tabla de la pestaña) solo aporta nombres y score."""
    resultado, fecha = cargar_frontera_guardada(clave)
    if resultado is None:
        if almacenamiento.hay_base_de_datos():
            st.info("Todavía no hay una frontera eficiente calculada. Se calcula en el proceso diario "
                    "(GitHub Action «Actualizar datos diarios»); puedes correrlo a mano desde la pestaña Actions.")
        else:
            st.info("La frontera eficiente la calcula el proceso diario y se guarda en la base de datos; "
                    "sin base configurada no está disponible.")
        return

    nombres = {}
    columna = next((c for c in ('Nombre', 'Empresa') if df is not None and c in df.columns), None)
    if columna and 'Ticker' in df.columns:
        nombres = dict(zip(df['Ticker'], df[columna].fillna('').astype(str), strict=True))
    ms, mv = resultado['max_sharpe'], resultado['min_volatilidad']

    st.caption(
        f"Calculada el {fecha:%d/%m/%Y} con {len(resultado['activos'])} {nombre_plural} "
        f"({resultado['desde']} a {resultado['hasta']}, {resultado['n_dias']} días) · "
        f"peso máximo por activo {_pct(resultado['peso_maximo'], 0)} · "
        f"tasa libre de riesgo {_pct(resultado['tasa_libre'])} · optimizador en Rust")
    mostrar_kpis([
        ("Máximo Sharpe", f"{ms['sharpe']:.2f}",
         f"rend. {_pct(ms['rendimiento'])} · vol. {_pct(ms['volatilidad'])}"),
        ("Mínima volatilidad", _pct(mv['volatilidad']), f"rend. {_pct(mv['rendimiento'])} · Sharpe {mv['sharpe']:.2f}"),
        ("Activos en máx. Sharpe", str(len(ms['pesos'])), f"de {len(resultado['activos'])} {nombre_plural}"),
        ("Activos en mín. volatilidad", str(len(mv['pesos'])), f"de {len(resultado['activos'])} {nombre_plural}"),
    ])
    st.write("")

    frontera = resultado['frontera']
    opciones = ['Máximo Sharpe', 'Mínima volatilidad', 'Elegir en la frontera']
    izq, der = st.columns([1.7, 1])
    with der:
        with st.container(border=True):
            titulo_seccion("Composición", "Peso de cada activo en la cartera elegida")
            eleccion = st.segmented_control("Cartera", opciones, default=opciones[0], key=f'frontera_cartera_{clave}',
                                            label_visibility='collapsed') or opciones[0]
            if eleccion == opciones[0]:
                elegida = ms
            elif eleccion == opciones[1]:
                elegida = mv
            else:
                etiquetas = [f"vol. {_pct(c['volatilidad'])} · rend. {_pct(c['rendimiento'])}" for c in frontera]
                inicial = min(range(len(frontera)), key=lambda i: abs(frontera[i]['sharpe'] - ms['sharpe']))
                etiqueta = st.select_slider("Nivel de riesgo (de menor a mayor volatilidad)", etiquetas,
                                            value=etiquetas[inicial], key=f'frontera_punto_{clave}')
                elegida = frontera[etiquetas.index(etiqueta)]
            st.markdown(f"**Rendimiento esperado** {_pct(elegida['rendimiento'])} · "
                        f"**Volatilidad** {_pct(elegida['volatilidad'])} · **Sharpe** {elegida['sharpe']:.2f}")
            st.plotly_chart(grafico_pesos_cartera(elegida['pesos'], nombres), width='stretch',
                            key=f'frontera_pesos_{clave}')
    with izq:
        with st.container(border=True):
            titulo_seccion("Frontera eficiente",
                           "Cada punto de la línea verde es la cartera con menos volatilidad para ese rendimiento "
                           "esperado · los puntos grises son cada activo por separado")
            st.plotly_chart(grafico_frontera(resultado, elegida, nombres), width='stretch',
                            key=f'frontera_grafico_{clave}')

    with st.expander("Tabla de pesos y supuestos"):
        filas = [{'Ticker': t, 'Nombre': nombres.get(t, ''), 'Peso %': p * 100} for t, p in elegida['pesos'].items()]
        activos = {a['ticker']: a for a in resultado['activos']}
        tabla = pd.DataFrame(filas)
        if not tabla.empty:
            tabla['Rend. anual %'] = [activos[t]['rendimiento'] * 100 for t in tabla['Ticker']]
            tabla['Vol. anual %'] = [activos[t]['volatilidad'] * 100 for t in tabla['Ticker']]
            st.dataframe(tabla, hide_index=True, width='stretch', column_config={
                'Peso %': st.column_config.ProgressColumn('Peso %', min_value=0, max_value=100, format='%.1f%%'),
                'Rend. anual %': st.column_config.NumberColumn(format='%.1f%%'),
                'Vol. anual %': st.column_config.NumberColumn(format='%.1f%%')})
        st.markdown(
            "- **Rendimiento esperado:** promedio histórico de los últimos 3 años, anualizado. Es el supuesto "
            "más frágil: la cartera de máximo Sharpe favorece a lo que más subió en ese periodo.\n"
            "- **Riesgo:** covarianza histórica con contracción de Ledoit-Wolf "
            f"({resultado['contraccion']:.1%}), que la estabiliza cuando hay muchos activos.\n"
            f"- **Restricciones:** solo compras (sin cortos), pesos que suman 100 % y como máximo "
            f"{_pct(resultado['peso_maximo'], 0)} por activo.\n"
            "- No es una recomendación de inversión: no incluye comisiones, impuestos ni rebalanceos.")
        if resultado.get('excluidos'):
            st.caption("No incluidos: " + " · ".join(f"{t} ({m})" for t, m in resultado['excluidos'].items()))
