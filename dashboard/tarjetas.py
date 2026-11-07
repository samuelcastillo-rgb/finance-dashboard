"""Piezas visuales reutilizables: títulos, KPIs, tarjetas, tablas, inspector y avisos."""
import html

import pandas as pd
import streamlit as st

from dashboard.formato import _color_variacion, _f, _mapear
from dashboard.graficos import grafico_radar
from finanzas.score import MIN_COBERTURA, nivel_score


def encabezado(texto_actualizado):
    st.markdown(
        '<div class="app-header"><div>'
        '<div class="app-title">Finance Quantitative Dashboard</div>'
        '<div class="app-subtitle">Score cuantitativo de ETFs y acciones individuales, '
        'calculado por percentiles dentro de tu universo</div></div>'
        f'<div class="app-stamp">{texto_actualizado}</div></div>',
        unsafe_allow_html=True)


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
