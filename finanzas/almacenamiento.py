# finanzas/almacenamiento.py
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
#
# También guarda los metadatos de cada ticker (nombre, categoría, sector...).
# Yahoo suele bloquear `info` desde servidores en la nube, así que cada vez que
# la app (o scripts/actualizar_metadatos.py) los obtiene bien en tu computadora, quedan
# en la base y la app en línea los usa como respaldo.
#
# Por último, guarda los precios de cierre diarios (tabla precios_diarios) y los
# registros de cada ticker con sus fundamentales (tabla metricas), que llena el
# proceso diario scripts/actualizar_datos.py (GitHub Action). La app los lee de aquí en vez
# de consultar a Yahoo en cada visita.
#
# También guarda las compras del portafolio personal (tabla posiciones). Estas
# solo se guardan en la base, nunca en un archivo del repositorio (que es público).

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import bindparam, text

# Rutas absolutas: funcionan sin importar desde qué carpeta se ejecute el código.
CARPETA_DATOS = Path(__file__).resolve().parent.parent / 'datos'
ARCH_TICKERS = CARPETA_DATOS / 'portfolio_tickers.json'
ARCH_METADATOS = CARPETA_DATOS / 'metadata_cache.json'
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

SQL_CREAR_TABLA_METADATOS = """
CREATE TABLE IF NOT EXISTS metadatos (
    tipo     TEXT NOT NULL,
    simbolo  TEXT NOT NULL,
    datos    TEXT NOT NULL,
    PRIMARY KEY (tipo, simbolo)
)
"""

SQL_CREAR_TABLA_PRECIOS = """
CREATE TABLE IF NOT EXISTS precios_diarios (
    simbolo  TEXT             NOT NULL,
    fecha    DATE             NOT NULL,
    cierre   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (simbolo, fecha)
)
"""

SQL_CREAR_TABLA_METRICAS = """
CREATE TABLE IF NOT EXISTS metricas (
    tipo        TEXT      NOT NULL,
    simbolo     TEXT      NOT NULL,
    datos       TEXT      NOT NULL,
    actualizado TIMESTAMP NOT NULL,
    PRIMARY KEY (tipo, simbolo)
)
"""

SQL_GUARDAR_METRICA = """
INSERT INTO metricas (tipo, simbolo, datos, actualizado)
VALUES (:tipo, :simbolo, :datos, :actualizado)
ON CONFLICT (tipo, simbolo) DO UPDATE
SET datos = excluded.datos, actualizado = excluded.actualizado
"""

SQL_CREAR_TABLA_POSICIONES = """
CREATE TABLE IF NOT EXISTS posiciones (
    orden    INTEGER          NOT NULL PRIMARY KEY,
    simbolo  TEXT             NOT NULL,
    fecha    DATE,
    precio   DOUBLE PRECISION NOT NULL,
    cantidad DOUBLE PRECISION NOT NULL
)
"""

SQL_GUARDAR_METADATO = """
INSERT INTO metadatos (tipo, simbolo, datos) VALUES (:tipo, :simbolo, :datos)
ON CONFLICT (tipo, simbolo) DO UPDATE SET datos = excluded.datos
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
        s.execute(text(SQL_CREAR_TABLA_METADATOS))
        s.execute(text(SQL_CREAR_TABLA_PRECIOS))
        s.execute(text(SQL_CREAR_TABLA_METRICAS))
        s.execute(text(SQL_CREAR_TABLA_POSICIONES))
        s.commit()
    return conn


# ------------------------------------------------------------------------------
# JSON (modo local / respaldo)
# ------------------------------------------------------------------------------
def _cargar_json(defecto):
    if os.path.exists(ARCH_TICKERS):
        try:
            with open(ARCH_TICKERS, encoding='utf-8') as f:
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
# API pública usada por la app (dashboard/) y los scripts
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
        st.warning(f"No se pudo leer la base de datos; usando {ARCH_TICKERS.name}. ({e})")
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


# ------------------------------------------------------------------------------
# Metadatos (nombre, categoría, sector...) por ticker
# ------------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _cargar_metadatos_db():
    with _conexion().session as s:
        filas = s.execute(text('SELECT tipo, simbolo, datos FROM metadatos')).fetchall()
    clave_por_tipo = {tipo: clave for clave, tipo in TIPOS.items()}
    datos = {clave: {} for clave in TIPOS}
    for tipo, simbolo, texto in filas:
        if tipo in clave_por_tipo:
            datos[clave_por_tipo[tipo]][simbolo] = json.loads(texto)
    return datos


def cargar_metadatos():
    """metadata_cache.json + lo guardado en la base (la base tiene prioridad)."""
    datos = {clave: {} for clave in TIPOS}
    try:
        with open(ARCH_METADATOS, encoding='utf-8') as f:
            archivo = json.load(f)
        for clave in TIPOS:
            datos[clave].update(archivo.get(clave, {}))
    except Exception:
        pass
    if hay_base_de_datos():
        try:
            for clave, por_simbolo in _cargar_metadatos_db().items():
                datos[clave].update(por_simbolo)
        except Exception:
            pass  # sin base: seguimos solo con el JSON
    return datos


def guardar_metadatos(metadatos):
    """Guarda {'etf_list': {simbolo: {...}}, 'stock_list': {...}} en la base.
    Sin base configurada no hace nada (en local se usa metadata_cache.json)."""
    if not hay_base_de_datos():
        return
    filas = [
        {'tipo': tipo, 'simbolo': simbolo, 'datos': json.dumps(valores, ensure_ascii=False)}
        for clave, tipo in TIPOS.items()
        for simbolo, valores in metadatos.get(clave, {}).items()
    ]
    if not filas:
        return
    try:
        with _conexion().session as s:
            s.execute(text(SQL_GUARDAR_METADATO), filas)
            s.commit()
    except Exception:
        pass  # no es crítico: el dashboard sigue funcionando sin guardar el respaldo


def guardar_metadato(clave, simbolo, valores):
    """Atajo para guardar los metadatos de un solo ticker (clave = 'etf_list' o 'stock_list')."""
    guardar_metadatos({clave: {simbolo: valores}})


# ------------------------------------------------------------------------------
# Precios de cierre diarios
# ------------------------------------------------------------------------------
def guardar_precios(precios):
    """Reemplaza la tabla precios_diarios por `precios` (DataFrame con fechas como índice
    y un ticker por columna, como lo devuelve yf.download(...)['Close']).

    Se reemplaza todo en vez de agregar solo los días nuevos porque los precios ajustados
    (auto_adjust=True) cambian hacia atrás cada vez que hay dividendos o splits.
    Devuelve el número de filas guardadas."""
    largo = precios.stack().dropna()
    filas = [
        {'simbolo': str(simbolo), 'fecha': fecha.date(), 'cierre': float(cierre)}
        for (fecha, simbolo), cierre in largo.items()
    ]
    if not filas:
        return 0
    with _conexion().session as s:
        s.execute(text('DELETE FROM precios_diarios'))
        s.execute(text(
            'INSERT INTO precios_diarios (simbolo, fecha, cierre) '
            'VALUES (:simbolo, :fecha, :cierre)'
        ), filas)
        s.commit()
    return len(filas)


def cargar_precios(simbolos):
    """Precios de cierre guardados para `simbolos`: DataFrame con fechas como índice ('Date')
    y un ticker por columna, igual que yf.download(...)['Close']. Vacío si no hay base o datos."""
    if not simbolos or not hay_base_de_datos():
        return pd.DataFrame()
    consulta = text(
        'SELECT fecha, simbolo, cierre FROM precios_diarios WHERE simbolo IN :simbolos'
    ).bindparams(bindparam('simbolos', expanding=True))
    try:
        with _conexion().session as s:
            filas = s.execute(consulta, {'simbolos': list(simbolos)}).fetchall()
    except Exception:
        return pd.DataFrame()
    if not filas:
        return pd.DataFrame()
    largo = pd.DataFrame(filas, columns=['fecha', 'simbolo', 'cierre'])
    largo['fecha'] = pd.to_datetime(largo['fecha'])
    precios = largo.pivot(index='fecha', columns='simbolo', values='cierre').sort_index()
    precios.index.name = 'Date'
    precios.columns.name = None
    return precios


# ------------------------------------------------------------------------------
# Métricas por ticker (registro con fundamentales que calcula datos_mercado.py)
# ------------------------------------------------------------------------------
def _a_json(valor):
    """Convierte tipos de numpy/pandas a tipos que json entiende."""
    if hasattr(valor, 'item'):
        return valor.item()
    if hasattr(valor, 'isoformat'):
        return valor.isoformat()
    return str(valor)


def guardar_metricas(clave, registros, actualizado):
    """Guarda {simbolo: registro} (clave = 'etf_list' o 'stock_list'). Los tickers que no
    vienen en `registros` conservan su registro anterior. Devuelve el número guardado."""
    filas = [
        {'tipo': TIPOS[clave], 'simbolo': simbolo,
         'datos': json.dumps(registro, ensure_ascii=False, default=_a_json),
         'actualizado': actualizado}
        for simbolo, registro in registros.items()
    ]
    if not filas:
        return 0
    with _conexion().session as s:
        s.execute(text(SQL_GUARDAR_METRICA), filas)
        s.commit()
    return len(filas)


def cargar_metricas():
    """({'etf_list': {simbolo: registro}, 'stock_list': {...}}, fecha_mas_reciente).
    Sin base o con error devuelve listas vacías y None (la app consulta a Yahoo en vivo)."""
    vacio = {clave: {} for clave in TIPOS}
    if not hay_base_de_datos():
        return vacio, None
    try:
        with _conexion().session as s:
            filas = s.execute(text(
                'SELECT tipo, simbolo, datos, actualizado FROM metricas'
            )).fetchall()
    except Exception:
        return vacio, None
    clave_por_tipo = {tipo: clave for clave, tipo in TIPOS.items()}
    datos = {clave: {} for clave in TIPOS}
    fecha = None
    for tipo, simbolo, texto, actualizado in filas:
        if tipo in clave_por_tipo:
            datos[clave_por_tipo[tipo]][simbolo] = json.loads(texto)
            if actualizado is not None and (fecha is None or actualizado > fecha):
                fecha = actualizado
    return datos, fecha


# ------------------------------------------------------------------------------
# Portafolio personal (compras: ticker, fecha, precio, cantidad)
# ------------------------------------------------------------------------------
def cargar_posiciones():
    """DataFrame con columnas Ticker, Fecha, Precio_Compra, Cantidad, o None si no hay base
    configurada (en ese caso la app las guarda solo mientras dure la sesión)."""
    if not hay_base_de_datos():
        return None
    with _conexion().session as s:
        filas = s.execute(text(
            'SELECT simbolo, fecha, precio, cantidad FROM posiciones ORDER BY orden'
        )).fetchall()
    return pd.DataFrame([tuple(f) for f in filas],
                        columns=['Ticker', 'Fecha', 'Precio_Compra', 'Cantidad'])


def guardar_posiciones(posiciones):
    """Reemplaza todas las compras guardadas por `posiciones` (en una transacción)."""
    filas = [
        {'orden': i, 'simbolo': str(f.Ticker), 'fecha': f.Fecha if pd.notna(f.Fecha) else None,
         'precio': float(f.Precio_Compra), 'cantidad': float(f.Cantidad)}
        for i, f in enumerate(posiciones.itertuples(index=False))
    ]
    with _conexion().session as s:
        s.execute(text('DELETE FROM posiciones'))
        if filas:
            s.execute(text(
                'INSERT INTO posiciones (orden, simbolo, fecha, precio, cantidad) '
                'VALUES (:orden, :simbolo, :fecha, :precio, :cantidad)'
            ), filas)
        s.commit()


def tickers_de_posiciones():
    """Tickers del portafolio personal (para que el proceso diario guarde sus precios)."""
    try:
        posiciones = cargar_posiciones()
    except Exception:
        return []
    if posiciones is None or posiciones.empty:
        return []
    return list(dict.fromkeys(posiciones['Ticker'].astype(str)))
