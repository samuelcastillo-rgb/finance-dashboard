# finanzas/frontera.py
# Frontera eficiente de Markowitz: la calcula el programa en Rust de optimizador/
# (binario `frontera`) durante el proceso diario. Aquí se arman los rendimientos que
# recibe, se ejecuta y se lee su resultado (JSON). La app solo lee lo guardado en la base.

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

BINARIO = Path(__file__).resolve().parent.parent / 'optimizador' / 'target' / 'release' / 'frontera'

DIAS_VENTANA = 252 * 3      # últimos 3 años
COBERTURA_MINIMA = 0.95     # un ticker necesita precio en el 95 % de esos días
TASA_LIBRE = 0.04           # la misma que usan los ratios de Sharpe y Sortino
PESO_MAXIMO = 0.20          # ningún activo pesa más del 20 %
PUNTOS = 40


def preparar_rendimientos(precios, tickers, dias=DIAS_VENTANA):
    """Rendimientos diarios de los últimos `dias` días hábiles, solo con los tickers que
    tienen precio en casi todos ellos y solo en las fechas en que todos cotizaron.

    Devuelve (DataFrame de rendimientos, {ticker: motivo de exclusión})."""
    excluidos = {}
    disponibles = [t for t in dict.fromkeys(tickers) if precios is not None and t in precios.columns]
    for t in dict.fromkeys(tickers):
        if t not in disponibles:
            excluidos[t] = 'sin precios'
    if not disponibles:
        return pd.DataFrame(), excluidos
    ventana = precios[disponibles].sort_index().iloc[-(dias + 1):]
    ventana = ventana.dropna(how='all')
    cobertura = ventana.notna().mean()
    incluidos = [t for t in disponibles if cobertura[t] >= COBERTURA_MINIMA]
    for t in disponibles:
        if t not in incluidos:
            excluidos[t] = f'historia incompleta ({cobertura[t]:.0%} de los últimos {dias} días)'
    rend = ventana[incluidos].dropna().pct_change().iloc[1:]
    rend = rend[np.isfinite(rend).all(axis=1)]
    return rend, excluidos


def texto_entrada(rend, tasa_libre=TASA_LIBRE, peso_maximo=PESO_MAXIMO, puntos=PUNTOS):
    """Formato que lee el programa de Rust (ver leer_entrada en optimizador/src/lib.rs)."""
    lineas = [f'tasa_libre {tasa_libre}', f'peso_maximo {peso_maximo}', f'puntos {puntos}',
              'tickers ' + ' '.join(rend.columns), 'datos']
    lineas += [' '.join(f'{x:.10g}' for x in fila) for fila in rend.to_numpy()]
    return '\n'.join(lineas) + '\n'


def calcular_frontera(precios, tickers, binario=BINARIO, peso_maximo=PESO_MAXIMO):
    """Ejecuta el optimizador y devuelve su resultado (dict) con, además, `desde`, `hasta`
    y `excluidos`. Lanza RuntimeError con el mensaje del programa si algo falla."""
    rend, excluidos = preparar_rendimientos(precios, tickers)
    if rend.shape[1] < 2 or len(rend) < 30:
        raise RuntimeError(f'datos insuficientes ({rend.shape[1]} tickers con historia completa)')
    # Con pocos activos, el peso máximo tiene que permitir llegar al 100 %.
    peso_maximo = max(peso_maximo, 1 / rend.shape[1])
    salida = subprocess.run([str(binario)], input=texto_entrada(rend, peso_maximo=peso_maximo),
                            capture_output=True, text=True, timeout=600)
    if salida.returncode != 0:
        raise RuntimeError(salida.stderr.strip() or f'el optimizador terminó con código {salida.returncode}')
    resultado = json.loads(salida.stdout)
    resultado['desde'] = pd.Timestamp(rend.index[0]).strftime('%Y-%m-%d')
    resultado['hasta'] = pd.Timestamp(rend.index[-1]).strftime('%Y-%m-%d')
    resultado['excluidos'] = excluidos
    return resultado
