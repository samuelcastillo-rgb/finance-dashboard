# portafolio.py
# Cálculos del portafolio personal: valoración de las compras (lotes), resumen por
# ticker con su peso en la cartera y simulador de compra. No depende de Streamlit:
# app.py se encarga de la presentación y almacenamiento.py de guardar las posiciones.

import numpy as np
import pandas as pd

COLUMNAS = ['Ticker', 'Fecha', 'Precio_Compra', 'Cantidad']


def posiciones_vacias():
    return pd.DataFrame({
        'Ticker': pd.Series(dtype='object'),
        'Fecha': pd.Series(dtype='object'),
        'Precio_Compra': pd.Series(dtype='float64'),
        'Cantidad': pd.Series(dtype='float64'),
    })


def limpiar_posiciones(df):
    """Normaliza lo que viene del editor: tickers en mayúsculas, fechas como date y
    descarta filas incompletas (sin ticker, precio <= 0 o cantidad <= 0)."""
    if df is None or len(df) == 0:
        return posiciones_vacias()
    df = df.reindex(columns=COLUMNAS).copy()
    df['Ticker'] = df['Ticker'].astype('string').str.strip().str.upper()
    df['Precio_Compra'] = pd.to_numeric(df['Precio_Compra'], errors='coerce')
    df['Cantidad'] = pd.to_numeric(df['Cantidad'], errors='coerce')
    fechas = pd.to_datetime(df['Fecha'], errors='coerce')
    # Una fecha imposible (antes de 1950 o en el futuro) se deja vacía
    fechas = fechas.where((fechas >= '1950-01-01') & (fechas <= pd.Timestamp.today()))
    df['Fecha'] = fechas.dt.date
    validas = (df['Ticker'].fillna('') != '') & (df['Precio_Compra'] > 0) & (df['Cantidad'] > 0)
    df = df[validas].copy()
    df['Ticker'] = df['Ticker'].astype(str)
    df['Fecha'] = df['Fecha'].astype('object').where(df['Fecha'].notna(), None)
    return df.reset_index(drop=True)


def valorar_lotes(posiciones, precios_actuales):
    """Agrega a cada compra su precio actual, costo, valor y ganancia (USD y %).
    `precios_actuales` es {ticker: precio}; un ticker sin precio queda con NaN."""
    lotes = limpiar_posiciones(posiciones)
    lotes['Precio_Actual'] = lotes['Ticker'].map(lambda t: precios_actuales.get(t, np.nan)).astype(float)
    lotes['Costo_USD'] = lotes['Precio_Compra'] * lotes['Cantidad']
    lotes['Valor_USD'] = lotes['Precio_Actual'] * lotes['Cantidad']
    lotes['Ganancia_USD'] = lotes['Valor_USD'] - lotes['Costo_USD']
    lotes['Ganancia_%'] = lotes['Ganancia_USD'] / lotes['Costo_USD'] * 100
    return lotes


def resumir_por_ticker(lotes):
    """Una fila por ticker (suma todas sus compras) con precio promedio y peso en la cartera.
    El peso se calcula sobre el valor actual de los tickers que tienen precio."""
    if lotes.empty:
        return pd.DataFrame(columns=['Ticker', 'Cantidad', 'Precio_Promedio', 'Precio_Actual',
                                     'Costo_USD', 'Valor_USD', 'Ganancia_USD', 'Ganancia_%', 'Peso_%'])
    res = lotes.groupby('Ticker', sort=False).agg(
        Cantidad=('Cantidad', 'sum'),
        Costo_USD=('Costo_USD', 'sum'),
        Precio_Actual=('Precio_Actual', 'first'),
    ).reset_index()
    res['Precio_Promedio'] = res['Costo_USD'] / res['Cantidad']
    res['Valor_USD'] = res['Precio_Actual'] * res['Cantidad']
    res['Ganancia_USD'] = res['Valor_USD'] - res['Costo_USD']
    res['Ganancia_%'] = res['Ganancia_USD'] / res['Costo_USD'] * 100
    total = res['Valor_USD'].sum(skipna=True)
    res['Peso_%'] = res['Valor_USD'] / total * 100 if total > 0 else np.nan
    res = res.sort_values('Valor_USD', ascending=False, na_position='last').reset_index(drop=True)
    return res[['Ticker', 'Cantidad', 'Precio_Promedio', 'Precio_Actual', 'Costo_USD',
                'Valor_USD', 'Ganancia_USD', 'Ganancia_%', 'Peso_%']]


def totales(lotes):
    """Costo, valor y ganancia de la cartera, solo con las compras que tienen precio actual."""
    con_precio = lotes[lotes['Precio_Actual'].notna()] if not lotes.empty else lotes
    costo = float(con_precio['Costo_USD'].sum()) if not con_precio.empty else 0.0
    valor = float(con_precio['Valor_USD'].sum()) if not con_precio.empty else 0.0
    ganancia = valor - costo
    return {
        'costo': costo,
        'valor': valor,
        'ganancia': ganancia,
        'ganancia_pct': ganancia / costo * 100 if costo > 0 else np.nan,
        'sin_precio': sorted(set(lotes.loc[lotes['Precio_Actual'].isna(), 'Ticker'])) if not lotes.empty else [],
    }


def simular_compra(lotes, ticker, cantidad, precio, variacion_pct=0.0):
    """Simula comprar `cantidad` de `ticker` a `precio` (el de la fecha de consulta) y que
    después el precio de ese ticker cambie `variacion_pct` %.

    Compara la cartera sin la compra y con la compra, ambas con la misma variación de precio,
    y devuelve un dict con los totales, el peso y el precio promedio del ticker en cada caso."""
    ticker = str(ticker).strip().upper()
    factor = 1 + variacion_pct / 100
    monto = cantidad * precio

    def escenario(base):
        base = base.copy()
        es_ticker = base['Ticker'] == ticker
        # Si el ticker ya está en la cartera, su precio actual pasa a ser el de la simulación
        base.loc[es_ticker, 'Precio_Actual'] = precio * factor
        base['Valor_USD'] = base['Precio_Actual'] * base['Cantidad']
        base['Ganancia_USD'] = base['Valor_USD'] - base['Costo_USD']
        t = totales(base)
        valor_ticker = float(base.loc[es_ticker, 'Valor_USD'].sum())
        cant_ticker = float(base.loc[es_ticker, 'Cantidad'].sum())
        costo_ticker = float(base.loc[es_ticker, 'Costo_USD'].sum())
        t['peso_ticker_pct'] = valor_ticker / t['valor'] * 100 if t['valor'] > 0 else np.nan
        t['cantidad_ticker'] = cant_ticker
        t['precio_promedio_ticker'] = costo_ticker / cant_ticker if cant_ticker > 0 else np.nan
        return t

    compra = pd.DataFrame([{
        'Ticker': ticker, 'Fecha': None, 'Precio_Compra': precio, 'Cantidad': cantidad,
        'Precio_Actual': precio, 'Costo_USD': monto, 'Valor_USD': monto,
        'Ganancia_USD': 0.0, 'Ganancia_%': 0.0,
    }])
    base = lotes if not lotes.empty else compra.iloc[0:0]
    sin_compra = escenario(base)
    con_compra = escenario(pd.concat([base, compra], ignore_index=True))
    return {
        'ticker': ticker,
        'monto': monto,
        'ganancia_compra': monto * (factor - 1),
        'sin_compra': sin_compra,
        'con_compra': con_compra,
        'delta_ganancia': con_compra['ganancia'] - sin_compra['ganancia'],
    }
