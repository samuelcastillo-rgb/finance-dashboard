"""Formato de números y colores de variación para tablas y tarjetas."""
import numpy as np
import pandas as pd


def _f(valor, decimales=1, sufijo=''):
    """Formatea un número para mostrarlo; '—' si el dato falta."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return '—'
    if not np.isfinite(v):
        return '—'
    return f'{v:.{decimales}f}{sufijo}'


def _usd(valor, signo=False):
    if valor is None or pd.isna(valor):
        return '—'
    texto = f"${abs(valor):,.2f}"
    if valor < 0:
        return '-' + texto
    return ('+' if signo and valor > 0 else '') + texto


def _pct(valor, signo=True):
    if valor is None or pd.isna(valor):
        return '—'
    return f"{valor:+.2f}%" if signo else f"{valor:.2f}%"


def _color_variacion(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return ''
    if v > 0:
        return 'color: #14B87A; font-weight: 600'
    if v < 0:
        return 'color: #E5484D; font-weight: 600'
    return ''


def _mapear(estilo, funcion, subset):
    # Styler.map existe desde pandas 2.1; antes se llamaba applymap.
    aplicar = getattr(estilo, 'map', None) or estilo.applymap
    return aplicar(funcion, subset=subset)
