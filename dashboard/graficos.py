"""Figuras de Plotly. Ninguna fija colores de fondo o texto: los pone el tema activo."""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from dashboard.config import COLORES_COMPONENTES, ESCALA_CORR, ESCALA_SCORE, FUENTE_GRAFICOS, PALETA
from finanzas.score import peso_disponible


def aplicar_estilo_grafico(fig, altura=None, leyenda_abajo=False):
    """Tipografía y márgenes uniformes para cualquier gráfico Plotly.

    Los colores de fondo, texto y cuadrícula no se fijan aquí: st.plotly_chart les aplica
    los del tema activo (claro u oscuro), y cambian solos al cambiar de modo."""
    hay_titulo = bool(fig.layout.title.text)
    fig.update_layout(
        font=dict(family=FUENTE_GRAFICOS, size=12),
        title_font=dict(family=FUENTE_GRAFICOS, size=15),
        margin=dict(l=10, r=10, t=50 if hay_titulo else 20, b=10),
        hoverlabel=dict(font_family=FUENTE_GRAFICOS),
        legend=dict(font=dict(size=11), title_font=dict(size=12)),
    )
    fig.update_xaxes(title_font=dict(size=13), tickfont=dict(size=11))
    fig.update_yaxes(title_font=dict(size=13), tickfont=dict(size=11))
    if altura:
        fig.update_layout(height=altura)
    if leyenda_abajo:
        fig.update_layout(legend=dict(orientation='h', yanchor='top', y=-0.18, x=0))
    return fig


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
                                   tickfont=dict(size=10)),
                   angularaxis=dict(tickfont=dict(size=11))),
        showlegend=True, legend=dict(orientation='h', yanchor='top', y=-0.08, x=0),
        font=dict(family=FUENTE_GRAFICOS), margin=dict(l=40, r=40, t=20, b=30), height=340)
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
                      textfont=dict(family=FUENTE_GRAFICOS, size=11),
                      marker=dict(opacity=0.85, line=dict(width=1, color='rgba(255,255,255,0.6)')))
    fig.update_coloraxes(colorbar=dict(title='Score', thickness=12))
    return aplicar_estilo_grafico(fig, altura=400)


def grafico_correlacion(precios, tickers):
    matriz = calcular_matriz_correlacion(precios, tickers)
    if matriz.empty:
        return None
    fig = px.imshow(matriz, text_auto=True, aspect="auto", zmin=-1, zmax=1,
                    color_continuous_scale=ESCALA_CORR)
    fig.update_coloraxes(colorbar=dict(title='ρ', thickness=12))
    return aplicar_estilo_grafico(fig, altura=420)


def grafico_pesos(resumen):
    datos = resumen[resumen['Valor_USD'] > 0]
    fig = px.pie(datos, names='Ticker', values='Valor_USD', hole=0.55,
                 color_discrete_sequence=COLORES_COMPONENTES)
    fig.update_traces(textposition='inside', textinfo='label+percent', sort=False,
                      hovertemplate='%{label}<br>$%{value:,.2f}<br>%{percent}<extra></extra>')
    fig.update_layout(showlegend=False)
    return aplicar_estilo_grafico(fig, altura=340)


def grafico_ganancia_por_ticker(resumen):
    datos = resumen.dropna(subset=['Ganancia_USD']).sort_values('Ganancia_USD')
    colores = [PALETA['primario'] if v >= 0 else PALETA['riesgo'] for v in datos['Ganancia_USD']]
    fig = go.Figure(go.Bar(
        x=datos['Ganancia_USD'], y=datos['Ticker'], orientation='h', marker_color=colores,
        customdata=datos['Ganancia_%'],
        hovertemplate='%{y}<br>%{x:+,.2f} USD<br>%{customdata:+.2f}%<extra></extra>'))
    fig.update_layout(xaxis_title='Ganancia / pérdida (USD)', yaxis_title=None)
    return aplicar_estilo_grafico(fig, altura=max(240, 34 * len(datos) + 90))


def grafico_frontera(resultado, elegida, nombres=None):
    """Frontera eficiente (línea), cada activo (puntos), las carteras de mínima volatilidad y
    máximo Sharpe, la línea del mercado de capitales y la cartera `elegida` resaltada.
    `resultado` es lo que guarda el optimizador en Rust (finanzas/frontera.py)."""
    nombres = nombres or {}
    pct = 100
    activos = pd.DataFrame(resultado['activos'])
    frontera = pd.DataFrame(resultado['frontera'])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=activos['volatilidad'] * pct, y=activos['rendimiento'] * pct, mode='markers', name='Cada activo',
        marker=dict(size=7, color=PALETA['suave'], opacity=0.55),
        customdata=[nombres.get(t, '') for t in activos['ticker']], text=activos['ticker'],
        hovertemplate='<b>%{text}</b> %{customdata}<br>Volatilidad %{x:.1f}%<br>Rendimiento %{y:.1f}%<extra></extra>'))

    ms, mv = resultado['max_sharpe'], resultado['min_volatilidad']
    tasa = resultado['tasa_libre']
    # Línea del mercado de capitales: combinaciones de la tasa libre de riesgo con el máximo Sharpe.
    x_fin = frontera['volatilidad'].max() * 1.1 * pct
    fig.add_trace(go.Scatter(
        x=[0, x_fin], y=[tasa * pct, (tasa + ms['sharpe'] * x_fin / pct) * pct], mode='lines',
        name='Línea del mercado de capitales', line=dict(color=PALETA['suave'], dash='dot', width=1.5),
        hoverinfo='skip'))
    fig.add_trace(go.Scatter(
        x=frontera['volatilidad'] * pct, y=frontera['rendimiento'] * pct, mode='lines', name='Frontera eficiente',
        line=dict(color=PALETA['primario'], width=3), customdata=frontera['sharpe'],
        hovertemplate='Volatilidad %{x:.1f}%<br>Rendimiento %{y:.1f}%<br>Sharpe %{customdata:.2f}<extra></extra>'))
    for cartera, nombre, color, simbolo in ((mv, 'Mínima volatilidad', COLORES_COMPONENTES[2], 'diamond'),
                                            (ms, 'Máximo Sharpe', COLORES_COMPONENTES[0], 'star')):
        fig.add_trace(go.Scatter(
            x=[cartera['volatilidad'] * pct], y=[cartera['rendimiento'] * pct], mode='markers', name=nombre,
            marker=dict(size=17, symbol=simbolo, color=color, line=dict(width=1.5, color='rgba(255,255,255,0.8)')),
            hovertemplate=f'<b>{nombre}</b><br>Volatilidad %{{x:.1f}}%<br>Rendimiento %{{y:.1f}}%'
                          f'<br>Sharpe {cartera["sharpe"]:.2f}<extra></extra>'))
    if elegida is not ms and elegida is not mv:
        fig.add_trace(go.Scatter(
            x=[elegida['volatilidad'] * pct], y=[elegida['rendimiento'] * pct], mode='markers', name='Cartera elegida',
            marker=dict(size=15, symbol='circle-open', color=PALETA['primario'], line=dict(width=3)),
            hovertemplate='<b>Cartera elegida</b><br>Volatilidad %{x:.1f}%<br>Rendimiento %{y:.1f}%<extra></extra>'))
    fig.update_layout(xaxis_title='Volatilidad anual (%)', yaxis_title='Rendimiento anual esperado (%)',
                      hovermode='closest')
    fig.update_xaxes(rangemode='tozero')
    return aplicar_estilo_grafico(fig, altura=460, leyenda_abajo=True)


def grafico_pesos_cartera(pesos, nombres=None, maximo=15):
    """Barras horizontales con el peso de cada activo de una cartera ({ticker: peso}).
    Muestra los `maximo` mayores y suma el resto en una barra "Otros"."""
    nombres = dict(nombres or {})
    datos = pd.DataFrame({'Ticker': list(pesos), 'Peso': [p * 100 for p in pesos.values()]})
    datos = datos[datos['Peso'] >= 0.05].sort_values('Peso', ascending=False)
    if len(datos) > maximo:
        resto = datos.iloc[maximo:]
        etiqueta = f'Otros ({len(resto)})'
        nombres[etiqueta] = ', '.join(resto['Ticker'].head(12)) + ('…' if len(resto) > 12 else '')
        datos = pd.concat([datos.iloc[:maximo], pd.DataFrame({'Ticker': [etiqueta], 'Peso': [resto['Peso'].sum()]})])
    datos = datos.iloc[::-1]
    fig = go.Figure(go.Bar(
        x=datos['Peso'], y=datos['Ticker'], orientation='h',
        marker_color=[PALETA['suave'] if t.startswith('Otros (') else PALETA['primario'] for t in datos['Ticker']],
        text=[f'{p:.1f}%' for p in datos['Peso']], textposition='outside', cliponaxis=False,
        customdata=[nombres.get(t, '') for t in datos['Ticker']],
        hovertemplate='<b>%{y}</b> %{customdata}<br>%{x:.1f}% de la cartera<extra></extra>'))
    fig.update_layout(xaxis_title='Peso (%)', yaxis_title=None, showlegend=False)
    fig.update_xaxes(range=[0, max(datos['Peso'].max() * 1.18, 5)] if not datos.empty else None)
    return aplicar_estilo_grafico(fig, altura=max(220, 30 * len(datos) + 90))
