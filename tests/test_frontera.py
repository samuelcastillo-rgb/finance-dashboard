# tests/test_frontera.py
# Datos que Python le pasa al optimizador en Rust (optimizador/) y, si el programa está
# compilado (cargo build --release en optimizador/), una corrida completa de punta a punta.
import json

import numpy as np
import pandas as pd
import pytest

from finanzas import frontera


def precios_de_prueba(dias=800, tickers=('AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF')):
    fechas = pd.bdate_range('2023-01-02', periods=dias)
    rng = np.random.default_rng(1)
    comun = rng.normal(0, 0.008, dias)
    return pd.DataFrame({
        t: 100 * np.cumprod(1 + 0.0002 * (i + 1) + (0.4 + 0.2 * i) * comun + rng.normal(0, 0.006 + 0.002 * i, dias))
        for i, t in enumerate(tickers)
    }, index=fechas)


def test_ventana_y_exclusiones():
    precios = precios_de_prueba()
    precios['NUEVO'] = np.nan
    precios.iloc[-100:, precios.columns.get_loc('NUEVO')] = 5.0          # IPO reciente
    precios['HUECO'] = precios['AAA']
    precios.iloc[-20:-15, precios.columns.get_loc('HUECO')] = np.nan     # 5 días sin dato: se acepta
    rend, excluidos = frontera.preparar_rendimientos(precios, ['AAA', 'BBB', 'NUEVO', 'HUECO', 'NADA'], dias=500)
    assert list(rend.columns) == ['AAA', 'BBB', 'HUECO']
    assert set(excluidos) == {'NUEVO', 'NADA'}
    assert 'historia incompleta' in excluidos['NUEVO']
    # 501 precios en la ventana, 5 fechas quitadas por el hueco -> 495 rendimientos
    assert len(rend) == 495
    assert np.isfinite(rend.to_numpy()).all()


def test_texto_de_entrada():
    rend = pd.DataFrame({'AAA': [0.01, -0.02], 'BBB': [0.0, 0.5]})
    texto = frontera.texto_entrada(rend, tasa_libre=0.03, peso_maximo=0.6, puntos=7)
    assert texto == ('tasa_libre 0.03\npeso_maximo 0.6\npuntos 7\ntickers AAA BBB\ndatos\n'
                     '0.01 0\n-0.02 0.5\n')


def test_datos_insuficientes():
    with pytest.raises(RuntimeError, match='datos insuficientes'):
        frontera.calcular_frontera(precios_de_prueba(), ['AAA'])


@pytest.mark.skipif(not frontera.BINARIO.exists(), reason='optimizador sin compilar (cargo build --release)')
def test_de_punta_a_punta_con_rust():
    precios = precios_de_prueba()
    r = frontera.calcular_frontera(precios, list(precios.columns) + ['NADA'])
    assert r['excluidos'] == {'NADA': 'sin precios'}
    assert len(r['activos']) == 6 and r['n_dias'] == frontera.DIAS_VENTANA
    for cartera in [r['max_sharpe'], r['min_volatilidad'], *r['frontera']]:
        assert sum(cartera['pesos'].values()) == pytest.approx(1, abs=1e-5)
        assert max(cartera['pesos'].values()) <= frontera.PESO_MAXIMO + 1e-6
    vols = [c['volatilidad'] for c in r['frontera']]
    assert min(vols) >= r['min_volatilidad']['volatilidad'] - 1e-6
    assert all(c['sharpe'] <= r['max_sharpe']['sharpe'] + 1e-6 for c in r['frontera'])
    json.dumps(r)  # se puede guardar tal cual en la base


@pytest.mark.skipif(not frontera.BINARIO.exists(), reason='optimizador sin compilar (cargo build --release)')
def test_pocos_activos_ajustan_el_peso_maximo():
    # Con 3 activos, 20 % no alcanza para llegar al 100 %: se usa 1/3.
    r = frontera.calcular_frontera(precios_de_prueba(), ['AAA', 'BBB', 'CCC'])
    assert r['peso_maximo'] == pytest.approx(1 / 3, abs=1e-6)
