# finanzas/frontera.py
# Frontera eficiente de Markowitz: la calcula el programa en Rust de optimizador/
# (binario `frontera`) durante el proceso diario. Aquí se arman los rendimientos que
# recibe, se ejecuta y se lee su resultado (JSON). La app solo lee lo guardado en la base.

import json
import math
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
DIAS_ANIO = 252
CLAVE_COMBINADA = 'combinada'  # ETFs + acciones + tickers del portafolio personal


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
    # Solo días hábiles de la mayoría: un ticker que cotiza en fin de semana (cripto) no debe
    # hacer que todos los demás parezcan tener historia incompleta.
    ventana = ventana[ventana.notna().mean(axis=1) >= 0.5]
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


# ------------------------------------------------------------------------------
# Comparación de una cartera real contra la frontera guardada (la usa la app)
# ------------------------------------------------------------------------------
def estimar(rend):
    """Rendimiento esperado y covarianza anualizados, igual que `estimar` en
    optimizador/src/lib.rs (media histórica y Ledoit-Wolf hacia m·I).

    Devuelve (Series mu, DataFrame sigma, intensidad de la contracción)."""
    x = rend.to_numpy(dtype=float)
    t, n = x.shape
    media = x.mean(axis=0)
    xc = x - media
    s = xc.T @ xc / t
    m = np.trace(s) / n
    d2 = ((s - m * np.eye(n)) ** 2).sum() / n
    s_norma2 = (s ** 2).sum()
    suma = ((xc ** 2).sum(axis=1) ** 2 - 2 * np.einsum('ti,ij,tj->t', xc, s, xc) + s_norma2).sum()
    b2_barra = suma / (t * t) / n
    intensidad = float(np.clip(min(b2_barra, d2) / d2, 0, 1)) if d2 > 0 else 1.0
    sigma = (intensidad * m * np.eye(n) + (1 - intensidad) * s) * DIAS_ANIO
    return (pd.Series(media * DIAS_ANIO, index=rend.columns),
            pd.DataFrame(sigma, index=rend.columns, columns=rend.columns), intensidad)


def rendimientos_de_resultado(precios, resultado):
    """Rearma, a partir de `precios`, los rendimientos diarios con que se calculó `resultado`
    (los mismos activos y fechas, de `desde` a `hasta`)."""
    tickers = [a['ticker'] for a in resultado['activos']]
    datos = precios.copy()
    datos.index = pd.to_datetime(datos.index)
    datos = datos[datos.index <= pd.Timestamp(resultado['hasta'])]
    rend, _ = preparar_rendimientos(datos, tickers)
    return rend[rend.index >= pd.Timestamp(resultado['desde'])]


def evaluar(pesos, mu, sigma, tasa_libre):
    """Rendimiento, volatilidad y Sharpe anuales de una cartera {ticker: peso}."""
    w = pd.Series(pesos, dtype=float).reindex(mu.index).fillna(0.0)
    rendimiento = float(w @ mu)
    volatilidad = float(np.sqrt(max(w @ sigma @ w, 0.0)))
    sharpe = (rendimiento - tasa_libre) / volatilidad if volatilidad > 0 else np.nan
    return {'rendimiento': rendimiento, 'volatilidad': volatilidad, 'sharpe': sharpe}


def _diferencia_sharpe(r_real, r_opt, tasa_libre):
    """Prueba de Jobson-Korkie con la corrección de Memmel (2003): ¿la diferencia entre los
    Sharpe de dos carteras sobre los mismos días es mayor que el ruido? Devuelve (z, p)."""
    exceso = tasa_libre / DIAS_ANIO
    a, b = r_real - exceso, r_opt - exceso
    if a.std() == 0 or b.std() == 0 or len(a) < 30:
        return np.nan, np.nan
    sa, sb = a.mean() / a.std(), b.mean() / b.std()
    rho = float(np.corrcoef(a, b)[0, 1])
    varianza = (2 * (1 - rho) + 0.5 * (sa ** 2 + sb ** 2 - 2 * sa * sb * rho ** 2)) / len(a)
    if varianza <= 0:
        return np.nan, np.nan
    z = (sb - sa) / math.sqrt(varianza)
    return z, math.erfc(abs(z) / math.sqrt(2))


def comparar_con_optimo(valores, resultado, rend):
    """Qué tan lejos está una cartera real del máximo Sharpe de `resultado`.

    `valores` = {ticker: valor actual en USD}; `rend` = rendimientos_de_resultado(...).
    La cartera real se mide con los mismos datos, ventana y estimador que la frontera.
    Los tickers sin historia suficiente quedan fuera y los pesos se reparten entre el resto."""
    valores = {t: float(v) for t, v in valores.items() if v is not None and np.isfinite(v) and v > 0}
    total = sum(valores.values())
    dentro = {t: v for t, v in valores.items() if t in rend.columns}
    if total <= 0 or not dentro:
        return None
    suma = sum(dentro.values())
    pesos_real = {t: v / suma for t, v in dentro.items()}
    tasa = resultado['tasa_libre']
    mu, sigma, _ = estimar(rend)

    ms = resultado['max_sharpe']
    real = evaluar(pesos_real, mu, sigma, tasa)
    optimo = evaluar(ms['pesos'], mu, sigma, tasa)
    real['pesos'], optimo['pesos'] = pesos_real, dict(ms['pesos'])

    frontera = sorted(resultado['frontera'], key=lambda c: c['volatilidad'])
    vols = np.array([c['volatilidad'] for c in frontera])
    rends = np.array([c['rendimiento'] for c in frontera])
    mv = resultado['min_volatilidad']
    # Rendimiento de la frontera con la misma volatilidad y volatilidad mínima para el mismo
    # rendimiento (la frontera eficiente sube de forma monótona desde la mínima volatilidad).
    rend_misma_vol = float(np.interp(real['volatilidad'], vols, rends))
    if real['rendimiento'] > rends.max():
        vol_mismo_rend = None
    elif real['rendimiento'] <= mv['rendimiento']:
        vol_mismo_rend = mv['volatilidad']
    else:
        vol_mismo_rend = float(np.interp(real['rendimiento'], rends, vols))
    misma_vol = min(frontera, key=lambda c: abs(c['volatilidad'] - real['volatilidad']))

    w_real = pd.Series(pesos_real).reindex(mu.index).fillna(0.0)
    w_opt = pd.Series(ms['pesos'], dtype=float).reindex(mu.index).fillna(0.0)
    d = w_real - w_opt
    z, p = _diferencia_sharpe(rend.to_numpy() @ w_real.to_numpy(), rend.to_numpy() @ w_opt.to_numpy(), tasa)

    return {
        'real': real,
        'optimo': optimo,
        'misma_volatilidad': misma_vol,
        'eficiencia_sharpe': real['sharpe'] / optimo['sharpe'] if optimo['sharpe'] > 0 else np.nan,
        'brecha_sharpe': optimo['sharpe'] - real['sharpe'],
        'rendimiento_perdido': rend_misma_vol - real['rendimiento'],
        'riesgo_extra': None if vol_mismo_rend is None else real['volatilidad'] - vol_mismo_rend,
        'debajo_min_volatilidad': real['volatilidad'] < mv['volatilidad'],
        'coincidencia_pesos': 1 - 0.5 * float(d.abs().sum()),
        'tracking_error': float(np.sqrt(max(d @ sigma @ d, 0.0))),
        'z': z, 'p_valor': p,
        'cobertura': suma / total,
        'fuera': sorted(set(valores) - set(dentro)),
        'n_dias': len(rend),
    }


def nivel_cercania(eficiencia):
    """Texto para la eficiencia de Sharpe (Sharpe real / Sharpe máximo)."""
    if eficiencia is None or pd.isna(eficiencia):
        return 'sin dato'
    if eficiencia >= 1:
        return 'en el óptimo o por encima'
    return ('muy cerca' if eficiencia >= 0.9 else 'cerca' if eficiencia >= 0.75
            else 'a media distancia' if eficiencia >= 0.5 else 'lejos' if eficiencia >= 0.25 else 'muy lejos')


def crecimiento(rend, pesos, base=100.0):
    """Valor de `base` invertido con pesos constantes (rebalanceo diario) sobre `rend`."""
    w = pd.Series(pesos, dtype=float).reindex(rend.columns).fillna(0.0)
    serie = (1 + rend @ w).cumprod() * base
    inicio = pd.Series([base], index=[rend.index[0] - pd.Timedelta(days=1)])
    return pd.concat([inicio, serie])
