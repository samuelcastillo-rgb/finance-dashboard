# tests/test_montecarlo.py
# Datos que Python prepara para la simulación Monte Carlo (la simulación se prueba en Rust:
# cd componentes/montecarlo/rust && cargo test).
import numpy as np
import pandas as pd

from finanzas.montecarlo import DIAS_MINIMOS, preparar_entrada


def precios_de_prueba(dias=400):
    fechas = pd.bdate_range('2024-01-01', periods=dias)
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        'AAA': 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, dias)),
        'BBB': 50 * np.cumprod(1 + rng.normal(0.0002, 0.02, dias)),
    }, index=fechas)


def test_rendimientos_y_pesos():
    precios = precios_de_prueba()
    e = preparar_entrada(precios, {'AAA': 300.0, 'BBB': 100.0})
    assert e['tickers'] == ['AAA', 'BBB']
    assert e['n_dias'] == 399
    assert len(e['rendimientos']) == 399 * 2
    assert e['pesos'] == [0.75, 0.25]
    assert e['valor_inicial'] == 400.0
    # Primera fila = rendimiento del segundo día, en el orden de los tickers.
    esperado = precios.pct_change().iloc[1]
    assert np.allclose(e['rendimientos'][:2], [esperado['AAA'], esperado['BBB']], atol=1e-8)
    assert e['excluidos'] == {}


def test_limite_de_dias():
    e = preparar_entrada(precios_de_prueba(), {'AAA': 1.0}, dias_maximos=300)
    assert e['n_dias'] == 300


def test_tickers_excluidos_y_fechas_comunes():
    precios = precios_de_prueba()
    precios['NUEVO'] = np.nan
    precios.iloc[-100:, precios.columns.get_loc('NUEVO')] = 10.0          # solo 100 días
    precios['HUECOS'] = precios['AAA']
    precios.iloc[5:10, precios.columns.get_loc('HUECOS')] = np.nan        # 5 días sin dato
    e = preparar_entrada(precios, {'AAA': 100.0, 'HUECOS': 100.0, 'NUEVO': 50.0,
                                   'NADA': 10.0, 'SINPRECIO': float('nan')})
    assert e['tickers'] == ['AAA', 'HUECOS']
    assert set(e['excluidos']) == {'NUEVO', 'NADA', 'SINPRECIO'}
    assert 'historia corta' in e['excluidos']['NUEVO']
    # Las fechas sin dato de HUECOS se quitan para todos: 400 - 5 precios -> 394 rendimientos.
    assert e['n_dias'] == 394
    assert e['valor_inicial'] == 200.0          # los excluidos no cuentan


def test_sin_historia_suficiente():
    e = preparar_entrada(precios_de_prueba(DIAS_MINIMOS), {'AAA': 100.0})
    assert e['tickers'] == [] and e['n_dias'] == 0
    assert 'AAA' in e['excluidos']
    assert preparar_entrada(pd.DataFrame(), {'AAA': 100.0})['tickers'] == []
