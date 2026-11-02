# almacenamiento.py
# Persistencia de las listas de tickers (ETFs y acciones).
#
# - Si hay una base de datos configurada en los secrets de Streamlit
#   ([connections.postgresql] en .streamlit/secrets.toml o en Streamlit Cloud),
#   los tickers se guardan ahí y sobreviven a reinicios y redespliegues.
# - Si no hay base configurada, se usa portfolio_tickers.json como antes
#   (útil para trabajar en local sin conexión).
#
# La primera vez que la base está vacía, se llena automáticamente con el
# contenido de portfolio_tickers.json, así que no hace falta migrar a mano.

import json
import os

import streamlit as st
from sqlalchemy import text

ARCH_TICKERS = 'portfolio_tickers.json'
NOMBRE_CONEXION = 'postgresql'

# Clave en session_state / JSON  ->  valor de la columna "tipo" en la base
TIPOS = {'etf_list': 'etf', 'stock_list': 'stock'}

SQL_CREAR_TABLA = """
CREATE TABLE IF NOT EXISTS tickers (
    tipo     TEXT    NOT NULL,
    simbolo  TEXT    NOT NULL,
    posicion INTEGER NOT NULL,
    PRIMARY KEY (tipo, simbolo)
)
"""


def hay_base_de_datos():
    """True si los secrets tienen la sección [connections.postgresql]."""
    try:
        return NOMBRE_CONEXION in st.secrets.get('connections', {})
    except Exception:  # no existe ningún secrets.toml
        return False


@st.cache_resource(show_spinner=False)
def _conexion():
    """Abre la conexión una sola vez por servidor y crea la tabla si no existe."""
    conn = st.connection(NOMBRE_CONEXION, type='sql')
    with conn.session as s:
        s.execute(text(SQL_CREAR_TABLA))
        s.commit()
    return conn


# ------------------------------------------------------------------------------
# JSON (modo local / respaldo)
# ------------------------------------------------------------------------------
def _cargar_json(defecto):
    if os.path.exists(ARCH_TICKERS):
        try:
            with open(ARCH_TICKERS, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {clave: list(lista) for clave, lista in defecto.items()}


def _guardar_json(datos):
    with open(ARCH_TICKERS, 'w', encoding='utf-8') as f:
        json.dump(datos, f, indent=4)


# ------------------------------------------------------------------------------
# Base de datos
# ------------------------------------------------------------------------------
def _cargar_db():
    """Devuelve {'etf_list': [...], 'stock_list': [...]} o None si la tabla está vacía."""
    with _conexion().session as s:
        filas = s.execute(text(
            'SELECT tipo, simbolo FROM tickers ORDER BY tipo, posicion'
        )).fetchall()
    if not filas:
        return None
    clave_por_tipo = {tipo: clave for clave, tipo in TIPOS.items()}
    datos = {clave: [] for clave in TIPOS}
    for tipo, simbolo in filas:
        if tipo in clave_por_tipo:
            datos[clave_por_tipo[tipo]].append(simbolo)
    return datos


def _guardar_db(datos):
    """Reemplaza el contenido de la tabla por las listas recibidas (en una transacción)."""
    filas = [
        {'tipo': tipo, 'simbolo': simbolo, 'posicion': i}
        for clave, tipo in TIPOS.items()
        for i, simbolo in enumerate(dict.fromkeys(datos.get(clave, [])))
    ]
    with _conexion().session as s:
        s.execute(text('DELETE FROM tickers'))
        if filas:
            s.execute(text(
                'INSERT INTO tickers (tipo, simbolo, posicion) '
                'VALUES (:tipo, :simbolo, :posicion)'
            ), filas)
        s.commit()


# ------------------------------------------------------------------------------
# API pública usada por app.py
# ------------------------------------------------------------------------------
def cargar_tickers(defecto):
    """Lee los tickers de la base (o del JSON si no hay base configurada)."""
    if not hay_base_de_datos():
        return _cargar_json(defecto)
    try:
        datos = _cargar_db()
        if datos is None:
            # Base recién creada: la llenamos con lo que haya en el JSON del repo.
            datos = _cargar_json(defecto)
            _guardar_db(datos)
        return datos
    except Exception as e:
        st.warning(f"No se pudo leer la base de datos; usando {ARCH_TICKERS}. ({e})")
        return _cargar_json(defecto)


def guardar_tickers(datos):
    """Guarda los tickers en la base (o en el JSON si no hay base configurada)."""
    if not hay_base_de_datos():
        _guardar_json(datos)
        return
    try:
        _guardar_db(datos)
    except Exception as e:
        st.error(f"No se pudo guardar en la base de datos: {e}")
