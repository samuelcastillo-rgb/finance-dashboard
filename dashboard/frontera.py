"""Sub-pestaña "Portafolio óptimo": la frontera eficiente de Markowitz de los ETFs, de las
acciones o de todo junto, y la comparación de tu portafolio real con el óptimo combinado.
Las fronteras las calcula cada día el optimizador en Rust (optimizador/) dentro del proceso
diario; aquí se leen de la base y tu portafolio se mide con los mismos datos y supuestos."""
import pandas as pd
import streamlit as st

from dashboard.carga import cargar_frontera_guardada, descargar_precios_cierre, precios_recientes
from dashboard.graficos import (
    COLOR_OPTIMO,
    COLOR_REAL,
    grafico_comparar_precios,
    grafico_frontera,
    grafico_mezcla_tipos,
    grafico_pesos_cartera,
    grafico_pesos_comparados,
)
from dashboard.pestanas.portafolio import clave_portafolio
from dashboard.tarjetas import mostrar_kpis, titulo_seccion
from finanzas import almacenamiento
from finanzas import frontera as fr
from finanzas import portafolio as pf
from finanzas.comparar import INDICE_REFERENCIA, NOMBRE_REFERENCIA

OPCION_COMBINADA = "ETFs + acciones vs. mi portafolio"


def _pct(valor, decimales=1):
    return f"{valor * 100:.{decimales}f}%"


def _aviso_sin_frontera():
    if almacenamiento.hay_base_de_datos():
        st.info("Todavía no hay una frontera eficiente calculada. Se calcula en el proceso diario "
                "(GitHub Action «Actualizar datos diarios»); puedes correrlo a mano desde la pestaña Actions.")
    else:
        st.info("La frontera eficiente la calcula el proceso diario y se guarda en la base de datos; "
                "sin base configurada no está disponible.")


def _nombres(*tablas):
    """{ticker: nombre} de las tablas de ETFs (columna Nombre) y acciones (columna Empresa)."""
    nombres = {}
    for df in tablas:
        columna = next((c for c in ('Nombre', 'Empresa') if df is not None and c in df.columns), None)
        if columna and 'Ticker' in df.columns:
            nombres.update(zip(df['Ticker'], df[columna].fillna('').astype(str), strict=True))
    return nombres


def mostrar_portafolio_optimo(clave, nombre_plural, df, tablas_completas=(None, None)):
    """Sub-pestaña completa: elige entre la frontera de la lista de la pestaña y la combinada
    (ETFs + acciones) comparada con tu portafolio. `tablas_completas` = (ETFs, acciones) sin filtros."""
    propia = f"Solo {nombre_plural}"
    eleccion = st.segmented_control("Universo", [propia, OPCION_COMBINADA], default=propia,
                                    key=f'universo_optimo_{clave}', label_visibility='collapsed') or propia
    if eleccion == propia:
        mostrar_frontera(clave, nombre_plural, df)
    else:
        mostrar_combinada(clave, *tablas_completas)


def mostrar_frontera(clave, nombre_plural, df, key=None, nombres=None):
    """`clave` = clave de la frontera guardada ('etf_list', 'stock_list' o 'combinada'); `df`
    (tabla de la pestaña) solo aporta nombres, o se pasan ya armados en `nombres`.
    `key` distingue los widgets si la misma frontera se dibuja en dos pestañas."""
    resultado, fecha = cargar_frontera_guardada(clave)
    if resultado is None:
        _aviso_sin_frontera()
        return
    clave_widgets = key or clave
    nombres = nombres if nombres is not None else _nombres(df)
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
            eleccion = st.segmented_control("Cartera", opciones, default=opciones[0],
                                            key=f'frontera_cartera_{clave_widgets}',
                                            label_visibility='collapsed') or opciones[0]
            if eleccion == opciones[0]:
                elegida = ms
            elif eleccion == opciones[1]:
                elegida = mv
            else:
                etiquetas = [f"vol. {_pct(c['volatilidad'])} · rend. {_pct(c['rendimiento'])}" for c in frontera]
                inicial = min(range(len(frontera)), key=lambda i: abs(frontera[i]['sharpe'] - ms['sharpe']))
                etiqueta = st.select_slider("Nivel de riesgo (de menor a mayor volatilidad)", etiquetas,
                                            value=etiquetas[inicial], key=f'frontera_punto_{clave_widgets}')
                elegida = frontera[etiquetas.index(etiqueta)]
            st.markdown(f"**Rendimiento esperado** {_pct(elegida['rendimiento'])} · "
                        f"**Volatilidad** {_pct(elegida['volatilidad'])} · **Sharpe** {elegida['sharpe']:.2f}")
            st.plotly_chart(grafico_pesos_cartera(elegida['pesos'], nombres), width='stretch',
                            key=f'frontera_pesos_{clave_widgets}')
    with izq:
        with st.container(border=True):
            titulo_seccion("Frontera eficiente",
                           "Cada punto de la línea verde es la cartera con menos volatilidad para ese rendimiento "
                           "esperado · los puntos grises son cada activo por separado")
            st.plotly_chart(grafico_frontera(resultado, elegida, nombres), width='stretch',
                            key=f'frontera_grafico_{clave_widgets}')

    with st.expander("Tabla de pesos y supuestos", key=f'frontera_supuestos_{clave_widgets}'):
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


# ------------------------------------------------------------------------------
# Tu portafolio real contra el óptimo combinado (ETFs + acciones)
# ------------------------------------------------------------------------------
def _portafolio_bloqueado():
    return bool(clave_portafolio()) and not st.session_state.get('portafolio_ok')


def _valores_portafolio():
    """{ticker: valor actual en USD} de las compras guardadas (las mismas de «Mi portafolio»)."""
    posiciones = st.session_state.get('posiciones')
    if posiciones is None:
        try:
            posiciones = pf.limpiar_posiciones(almacenamiento.cargar_posiciones())
        except Exception:
            return {}
    if posiciones is None or posiciones.empty:
        return {}
    precios, _ = precios_recientes(tuple(dict.fromkeys(posiciones['Ticker'])))
    resumen = pf.resumir_por_ticker(pf.valorar_lotes(posiciones, precios))
    resumen = resumen[resumen['Valor_USD'].notna() & (resumen['Valor_USD'] > 0)]
    return dict(zip(resumen['Ticker'], resumen['Valor_USD'].astype(float), strict=True))


def _tipo(ticker):
    if ticker in st.session_state.get('etf_list', []):
        return 'ETFs'
    if ticker in st.session_state.get('stock_list', []):
        return 'Acciones'
    return 'Otros'


def _mezcla(pesos):
    mezcla = {}
    for t, p in pesos.items():
        mezcla[_tipo(t)] = mezcla.get(_tipo(t), 0.0) + p
    return mezcla


def _pp(valor, signo=True):
    """Diferencia en puntos porcentuales (valor en fracción)."""
    return f"{valor * 100:{'+' if signo else ''}.1f} pp"


def mostrar_combinada(key, df_etfs_todos=None, df_stocks_todos=None):
    """Frontera de ETFs + acciones (+ tus tickers) y tu portafolio comparado con su máximo Sharpe."""
    if _portafolio_bloqueado():
        st.info("Tu portafolio está protegido con clave. Ábrelo en la pestaña 💼 Mi portafolio y vuelve aquí "
                "para compararlo con el óptimo.")
        return
    resultado, fecha = cargar_frontera_guardada(fr.CLAVE_COMBINADA)
    if resultado is None:
        _aviso_sin_frontera()
        return
    nombres = _nombres(df_etfs_todos, df_stocks_todos)
    valores = _valores_portafolio()
    if not valores:
        st.info("Agrega tus compras en la pestaña 💼 Mi portafolio para compararlas con el óptimo. "
                "Mientras tanto, esta es la frontera eficiente de ETFs y acciones juntos.")
        mostrar_frontera(fr.CLAVE_COMBINADA, 'activos', None, key=f'{key}_combinada', nombres=nombres)
        return

    activos = tuple(sorted(a['ticker'] for a in resultado['activos']))
    precios = descargar_precios_cierre(activos + (INDICE_REFERENCIA,))
    rend = fr.rendimientos_de_resultado(precios, resultado) if not precios.empty else pd.DataFrame()
    comp = fr.comparar_con_optimo(valores, resultado, rend) if not rend.empty else None
    if comp is None:
        st.warning("Ninguno de los tickers de tu portafolio está en la frontera combinada (hacen falta 3 años "
                   "de precios). Si los agregaste hace poco, se incluyen en la próxima corrida del proceso diario.")
        mostrar_frontera(fr.CLAVE_COMBINADA, 'activos', None, key=f'{key}_combinada', nombres=nombres)
        return
    _mostrar_comparacion(key, resultado, fecha, comp, rend, precios, nombres)


def _mostrar_comparacion(key, resultado, fecha, comp, rend, precios, nombres):
    real, opt = comp['real'], comp['optimo']
    tipos = pd.Series([_tipo(a['ticker']) for a in resultado['activos']]).value_counts()
    st.caption(
        f"Frontera combinada calculada el {fecha:%d/%m/%Y} con {len(resultado['activos'])} activos "
        f"({tipos.get('ETFs', 0)} ETFs, {tipos.get('Acciones', 0)} acciones"
        + (f", {tipos.get('Otros', 0)} solo de tu portafolio" if tipos.get('Otros', 0) else "")
        + f") · {resultado['desde']} a {resultado['hasta']} · peso máximo por activo "
        f"{_pct(resultado['peso_maximo'], 0)} · tasa libre de riesgo {_pct(resultado['tasa_libre'])} · "
        "tu portafolio se mide con los mismos datos y supuestos")
    if comp['fuera']:
        st.warning(f"Sin 3 años de historia, no entran en la comparación: {', '.join(comp['fuera'])} "
                   f"({_pct(1 - comp['cobertura'])} de tu cartera). El resto se reparte en proporción a su valor.")

    eficiencia = comp['eficiencia_sharpe']
    nivel = fr.nivel_cercania(eficiencia)
    riesgo = comp['riesgo_extra']
    mostrar_kpis([
        ("Cercanía al máximo Sharpe", "—" if pd.isna(eficiencia) else f"{max(eficiencia, 0):.0%}",
         f"{nivel} · Sharpe {real['sharpe']:.2f} de {opt['sharpe']:.2f}"),
        ("Rendimiento que te falta", _pp(max(comp['rendimiento_perdido'], 0), signo=False),
         f"al año, con tu mismo riesgo ({_pct(real['volatilidad'])} de volatilidad)"),
        ("Riesgo de más", "—" if riesgo is None else _pp(max(riesgo, 0), signo=False),
         "rindes más que toda la frontera" if riesgo is None
         else f"de volatilidad, para tu mismo rendimiento ({_pct(real['rendimiento'])})"),
        ("Coincidencia de pesos", _pct(comp['coincidencia_pesos'], 0),
         f"con el máximo Sharpe · error de seguimiento {_pct(comp['tracking_error'])}"),
    ])
    st.write("")
    st.markdown(_resumen(comp))

    opciones = {'Máximo Sharpe': opt['pesos'], 'Frontera con tu mismo riesgo': comp['misma_volatilidad']['pesos'],
                'Mínima volatilidad': resultado['min_volatilidad']['pesos']}
    izq, der = st.columns(2)
    with izq:
        with st.container(border=True):
            titulo_seccion("Tu portafolio frente a la frontera eficiente",
                           "Línea verde: lo mejor que se puede lograr con ETFs y acciones para cada nivel de "
                           "riesgo · las líneas punteadas miden cuánto rendimiento te falta con tu mismo riesgo "
                           "y cuánto riesgo te sobra para tu mismo rendimiento")
            st.plotly_chart(grafico_frontera(resultado, resultado['max_sharpe'], nombres, real=comp),
                            width='stretch', key=f'comparacion_frontera_{key}')
    with der:
        with st.container(border=True):
            titulo_seccion("Cómo les habría ido en la misma ventana",
                           f"100 USD con los pesos de hoy fijos, de {resultado['desde']} a {resultado['hasta']}. "
                           "El máximo Sharpe se eligió con estos mismos datos, así que esta gráfica lo favorece: "
                           "muestra el pasado, no promete el futuro.")
            series = pd.DataFrame({'Tu portafolio': fr.crecimiento(rend, real['pesos']),
                                   'Máximo Sharpe': fr.crecimiento(rend, opt['pesos'])})
            referencia = None
            if INDICE_REFERENCIA in precios.columns:
                sp = precios[INDICE_REFERENCIA].copy()
                sp.index = pd.to_datetime(sp.index)
                sp = sp[(sp.index >= series.index[0]) & (sp.index <= series.index[-1])].dropna()
                if len(sp) > 1:
                    series[NOMBRE_REFERENCIA] = (sp / sp.iloc[0] * 100).reindex(series.index).ffill()
                    referencia = NOMBRE_REFERENCIA
            colores = {'Tu portafolio': COLOR_REAL, 'Máximo Sharpe': COLOR_OPTIMO}
            st.plotly_chart(grafico_comparar_precios(series - 100, colores, referencia=referencia,
                                                     nombre_referencia=NOMBRE_REFERENCIA),
                            width='stretch', key=f'comparacion_crecimiento_{key}')

    with st.container(border=True):
        titulo_seccion("Pesos: tu portafolio vs. el óptimo",
                       "Los tickers con más peso en cualquiera de las dos carteras y cómo se reparten entre "
                       "ETFs y acciones")
        objetivo = st.segmented_control("Cartera óptima", list(opciones), default='Máximo Sharpe',
                                        key=f'comparacion_objetivo_{key}',
                                        label_visibility='collapsed') or 'Máximo Sharpe'
        izq, der = st.columns([1.6, 1])
        izq.plotly_chart(grafico_pesos_comparados(real['pesos'], opciones[objetivo], objetivo, nombres, maximo=12),
                         width='stretch', key=f'comparacion_pesos_{key}')
        der.plotly_chart(grafico_mezcla_tipos({'Tu portafolio': _mezcla(real['pesos']),
                                               objetivo: _mezcla(opciones[objetivo])}),
                         width='stretch', key=f'comparacion_mezcla_{key}')

    with st.expander("Qué mover para acercarte y cómo se mide", key=f'comparacion_detalle_{key}'):
        tabla = pd.DataFrame({'Tu peso %': pd.Series(real['pesos'], dtype=float),
                              'Óptimo %': pd.Series(opt['pesos'], dtype=float)}).fillna(0.0) * 100
        tabla['Diferencia pp'] = tabla['Óptimo %'] - tabla['Tu peso %']
        tabla = tabla[tabla[['Tu peso %', 'Óptimo %']].max(axis=1) >= 0.05]
        tabla = tabla.reindex(tabla['Diferencia pp'].abs().sort_values(ascending=False).index)
        tabla.insert(0, 'Tipo', [_tipo(t) for t in tabla.index])
        tabla.insert(0, 'Nombre', [nombres.get(t, '') for t in tabla.index])
        tabla = tabla.rename_axis('Ticker').reset_index()
        st.caption("Diferencia = peso en el máximo Sharpe − tu peso: positivo es subir, negativo es bajar.")
        st.dataframe(tabla, hide_index=True, width='stretch', column_config={
            'Tu peso %': st.column_config.NumberColumn(format='%.1f%%'),
            'Óptimo %': st.column_config.NumberColumn(format='%.1f%%'),
            'Diferencia pp': st.column_config.NumberColumn(format='%+.1f')})
        st.markdown(
            "- **Cercanía al máximo Sharpe** = Sharpe de tu portafolio ÷ Sharpe máximo. El Sharpe es "
            "(rendimiento esperado − tasa libre) ÷ volatilidad: cuánto rendimiento extra recibes por cada "
            "unidad de riesgo. 100 % es estar en el óptimo.\n"
            "- **Rendimiento que te falta:** distancia vertical a la frontera, es decir, cuánto más rendiría "
            "la mejor cartera con tu misma volatilidad. **Riesgo de más:** distancia horizontal, cuánta "
            "volatilidad te podrías ahorrar sin perder rendimiento.\n"
            "- **Coincidencia de pesos** = 1 − ½·Σ|tu peso − peso óptimo| (100 % = misma cartera, 0 % = "
            "ningún activo en común). **Error de seguimiento:** volatilidad anual de la diferencia entre "
            "las dos carteras.\n"
            "- **¿Es ruido?** Prueba de Jobson-Korkie con la corrección de Memmel sobre los rendimientos "
            f"diarios de los dos portafolios ({comp['n_dias']} días). Es optimista a favor del máximo Sharpe "
            "porque se eligió con los mismos datos.\n"
            "- Tu portafolio se mide con los pesos de hoy (valor actual de cada ticker), la misma ventana de "
            "3 años y la misma covarianza con contracción de Ledoit-Wolf que la frontera. La frontera "
            "limita cada activo a "
            f"{_pct(resultado['peso_maximo'], 0)}; si tu cartera concentra más, puede quedar por encima de ella.\n"
            "- No es una recomendación de inversión: no incluye comisiones, impuestos ni el costo de rebalancear.")


def _resumen(comp):
    """Una o dos frases que explican el resultado."""
    real, opt, eficiencia = comp['real'], comp['optimo'], comp['eficiencia_sharpe']
    if pd.isna(eficiencia):
        texto = (f"El máximo Sharpe de esta ventana no supera la tasa libre de riesgo, así que la cercanía no se "
                 f"puede medir. Tu Sharpe es {real['sharpe']:.2f}.")
    elif eficiencia >= 1:
        texto = (f"Tu portafolio tiene un Sharpe de **{real['sharpe']:.2f}**, igual o mayor que el máximo de la "
                 f"frontera ({opt['sharpe']:.2f}). Suele pasar cuando concentras más del "
                 "límite por activo en lo que más subió en estos 3 años.")
    elif real['sharpe'] <= 0:
        texto = (f"Tu portafolio está **muy lejos** del óptimo: en esta ventana su rendimiento esperado "
                 f"({_pct(real['rendimiento'])}) no supera la tasa libre de riesgo, así que su Sharpe es "
                 f"{real['sharpe']:.2f} contra {opt['sharpe']:.2f} del máximo.")
    else:
        texto = (f"Tu portafolio está **{fr.nivel_cercania(eficiencia)}** del óptimo: obtiene el "
                 f"**{eficiencia:.0%}** del rendimiento por unidad de riesgo que logra la cartera de máximo Sharpe "
                 f"({real['sharpe']:.2f} contra {opt['sharpe']:.2f}).")
        if comp['debajo_min_volatilidad']:
            texto += " Tiene menos volatilidad que la cartera de mínima volatilidad, a costa de rendimiento."
    p = comp['p_valor']
    if not pd.isna(p) and not pd.isna(eficiencia) and eficiencia < 1:
        significativa = p < 0.05
        texto += (f" Con {comp['n_dias']} días de datos, la diferencia "
                  + ("**es estadísticamente significativa**" if significativa
                     else "**no es estadísticamente significativa**")
                  + f" (p = {p:.2f})" + ("." if significativa else ": puede ser ruido de la muestra."))
    return texto
