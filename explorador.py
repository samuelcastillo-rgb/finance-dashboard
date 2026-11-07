"""Puente en Python para el explorador de métricas escrito en TypeScript.

El código fuente está en componentes/explorador/src (TypeScript + CSS) y se compila
a componentes/explorador/dist con `npm run build`. Aquí solo leemos esos archivos
compilados y los registramos como componente de Streamlit (st.components.v2), así
Streamlit Cloud no necesita Node: basta con que dist/ esté en el repositorio.
"""
import math
from pathlib import Path

import pandas as pd
import streamlit as st

_DIST = Path(__file__).parent / "componentes" / "explorador" / "dist"

# El salto de línea inicial es necesario: Streamlit interpreta un texto de una sola
# línea (como el JS minificado) como ruta de archivo en vez de código.
_componente = st.components.v2.component(
    "explorador_metricas",
    js="// explorador de métricas\n" + (_DIST / "explorador.js").read_text(encoding="utf-8"),
    css="/* explorador de métricas */\n" + (_DIST / "explorador.css").read_text(encoding="utf-8"),
)


def _limpiar(valor):
    """Convierte NaN/inf y tipos de numpy a algo que JSON entienda."""
    if valor is None:
        return None
    if isinstance(valor, str):
        return valor
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    return numero if math.isfinite(numero) else None


def explorador_metricas(df, columnas, id_col='Ticker', nombre_col=None, inicial=None, key=None):
    """Muestra el explorador interactivo.

    columnas: lista de tuplas (id, etiqueta, tipo, sufijo, decimales) con tipo 'num' o 'cat'.
    Solo se envían las columnas que existen en df.
    inicial: dict opcional con la vista de arranque (tipo, x, y, color, tamano).
    """
    definiciones = []
    for id_columna, etiqueta, tipo, sufijo, decimales in columnas:
        if id_columna in df.columns:
            definiciones.append({'id': id_columna, 'etiqueta': etiqueta, 'tipo': tipo,
                                 'sufijo': sufijo, 'decimales': decimales})
    ids = [d['id'] for d in definiciones]
    if nombre_col and nombre_col in df.columns and nombre_col not in ids:
        ids.append(nombre_col)

    tabla = df[ids].copy()
    for d in definiciones:
        if d['tipo'] == 'num':
            tabla[d['id']] = pd.to_numeric(tabla[d['id']], errors='coerce')
    filas = [{k: _limpiar(v) for k, v in fila.items()} for fila in tabla.to_dict(orient='records')]

    return _componente(
        key=key,
        data={'columnas': definiciones, 'filas': filas, 'id_col': id_col,
              'nombre_col': nombre_col, 'inicial': inicial or {}},
    )
