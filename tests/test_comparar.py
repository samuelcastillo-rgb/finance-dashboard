# tests/test_comparar.py
# Cálculos de la pestaña "Comparar" (sin red).
import numpy as np
import pandas as pd
import pytest

from finanzas import comparar as cp


def precios(dias=400):
    fechas = pd.bdate_range('2025-01-01', periods=dias)
    rng = np.random.default_rng(3)
    mercado = rng.normal(0.0004, 0.01, dias)
    return pd.DataFrame({
        '^GSPC': 5000 * np.cumprod(1 + mercado),
        'DOBLE': 100 * np.cumprod(1 + 2 * mercado),                       # beta 2, correlación 1
        'PROPIO': 50 * np.cumprod(1 + rng.normal(0.0003, 0.01, dias)),    # independiente
    }, index=fechas)


def test_ultimo_anio():
    p = precios()
    anio = cp.ultimo_anio(p, ['DOBLE', 'NO_EXISTE', '^GSPC'])
    assert list(anio.columns) == ['DOBLE', '^GSPC']
    assert anio.index.min() >= p.index.max() - pd.DateOffset(years=1)
    assert anio.index.max() == p.index.max()
    assert cp.ultimo_anio(p, ['NO_EXISTE']).empty


def test_rendimiento_acumulado_empieza_en_cero():
    acum = cp.rendimiento_acumulado(cp.ultimo_anio(precios(), ['DOBLE', 'PROPIO']))
    assert (acum.iloc[0] == 0).all()


def test_beta_y_correlacion():
    m = cp.metricas_anio(cp.ultimo_anio(precios(), ['DOBLE', 'PROPIO', '^GSPC']))
    assert m.loc['DOBLE', 'Beta'] == pytest.approx(2, abs=1e-9)
    assert m.loc['DOBLE', 'Correlacion_Ref'] == pytest.approx(1, abs=1e-9)
    assert abs(m.loc['PROPIO', 'Correlacion_Ref']) < 0.2
    assert m.loc['^GSPC', 'Beta'] == 1.0
    assert (m['Caida_Max_%'] <= 0).all()
    assert m.loc['DOBLE', 'Volatilidad_%'] == pytest.approx(2 * m.loc['^GSPC', 'Volatilidad_%'], rel=1e-6)


def test_sin_referencia_ni_datos_queda_nan():
    p = cp.ultimo_anio(precios(), ['DOBLE', 'PROPIO'])
    p['VACIO'] = np.nan
    p.iloc[-1, p.columns.get_loc('VACIO')] = 10.0          # un solo precio: no se puede medir
    m = cp.metricas_anio(p)
    assert m['Beta'].isna().all()
    assert m.loc['VACIO'].isna().all()


def test_matriz_y_descripcion():
    c = cp.matriz_correlacion(cp.ultimo_anio(precios(), ['DOBLE', 'PROPIO', '^GSPC']))
    assert c.shape == (3, 3)
    assert c.loc['DOBLE', '^GSPC'] == pytest.approx(1, abs=1e-9)
    assert cp.matriz_correlacion(cp.ultimo_anio(precios(), ['DOBLE'])).empty
    assert cp.describir_correlacion(0.9) == 'muy alta'
    assert cp.describir_correlacion(-0.5) == 'moderada e inversa'
    assert cp.describir_correlacion(0.1) == 'casi nula'
    assert cp.describir_correlacion(np.nan) == 'sin dato'
