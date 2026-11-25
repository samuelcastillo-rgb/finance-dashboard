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


def test_dias_de_fin_de_semana_no_excluyen_a_los_demas():
    precios = precios_de_prueba()
    # Un ticker que cotiza todos los días (cripto) agrega fines de semana al índice.
    diario = pd.Series(np.linspace(100, 200, 1120), index=pd.date_range('2023-01-02', periods=1120))
    precios = precios.join(diario.rename('CRIPTO'), how='outer')
    rend, excluidos = frontera.preparar_rendimientos(precios, list(precios.columns), dias=500)
    assert excluidos == {}
    assert set(rend.columns) == {'AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF', 'CRIPTO'}


def test_estimar_contraccion_y_anualizacion():
    rend = frontera.preparar_rendimientos(precios_de_prueba(), ['AAA', 'BBB', 'CCC'])[0]
    mu, sigma, intensidad = frontera.estimar(rend)
    assert 0 <= intensidad <= 1
    assert mu.to_numpy() == pytest.approx(rend.mean().to_numpy() * 252)
    s = np.cov(rend.to_numpy().T, bias=True) * 252
    m = np.trace(s) / 3
    esperado = intensidad * m * np.eye(3) + (1 - intensidad) * s
    assert sigma.to_numpy() == pytest.approx(esperado)


def _resultado_simple():
    """Frontera de juguete (3 puntos) para probar la comparación sin el programa de Rust."""
    return {
        'tasa_libre': 0.04, 'desde': '2023-01-03', 'hasta': '2026-01-01',
        'activos': [{'ticker': t} for t in ('AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF')],
        'min_volatilidad': {'rendimiento': 0.05, 'volatilidad': 0.10, 'sharpe': 0.1, 'pesos': {'AAA': 1.0}},
        'max_sharpe': {'rendimiento': 0.15, 'volatilidad': 0.15, 'sharpe': 0.73, 'pesos': {'BBB': 0.5, 'CCC': 0.5}},
        'frontera': [
            {'rendimiento': 0.05, 'volatilidad': 0.10, 'sharpe': 0.1, 'pesos': {'AAA': 1.0}},
            {'rendimiento': 0.15, 'volatilidad': 0.15, 'sharpe': 0.73, 'pesos': {'BBB': 0.5, 'CCC': 0.5}},
            {'rendimiento': 0.20, 'volatilidad': 0.25, 'sharpe': 0.64, 'pesos': {'FFF': 1.0}},
        ],
    }


def test_comparar_con_optimo():
    resultado = _resultado_simple()
    rend = frontera.rendimientos_de_resultado(precios_de_prueba(), resultado)
    c = frontera.comparar_con_optimo({'AAA': 600.0, 'DDD': 400.0, 'ZZZ': 1000.0}, resultado, rend)
    # ZZZ no tiene precios: queda fuera y el resto se reparte 60/40
    assert c['fuera'] == ['ZZZ'] and c['cobertura'] == pytest.approx(0.5)
    assert c['real']['pesos'] == pytest.approx({'AAA': 0.6, 'DDD': 0.4})
    # Sin ningún ticker en común con el óptimo, los pesos no coinciden en nada
    assert c['coincidencia_pesos'] == pytest.approx(0.0)
    assert c['optimo']['sharpe'] > 0
    assert c['eficiencia_sharpe'] == pytest.approx(c['real']['sharpe'] / c['optimo']['sharpe'])
    assert c['eficiencia_sharpe'] < 1 and c['brecha_sharpe'] > 0
    assert c['tracking_error'] > 0
    assert 0 <= c['p_valor'] <= 1

    # La misma cartera que el óptimo: coincidencia total, eficiencia 1 y sin diferencia
    igual = frontera.comparar_con_optimo({'BBB': 1.0, 'CCC': 1.0}, resultado, rend)
    assert igual['coincidencia_pesos'] == pytest.approx(1.0)
    assert igual['eficiencia_sharpe'] == pytest.approx(1.0)
    assert igual['tracking_error'] == pytest.approx(0.0, abs=1e-12)

    assert frontera.comparar_con_optimo({'ZZZ': 5.0}, resultado, rend) is None


def test_crecimiento_y_niveles():
    rend = pd.DataFrame({'A': [0.1, -0.1], 'B': [0.0, 0.0]}, index=pd.bdate_range('2024-01-02', periods=2))
    serie = frontera.crecimiento(rend, {'A': 0.5, 'B': 0.5})
    assert serie.to_numpy() == pytest.approx([100, 105, 99.75])
    assert frontera.nivel_cercania(0.95) == 'muy cerca'
    assert frontera.nivel_cercania(0.3) == 'lejos'
    assert frontera.nivel_cercania(1.02) == 'en el óptimo o por encima'
    assert frontera.nivel_cercania(np.nan) == 'sin dato'


@pytest.mark.skipif(not frontera.BINARIO.exists(), reason='optimizador sin compilar (cargo build --release)')
def test_python_y_rust_estiman_lo_mismo():
    # La app mide la cartera real con el estimador de Python: tiene que coincidir con el de Rust.
    precios = precios_de_prueba()
    r = frontera.calcular_frontera(precios, list(precios.columns))
    rend = frontera.rendimientos_de_resultado(precios, r)
    assert len(rend) == r['n_dias']
    mu, sigma, intensidad = frontera.estimar(rend)
    assert intensidad == pytest.approx(r['contraccion'], abs=1e-6)   # el JSON guarda 6 decimales
    for a in r['activos']:
        assert mu[a['ticker']] == pytest.approx(a['rendimiento'], abs=1e-6)
        assert np.sqrt(sigma.loc[a['ticker'], a['ticker']]) == pytest.approx(a['volatilidad'], abs=1e-6)
    ms = frontera.evaluar(r['max_sharpe']['pesos'], mu, sigma, r['tasa_libre'])
    assert ms['sharpe'] == pytest.approx(r['max_sharpe']['sharpe'], rel=1e-3)
