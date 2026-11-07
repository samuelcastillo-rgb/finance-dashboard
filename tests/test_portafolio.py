# tests/test_portafolio.py
# Pruebas de finanzas/portafolio.py: limpieza del editor, valoración y simulador de compra.
import pandas as pd
import pytest

from finanzas import portafolio as pf


def _compras():
    return pd.DataFrame({
        'Ticker': [' voo ', 'VOO', 'AAPL', '', 'MSFT'],
        'Fecha': ['2024-01-10', '2025-03-01', '2024-06-01', '2024-01-01', '2024-01-01'],
        'Precio_Compra': [400.0, 500.0, 200.0, 10.0, 0.0],
        'Cantidad': [1.0, 1.0, 5.0, 1.0, 3.0],
    })


def test_limpiar_descarta_filas_incompletas_y_normaliza_tickers():
    limpias = pf.limpiar_posiciones(_compras())
    # Se descartan la fila sin ticker y la de precio 0
    assert limpias['Ticker'].tolist() == ['VOO', 'VOO', 'AAPL']


def test_valoracion_y_resumen_por_ticker():
    lotes = pf.valorar_lotes(_compras(), {'VOO': 600.0, 'AAPL': 180.0})
    resumen = pf.resumir_por_ticker(lotes).set_index('Ticker')
    assert resumen.loc['VOO', 'Cantidad'] == 2
    assert resumen.loc['VOO', 'Precio_Promedio'] == pytest.approx(450.0)
    assert resumen.loc['VOO', 'Ganancia_USD'] == pytest.approx(300.0)
    assert resumen.loc['AAPL', 'Ganancia_USD'] == pytest.approx(-100.0)
    assert resumen['Peso_%'].sum() == pytest.approx(100.0)


def test_totales_ignoran_tickers_sin_precio():
    lotes = pf.valorar_lotes(_compras(), {'VOO': 600.0})
    t = pf.totales(lotes)
    assert t['sin_precio'] == ['AAPL']
    assert t['costo'] == pytest.approx(900.0)
    assert t['ganancia'] == pytest.approx(300.0)


def test_simular_compra_con_variacion():
    lotes = pf.valorar_lotes(_compras(), {'VOO': 600.0, 'AAPL': 180.0})
    sim = pf.simular_compra(lotes, 'aapl', cantidad=5, precio=180.0, variacion_pct=10)
    assert sim['ticker'] == 'AAPL'
    assert sim['monto'] == pytest.approx(900.0)
    assert sim['ganancia_compra'] == pytest.approx(90.0)
    # Con la compra hay 10 AAPL a precio promedio (1000 + 900) / 10
    assert sim['con_compra']['cantidad_ticker'] == 10
    assert sim['con_compra']['precio_promedio_ticker'] == pytest.approx(190.0)


def test_simular_compra_sin_cartera():
    sim = pf.simular_compra(pf.valorar_lotes(None, {}), 'SPY', cantidad=2, precio=100.0)
    assert sim['sin_compra']['valor'] == 0
    assert sim['con_compra']['peso_ticker_pct'] == pytest.approx(100.0)
