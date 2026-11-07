"""Pestaña "Mi portafolio": compras guardadas, valoración, gráficas y simulador.

Los cálculos viven en finanzas/portafolio.py; las compras se guardan en la base (tabla posiciones).
"""
import hmac
from datetime import date

import pandas as pd
import streamlit as st

from dashboard.carga import precios_recientes
from dashboard.formato import _color_variacion, _mapear, _pct, _usd
from dashboard.graficos import grafico_ganancia_por_ticker, grafico_pesos
from dashboard.tarjetas import mostrar_kpis, titulo_seccion
from finanzas import almacenamiento
from finanzas import portafolio as pf


def clave_portafolio():
    """Clave opcional de la pestaña ([portafolio] clave = "..." en los secrets)."""
    try:
        return st.secrets.get('portafolio', {}).get('clave')
    except Exception:
        return None


def editor_posiciones():
    """Tabla editable de compras. Devuelve las compras tal como están en el editor (limpias)."""
    if 'posiciones' not in st.session_state:
        try:
            guardadas = almacenamiento.cargar_posiciones()
        except Exception as e:
            st.error(f"No se pudieron leer las compras guardadas: {e}")
            guardadas = None
        st.session_state.posiciones_en_base = guardadas is not None
        st.session_state.posiciones = pf.limpiar_posiciones(guardadas)
        st.session_state.version_editor = 0

    with st.container(border=True):
        titulo_seccion("Mis compras",
                       "Una fila por compra (puedes repetir un ticker si compraste en varias fechas). "
                       "Agrega filas con «+», bórralas seleccionándolas y usando la papelera.")
        para_editor = st.session_state.posiciones.copy()
        para_editor['Fecha'] = pd.to_datetime(para_editor['Fecha'], errors='coerce')
        editado = st.data_editor(
            para_editor, num_rows='dynamic', hide_index=True, width='stretch',
            key=f"editor_posiciones_{st.session_state.version_editor}",
            column_config={
                'Ticker': st.column_config.TextColumn('Ticker', required=True),
                'Fecha': st.column_config.DateColumn('Fecha de compra', format='DD/MM/YYYY',
                                                     min_value=date(1950, 1, 1), max_value=date.today()),
                'Precio_Compra': st.column_config.NumberColumn('Precio de compra (USD)', min_value=0.0,
                                                               format='%.2f', required=True),
                'Cantidad': st.column_config.NumberColumn('Cantidad', min_value=0.0, format='%.4f',
                                                          required=True),
            })
        limpias = pf.limpiar_posiciones(editado)
        hay_cambios = not limpias.equals(pf.limpiar_posiciones(st.session_state.posiciones))

        col_boton, col_aviso = st.columns([1, 3])
        if col_boton.button('💾 Guardar cambios', disabled=not hay_cambios, width='stretch'):
            try:
                if st.session_state.posiciones_en_base:
                    almacenamiento.guardar_posiciones(limpias)
                st.session_state.posiciones = limpias
                st.session_state.version_editor += 1
                incompletas = len(editado.dropna(how='all')) - len(limpias)
                st.session_state.aviso_portafolio = (
                    f"Compras guardadas ({len(limpias)})."
                    + (f" Se descartaron {incompletas} filas incompletas (falta ticker, precio o cantidad)."
                       if incompletas > 0 else ""))
                st.rerun()
            except Exception as e:
                st.error(f"No se pudieron guardar las compras: {e}")
        if hay_cambios:
            col_aviso.caption("Tienes cambios sin guardar. Los cálculos de abajo ya los incluyen.")
        elif st.session_state.get('aviso_portafolio'):
            col_aviso.success(st.session_state.pop('aviso_portafolio'))
    return limpias


def mostrar_portafolio():
    clave = clave_portafolio()
    if not clave:
        st.warning("Esta pestaña no tiene clave: cualquiera con el enlace de la app puede ver tus compras. "
                   "Agrega `[portafolio]` y `clave = \"...\"` en los secrets para protegerla.")
    posiciones = editor_posiciones()
    if not st.session_state.posiciones_en_base:
        st.info("No hay base de datos configurada: las compras se pierden al cerrar la app.")

    tickers = tuple(dict.fromkeys(posiciones['Ticker']))
    precios, fecha_precios = precios_recientes(tickers)
    lotes = pf.valorar_lotes(posiciones, precios)

    # --- Resumen de la cartera ---
    if not lotes.empty:
        t = pf.totales(lotes)
        resumen = pf.resumir_por_ticker(lotes)
        texto_fecha = f"Precios al {fecha_precios:%d/%m/%Y}" if fecha_precios is not None else "Sin precios"
        kpis = [
            ("Valor actual", _usd(t['valor']), texto_fecha),
            ("Invertido", _usd(t['costo']), f"{len(lotes)} compras · {len(resumen)} tickers"),
            ("Ganancia / pérdida", _usd(t['ganancia'], signo=True), _pct(t['ganancia_pct'])),
        ]
        if resumen['Peso_%'].notna().any():
            mayor = resumen.loc[resumen['Peso_%'].idxmax()]
            kpis.append(("Mayor peso", mayor['Ticker'], f"{mayor['Peso_%']:.1f}% de la cartera"))
        mostrar_kpis(kpis)
        if t['sin_precio']:
            st.warning("Sin precio actual (revisa el ticker): " + ", ".join(t['sin_precio'])
                       + ". No se incluyen en los totales.")
        st.write("")

        with st.container(border=True):
            titulo_seccion("Participaciones por ticker",
                           "Suma de todas las compras de cada ticker · peso = valor actual / valor total")
            vista = resumen.rename(columns={
                'Precio_Promedio': 'Precio prom.', 'Precio_Actual': 'Precio actual',
                'Costo_USD': 'Invertido', 'Valor_USD': 'Valor actual',
                'Ganancia_USD': 'Ganancia USD', 'Ganancia_%': 'Ganancia %', 'Peso_%': 'Peso %'})
            estilo = vista.style.format({
                'Cantidad': '{:,.4g}', 'Precio prom.': '${:,.2f}', 'Precio actual': '${:,.2f}',
                'Invertido': '${:,.2f}', 'Valor actual': '${:,.2f}', 'Ganancia USD': '{:+,.2f}',
                'Ganancia %': '{:+.2f}%'}, na_rep='—')
            estilo = _mapear(estilo, _color_variacion, ['Ganancia USD', 'Ganancia %'])
            st.dataframe(estilo, hide_index=True, width='stretch', column_config={
                'Peso %': st.column_config.ProgressColumn('Peso %', min_value=0, max_value=100,
                                                          format='%.1f%%')})

        izq, der = st.columns(2)
        with izq:
            with st.container(border=True):
                titulo_seccion("Distribución de la cartera", "Peso de cada ticker sobre el valor actual")
                if resumen['Valor_USD'].fillna(0).gt(0).any():
                    st.plotly_chart(grafico_pesos(resumen), width='stretch', key='pie_portafolio')
                else:
                    st.info("Sin precios para calcular la distribución.")

        with der:
            with st.container(border=True):
                titulo_seccion("Ganancia / pérdida por ticker", "En USD, sumando todas las compras de cada ticker")
                if resumen['Ganancia_USD'].notna().any():
                    st.plotly_chart(grafico_ganancia_por_ticker(resumen), width='stretch', key='gan_portafolio')
                else:
                    st.info("Sin precios para calcular la ganancia.")

        with st.expander("Detalle por compra"):
            detalle = lotes[['Ticker', 'Fecha', 'Cantidad', 'Precio_Compra', 'Precio_Actual',
                             'Costo_USD', 'Valor_USD', 'Ganancia_USD', 'Ganancia_%']].rename(columns={
                'Precio_Compra': 'Precio compra', 'Precio_Actual': 'Precio actual', 'Costo_USD': 'Invertido',
                'Valor_USD': 'Valor actual', 'Ganancia_USD': 'Ganancia USD', 'Ganancia_%': 'Ganancia %'})
            estilo = detalle.style.format({
                'Fecha': lambda f: f.strftime('%d/%m/%Y') if pd.notna(f) and f is not None else '—',
                'Cantidad': '{:,.4g}', 'Precio compra': '${:,.2f}', 'Precio actual': '${:,.2f}',
                'Invertido': '${:,.2f}', 'Valor actual': '${:,.2f}', 'Ganancia USD': '{:+,.2f}',
                'Ganancia %': '{:+.2f}%'}, na_rep='—')
            estilo = _mapear(estilo, _color_variacion, ['Ganancia USD', 'Ganancia %'])
            st.dataframe(estilo, hide_index=True, width='stretch')
    else:
        st.info("Agrega tus compras en la tabla de arriba para ver el valor, la ganancia y la distribución "
                "de tu cartera. El simulador de abajo funciona aunque todavía no tengas compras.")

    # --- Simulador de compra ---
    with st.container(border=True):
        titulo_seccion("Simulador de compra",
                       "Simula comprar un ticker al precio de la fecha de consulta y cómo cambiaría tu "
                       "ganancia si después su precio sube o baja.")
        opciones = list(dict.fromkeys(list(tickers) + st.session_state.etf_list + st.session_state.stock_list))
        c1, c2, c3 = st.columns(3)
        ticker_sim = c1.selectbox("Ticker (elige o escribe uno)", opciones, index=0 if opciones else None,
                                  accept_new_options=True, key='sim_ticker')
        if ticker_sim:
            ticker_sim = str(ticker_sim).strip().upper()
            precio_hoy = precios.get(ticker_sim)
            if precio_hoy is None:
                precio_hoy = precios_recientes((ticker_sim,))[0].get(ticker_sim)
            cantidad_sim = c2.number_input("Cantidad", min_value=0.0, value=1.0, step=1.0, key='sim_cantidad')
            precio_sim = c3.number_input("Precio de compra (USD)", min_value=0.0,
                                         value=float(precio_hoy or 0.0), step=1.0, format='%.2f',
                                         key=f'sim_precio_{ticker_sim}',
                                         help="Por defecto, el último precio disponible a la fecha de consulta.")
            if precio_hoy is None:
                st.warning(f"No se encontró precio para {ticker_sim}; ingresa el precio a mano.")
            variacion = st.slider(f"Si el precio de {ticker_sim} cambia (%)", min_value=-50, max_value=100,
                                  value=0, step=1, key='sim_variacion')

            if cantidad_sim > 0 and precio_sim > 0:
                sim = pf.simular_compra(lotes, ticker_sim, cantidad_sim, precio_sim, variacion)
                sin, con = sim['sin_compra'], sim['con_compra']
                mostrar_kpis([
                    ("Monto de la compra", _usd(sim['monto']), f"{cantidad_sim:,.4g} × {_usd(precio_sim)}"),
                    ("Ganancia de la compra", _usd(sim['ganancia_compra'], signo=True),
                     f"con {variacion:+d}% en {ticker_sim}"),
                    ("Ganancia total", _usd(con['ganancia'], signo=True),
                     f"sin comprar: {_usd(sin['ganancia'], signo=True)} · Δ {_usd(sim['delta_ganancia'], signo=True)}"),
                    (f"Peso de {ticker_sim}", _pct(con['peso_ticker_pct'], signo=False),
                     f"antes: {_pct(sin['peso_ticker_pct'], signo=False)}"),
                ])
                comparacion = pd.DataFrame({
                    'Concepto': ['Invertido', 'Valor', 'Ganancia USD', 'Ganancia %',
                                 f'Peso de {ticker_sim}', f'Cantidad de {ticker_sim}',
                                 f'Precio promedio de {ticker_sim}'],
                    'Sin comprar': [_usd(sin['costo']), _usd(sin['valor']), _usd(sin['ganancia'], signo=True),
                                    _pct(sin['ganancia_pct']), _pct(sin['peso_ticker_pct'], signo=False),
                                    f"{sin['cantidad_ticker']:,.4g}", _usd(sin['precio_promedio_ticker'])],
                    'Comprando': [_usd(con['costo']), _usd(con['valor']), _usd(con['ganancia'], signo=True),
                                  _pct(con['ganancia_pct']), _pct(con['peso_ticker_pct'], signo=False),
                                  f"{con['cantidad_ticker']:,.4g}", _usd(con['precio_promedio_ticker'])],
                })
                st.write("")
                st.dataframe(comparacion, hide_index=True, width='stretch')
                st.caption(f"Ambas columnas suponen que {ticker_sim} cambia {variacion:+d}% desde "
                           f"{_usd(precio_sim)}. La simulación no se guarda.")


def mostrar():
    """Pide la clave (si está configurada en los secrets) y muestra el portafolio."""
    clave_requerida = clave_portafolio()
    if clave_requerida and not st.session_state.get('portafolio_ok'):
        with st.form('form_clave_portafolio'):
            intento = st.text_input("Clave del portafolio", type='password')
            if st.form_submit_button("Entrar"):
                if hmac.compare_digest(intento.encode(), str(clave_requerida).encode()):
                    st.session_state.portafolio_ok = True
                    st.rerun()
                else:
                    st.error("Clave incorrecta.")
    else:
        mostrar_portafolio()
