# finanzas/comparar.py
# Cálculos de la pestaña "Comparar": rendimiento de 1 año, riesgo y correlación de hasta
# 3 tickers contra el S&P 500. Solo funciones sobre DataFrames de precios (sin red).

import numpy as np
import pandas as pd

INDICE_REFERENCIA = '^GSPC'        # S&P 500
NOMBRE_REFERENCIA = 'S&P 500'
MAX_TICKERS = 3
DIAS_ANIO = 252


def ultimo_anio(precios, tickers):
    """Precios de cierre de los últimos 12 meses (hasta la fecha más reciente con dato) de los
    `tickers` que existan en `precios`. Las fechas sin ningún dato se quitan."""
    columnas = [t for t in dict.fromkeys(tickers) if precios is not None and t in precios.columns]
    if not columnas:
        return pd.DataFrame()
    datos = precios[columnas].sort_index()
    datos.index = pd.to_datetime(datos.index)
    inicio = datos.index.max() - pd.DateOffset(years=1)
    return datos[datos.index >= inicio].dropna(how='all').dropna(axis=1, how='all')


def rendimiento_acumulado(precios):
    """Rendimiento acumulado (%) desde el primer precio disponible de cada columna."""
    return (precios / precios.bfill().iloc[0] - 1) * 100


def metricas_anio(precios, referencia=INDICE_REFERENCIA):
    """Por ticker: rendimiento, volatilidad anualizada, caída máxima (todo en %) y, si está la
    `referencia` en las columnas, beta y correlación contra ella. Un dato que no se puede
    calcular queda en NaN, nunca en 0."""
    filas = {}
    rend = precios.pct_change(fill_method=None)
    for t in precios.columns:
        serie = precios[t].dropna()
        if len(serie) < 2:
            filas[t] = {'Rendimiento_%': np.nan, 'Volatilidad_%': np.nan, 'Caida_Max_%': np.nan,
                        'Beta': np.nan, 'Correlacion_Ref': np.nan}
            continue
        r = rend[t].dropna()
        caida = (serie / serie.cummax() - 1).min() * 100
        fila = {
            'Rendimiento_%': (serie.iloc[-1] / serie.iloc[0] - 1) * 100,
            'Volatilidad_%': r.std() * np.sqrt(DIAS_ANIO) * 100 if len(r) > 1 else np.nan,
            'Caida_Max_%': caida,
            'Beta': np.nan,
            'Correlacion_Ref': np.nan,
        }
        if referencia in precios.columns and t != referencia:
            pares = rend[[t, referencia]].dropna()
            var_ref = pares[referencia].var()
            if len(pares) > 2 and var_ref > 0:
                fila['Beta'] = pares[t].cov(pares[referencia]) / var_ref
                fila['Correlacion_Ref'] = pares[t].corr(pares[referencia])
        elif t == referencia:
            fila['Beta'], fila['Correlacion_Ref'] = 1.0, 1.0
        filas[t] = fila
    return pd.DataFrame.from_dict(filas, orient='index')


def matriz_correlacion(precios):
    """Correlación de Pearson de los rendimientos diarios (solo días en que cotizan todos)."""
    if precios.shape[1] < 2:
        return pd.DataFrame()
    return precios.pct_change(fill_method=None).dropna().corr()


def describir_correlacion(valor):
    """Texto corto para interpretar una correlación."""
    if pd.isna(valor):
        return 'sin dato'
    a = abs(valor)
    fuerza = 'muy alta' if a >= 0.8 else 'alta' if a >= 0.6 else 'moderada' if a >= 0.4 else 'baja' if a >= 0.2 \
        else 'casi nula'
    return fuerza + (' e inversa' if valor < 0 and a >= 0.2 else '')
