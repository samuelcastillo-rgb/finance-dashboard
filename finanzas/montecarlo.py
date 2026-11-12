# finanzas/montecarlo.py
# Prepara los datos de la simulación Monte Carlo del portafolio. La simulación en sí está
# escrita en Rust (componentes/montecarlo/rust) y corre en el navegador como WebAssembly;
# aquí solo se arma la matriz de rendimientos diarios y los pesos que necesita.

import math

import numpy as np
import pandas as pd

DIAS_MINIMOS = 252          # un año de historia como mínimo para incluir un ticker
DIAS_MAXIMOS = 252 * 5      # se usan a lo sumo los últimos 5 años


def preparar_entrada(precios, valores, dias_maximos=DIAS_MAXIMOS):
    """Rendimientos diarios y pesos de los tickers del portafolio.

    `precios`: DataFrame de cierres ajustados (índice = fechas, columnas = tickers).
    `valores`: {ticker: valor actual en USD} de cada posición.

    Devuelve un dict con `tickers`, `rendimientos` (lista plana de n_dias × n_activos,
    un día por fila), `n_dias`, `pesos` (suman 1), `valor_inicial`, `desde`, `hasta` y
    `excluidos` ({ticker: motivo}). Si ningún ticker tiene historia suficiente,
    `tickers` queda vacío.
    """
    excluidos = {}
    con_valor = {}
    for ticker, valor in valores.items():
        if valor is None or not math.isfinite(valor) or valor <= 0:
            excluidos[ticker] = 'sin precio actual'
        else:
            con_valor[ticker] = float(valor)

    incluidos = []
    for ticker in con_valor:
        serie = precios[ticker].dropna() if precios is not None and ticker in precios.columns else None
        if serie is None or serie.empty:
            excluidos[ticker] = 'sin precios históricos'
        elif len(serie) < DIAS_MINIMOS + 1:
            excluidos[ticker] = f'historia corta ({len(serie)} días; se necesita 1 año)'
        else:
            incluidos.append(ticker)

    vacio = {'tickers': [], 'rendimientos': [], 'n_dias': 0, 'pesos': [], 'valor_inicial': 0.0,
             'desde': None, 'hasta': None, 'excluidos': excluidos}
    if not incluidos:
        return vacio

    # Solo fechas en que todos los tickers cotizaron, para conservar la correlación entre ellos.
    comunes = precios[incluidos].dropna().sort_index().tail(dias_maximos + 1)
    rend = comunes.pct_change().iloc[1:]
    rend = rend[np.isfinite(rend).all(axis=1) & (rend > -1).all(axis=1)]
    if len(rend) < DIAS_MINIMOS:
        for ticker in incluidos:
            excluidos[ticker] = 'pocas fechas en común con el resto del portafolio'
        return vacio

    valor_inicial = sum(con_valor[t] for t in incluidos)
    return {
        'tickers': incluidos,
        'rendimientos': [round(float(x), 8) for x in rend.to_numpy().ravel()],
        'n_dias': len(rend),
        'pesos': [con_valor[t] / valor_inicial for t in incluidos],
        'valor_inicial': valor_inicial,
        'desde': pd.Timestamp(rend.index[0]).strftime('%Y-%m-%d'),
        'hasta': pd.Timestamp(rend.index[-1]).strftime('%Y-%m-%d'),
        'excluidos': excluidos,
    }
