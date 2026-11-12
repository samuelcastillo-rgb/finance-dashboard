"""Pestaña "Comparar": hasta 3 tickers de la base (ETFs, acciones o una mezcla) lado a lado:
precio de 1 año, criterios del score y correlación entre ellos y con el S&P 500.

Los cálculos viven en finanzas/comparar.py; el score y sus criterios en finanzas/score.py."""
import pandas as pd
import streamlit as st

from dashboard.carga import descargar_precios_cierre
from dashboard.config import COLUMNAS_EXPLORADOR_ACCIONES, COLUMNAS_EXPLORADOR_ETFS
from dashboard.formato import _f
from dashboard.graficos import (
    COLORES_COMPARAR,
    grafico_comparar_precios,
    grafico_matriz_correlacion,
    grafico_radar_comparado,
)
from dashboard.tarjetas import mostrar_kpis, titulo_seccion
from finanzas import comparar as cp
from finanzas.score import COMPONENTES_ACCIONES, COMPONENTES_ETFS, nivel_score

TIPOS = {
    'ETF': {'componentes': COMPONENTES_ETFS, 'nombre': 'Nombre', 'grupo': 'Category',
            'formato': {c[0]: (c[3], c[4]) for c in COLUMNAS_EXPLORADOR_ETFS}},
    'Acción': {'componentes': COMPONENTES_ACCIONES, 'nombre': 'Empresa', 'grupo': 'Sector',
               'formato': {c[0]: (c[3], c[4]) for c in COLUMNAS_EXPLORADOR_ACCIONES}},
}


def _universo(df_etfs, df_stocks):
    """{ticker: (tipo, fila)} con todos los tickers de la base; un ticker que esté en las dos
    listas se trata como ETF."""
    universo = {}
    for tipo, df in (('Acción', df_stocks), ('ETF', df_etfs)):
        if df is None or df.empty:
            continue
        for _, fila in df.iterrows():
            universo[fila['Ticker']] = (tipo, fila)
    return universo


def _texto(fila, columna, default=''):
    valor = fila.get(columna) if columna in fila.index else None
    return default if valor is None or pd.isna(valor) else str(valor)


def _valor(formato, columna, valor):
    if valor is None or pd.isna(valor):
        return 'sin dato'
    sufijo, decimales = formato.get(columna, ('', 2))
    return f"{valor:,.{decimales}f}{sufijo}"


@st.cache_data(ttl=3600, show_spinner=False)
def _precios_referencia():
    return descargar_precios_cierre((cp.INDICE_REFERENCIA,))


def selector(universo):
    opciones = sorted(universo, key=lambda t: (universo[t][0] != 'ETF', t))

    def etiqueta(t):
        tipo, fila = universo[t]
        nombre = _texto(fila, TIPOS[tipo]['nombre'])
        return f"{t} · {nombre[:38]} ({tipo})" if nombre and nombre != t else f"{t} ({tipo})"

    if 'comparar_tickers' not in st.session_state:
        por_score = sorted((t for t in opciones if universo[t][0] == 'ETF'),
                           key=lambda t: -(universo[t][1].get('Score_Final') or 0))
        st.session_state.comparar_tickers = por_score[:2]
    st.session_state.comparar_tickers = [t for t in st.session_state.comparar_tickers if t in universo]
    return st.multiselect(
        f"Elige hasta {cp.MAX_TICKERS} tickers (ETFs, acciones o una mezcla)", opciones,
        max_selections=cp.MAX_TICKERS, format_func=etiqueta, key='comparar_tickers',
        placeholder="Escribe un ticker o un nombre…")


def seccion_precios(precios_anio, seleccion, colores):
    with st.container(border=True):
        titulo_seccion("1. Precio en el último año",
                       f"Comparado contra el {cp.NOMBRE_REFERENCIA} (línea punteada)")
        modo = st.segmented_control("Ver", ['Rendimiento acumulado (%)', 'Precio (USD)'],
                                    default='Rendimiento acumulado (%)', key='comparar_modo',
                                    label_visibility='collapsed') or 'Rendimiento acumulado (%)'
        en_porcentaje = modo.startswith('Rendimiento')
        datos = precios_anio
        if not en_porcentaje:
            # En USD el S&P 500 (miles de puntos) aplastaría a los demás: se omite.
            datos = datos.drop(columns=[cp.INDICE_REFERENCIA], errors='ignore')
        else:
            datos = cp.rendimiento_acumulado(datos)
        st.plotly_chart(grafico_comparar_precios(datos, colores, cp.INDICE_REFERENCIA, cp.NOMBRE_REFERENCIA,
                                                 en_porcentaje), width='stretch', key='comparar_precios')
        desde, hasta = precios_anio.index.min(), precios_anio.index.max()

        metricas = cp.metricas_anio(precios_anio)
        filas = []
        for t in [*seleccion, cp.INDICE_REFERENCIA]:
            if t not in metricas.index:
                continue
            m = metricas.loc[t]
            filas.append({
                'Ticker': cp.NOMBRE_REFERENCIA if t == cp.INDICE_REFERENCIA else t,
                'Precio actual': precios_anio[t].dropna().iloc[-1],
                'Rendimiento 1a': m['Rendimiento_%'], 'Volatilidad 1a': m['Volatilidad_%'],
                'Caída máxima 1a': m['Caida_Max_%'],
                f'Beta vs {cp.NOMBRE_REFERENCIA}': m['Beta'],
            })
        tabla = pd.DataFrame(filas)
        st.dataframe(tabla.style.format({
            'Precio actual': '${:,.2f}', 'Rendimiento 1a': '{:+.1f}%', 'Volatilidad 1a': '{:.1f}%',
            'Caída máxima 1a': '{:.1f}%', f'Beta vs {cp.NOMBRE_REFERENCIA}': '{:.2f}'}, na_rep='—'),
            hide_index=True, width='stretch')
        st.caption(f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}. Beta = cuánto se mueve el activo cuando el "
                   f"{cp.NOMBRE_REFERENCIA} se mueve 1 % (1 = igual que el mercado, 2 = el doble).")
        faltan = [t for t in seleccion if t not in precios_anio.columns]
        if faltan:
            st.warning("Sin precios del último año para: " + ", ".join(faltan))
        if cp.INDICE_REFERENCIA not in precios_anio.columns:
            st.info(f"No se pudieron obtener los precios del {cp.NOMBRE_REFERENCIA}; se compara sin él.")


def seccion_score(universo, seleccion, colores):
    with st.container(border=True):
        titulo_seccion("2. Score y sus criterios",
                       "Percentil de cada criterio dentro de su universo (100 = el mejor de tu lista)")
        kpis = []
        for t in seleccion:
            tipo, fila = universo[t]
            nivel = nivel_score(fila.get('Score_Final'))[0]
            nombre = _texto(fila, TIPOS[tipo]['nombre'], t)
            grupo = _texto(fila, TIPOS[tipo]['grupo'])
            kpis.append((f"{t} · {tipo}", _f(fila.get('Score_Final')),
                         f"{nivel} · {nombre[:30]}" + (f" · {grupo}" if grupo else "")))
        mostrar_kpis(kpis)

        tipos_presentes = [tipo for tipo in TIPOS if any(universo[t][0] == tipo for t in seleccion)]
        if len(tipos_presentes) > 1:
            st.info("Elegiste ETFs y acciones: su score se calcula con criterios distintos y contra universos "
                    "distintos (ETFs contra ETFs, acciones contra acciones), así que se comparan por separado. "
                    "El precio y la correlación sí se comparan entre todos.")
        for tipo in tipos_presentes:
            cfg = TIPOS[tipo]
            tickers = [t for t in seleccion if universo[t][0] == tipo]
            if len(tipos_presentes) > 1:
                st.markdown(f"**{'ETFs' if tipo == 'ETF' else 'Acciones'}**")
            izq, der = st.columns([1, 1.25])
            with izq:
                st.plotly_chart(grafico_radar_comparado([(t, universo[t][1]) for t in tickers], cfg['componentes'],
                                                        colores), width='stretch', key=f'comparar_radar_{tipo}')
            with der:
                st.dataframe(_tabla_criterios(universo, tickers, cfg), width='stretch',
                             height=35 * (len(cfg['componentes']) + 2) + 3)
                st.caption("Valor real y, entre paréntesis, su percentil. En negritas, el mejor de la "
                           "comparación en cada criterio. En los criterios «inv.» menos es mejor.")


def _tabla_criterios(universo, tickers, cfg):
    filas, mejores = {}, {}
    score = {t: universo[t][1].get('Score_Final') for t in tickers}
    filas['Score (peso)'] = {t: _f(score[t]) for t in tickers}
    mejores['Score (peso)'] = _mejor(score)
    for etiqueta, col_pctl, peso, col_valor in cfg['componentes']:
        nombre = f"{etiqueta} ({peso:.0%})"
        pctl = {t: universo[t][1].get(col_pctl) for t in tickers}
        filas[nombre] = {
            t: _valor(cfg['formato'], col_valor, universo[t][1].get(col_valor))
            + (f"  (p{pctl[t]:.0f})" if pctl[t] is not None and pd.notna(pctl[t]) else '')
            for t in tickers}
        mejores[nombre] = _mejor(pctl)
    tabla = pd.DataFrame.from_dict(filas, orient='index')
    tabla.index.name = 'Criterio'
    return tabla.style.apply(
        lambda col: ['font-weight: 700' if col.name in mejores[i] else '' for i in col.index], axis=0)


def _mejor(valores):
    """Tickers con el valor más alto (solo si hay al menos dos con dato)."""
    validos = {t: v for t, v in valores.items() if v is not None and pd.notna(v)}
    if len(validos) < 2:
        return set()
    maximo = max(validos.values())
    return {t for t, v in validos.items() if v == maximo}


def seccion_correlacion(precios_anio, seleccion):
    with st.container(border=True):
        titulo_seccion("3. Correlación (rendimientos diarios, 1 año)",
                       "1 = se mueven igual · 0 = sin relación · −1 = se mueven al revés. "
                       "Una correlación baja entre ellos diversifica más.")
        columnas = [t for t in [*seleccion, cp.INDICE_REFERENCIA] if t in precios_anio.columns]
        matriz = cp.matriz_correlacion(precios_anio[columnas])
        if matriz.empty:
            st.info("Se necesitan al menos 2 series con precios para calcular la correlación.")
            return
        matriz = matriz.rename(index={cp.INDICE_REFERENCIA: cp.NOMBRE_REFERENCIA},
                               columns={cp.INDICE_REFERENCIA: cp.NOMBRE_REFERENCIA})
        izq, der = st.columns([1.3, 1])
        with izq:
            st.plotly_chart(grafico_matriz_correlacion(matriz), width='stretch', key='comparar_correlacion')
        with der:
            nombres = list(matriz.columns)
            lineas = []
            for i, a in enumerate(nombres):
                for b in nombres[i + 1:]:
                    valor = matriz.loc[a, b]
                    lineas.append(f"- **{a}** y **{b}**: {valor:.2f} · {cp.describir_correlacion(valor)}")
            st.markdown("\n".join(lineas))


def mostrar(df_etfs, df_stocks, precios_cierre):
    """`df_etfs` y `df_stocks` son las tablas completas (sin los filtros de la barra lateral)."""
    universo = _universo(df_etfs, df_stocks)
    if not universo:
        st.warning("No hay tickers cargados. Añade ETFs o acciones desde el menú lateral.")
        return
    seleccion = selector(universo)
    if not seleccion:
        st.info(f"Elige de 1 a {cp.MAX_TICKERS} tickers para compararlos.")
        return
    colores = dict(zip(seleccion, COLORES_COMPARAR, strict=False))

    referencia = _precios_referencia()
    precios = precios_cierre
    if referencia is not None and cp.INDICE_REFERENCIA in getattr(referencia, 'columns', []):
        ref = referencia[[cp.INDICE_REFERENCIA]].copy()
        ref.index = pd.to_datetime(ref.index).tz_localize(None).normalize()
        base = precios_cierre[[t for t in seleccion if t in precios_cierre.columns]].copy()
        base.index = pd.to_datetime(base.index).tz_localize(None).normalize()
        precios = base.join(ref, how='outer')
    precios_anio = cp.ultimo_anio(precios, [*seleccion, cp.INDICE_REFERENCIA])

    if precios_anio.empty:
        st.warning("No hay precios del último año para estos tickers.")
    else:
        seccion_precios(precios_anio, seleccion, colores)
    seccion_score(universo, seleccion, colores)
    if not precios_anio.empty:
        seccion_correlacion(precios_anio, seleccion)
