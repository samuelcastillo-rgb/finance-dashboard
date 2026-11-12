"""Puente en Python para la simulación Monte Carlo escrita en Rust + TypeScript.

El motor está en componentes/montecarlo/rust (Rust, compilado a WebAssembly) y la
interfaz en componentes/montecarlo/src (TypeScript). `npm run build` deja todo en
componentes/montecarlo/dist/montecarlo.js con el .wasm incrustado; aquí solo se registra
ese archivo como componente de Streamlit (st.components.v2), así Streamlit Cloud no
necesita Rust ni Node.
"""
from pathlib import Path

import streamlit as st

_DIST = Path(__file__).resolve().parent.parent / "componentes" / "montecarlo" / "dist"

# El salto de línea inicial es necesario: Streamlit interpreta un texto de una sola
# línea (como el JS minificado) como ruta de archivo en vez de código.
_componente = st.components.v2.component(
    "montecarlo_portafolio",
    js="// simulación Monte Carlo (Rust + WebAssembly)\n" + (_DIST / "montecarlo.js").read_text(encoding="utf-8"),
    css="/* simulación Monte Carlo */\n" + (_DIST / "montecarlo.css").read_text(encoding="utf-8"),
)


def simulacion_montecarlo(entrada, key=None):
    """Muestra la simulación. `entrada` es el dict de finanzas.montecarlo.preparar_entrada
    (con al menos un ticker)."""
    datos = {k: entrada[k] for k in ('tickers', 'rendimientos', 'n_dias', 'pesos', 'valor_inicial',
                                     'desde', 'hasta')}
    return _componente(data=datos, key=key)
