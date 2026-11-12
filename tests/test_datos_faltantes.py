# tests/test_datos_faltantes.py
# Validación SIN red de cómo stock_ratios.py y etf_ratios.py tratan los datos faltantes:
# un dato que Yahoo Finance no entrega debe salir como None ("sin dato"), nunca como 0.
#
# Uso:  pytest   (o solo este archivo: pytest tests/test_datos_faltantes.py -v)
from unittest.mock import patch

import pandas as pd

from finanzas import etf_ratios as er
from finanzas import stock_ratios as sr


class FalsaAccion:
    """Imita lo mínimo de yf.Ticker que usa get_stock_fundamentals."""

    def __init__(self, info, financials=None, balance_sheet=None):
        self._info = info
        self.financials = financials if financials is not None else pd.DataFrame()
        self.balance_sheet = balance_sheet if balance_sheet is not None else pd.DataFrame()

    @property
    def info(self):
        if isinstance(self._info, Exception):
            raise self._info
        return self._info


def estado(filas):
    """Estado financiero de un solo año: {'EBIT': 1000, ...} -> DataFrame como el de yfinance."""
    return pd.DataFrame({pd.Timestamp('2025-12-31'): list(filas.values())}, index=list(filas.keys()))


def estado_dos_anios(filas):
    """{'Fila': (año actual, año anterior)} -> DataFrame con el año más reciente primero."""
    return pd.DataFrame({pd.Timestamp('2025-12-31'): [v[0] for v in filas.values()],
                         pd.Timestamp('2024-12-31'): [v[1] for v in filas.values()]},
                        index=list(filas.keys()))


def comprobar(nombre, obtenido, esperado):
    assert obtenido == esperado, f'{nombre}: esperado {esperado!r}, obtenido {obtenido!r}'


METRICAS = ['ROA_%', 'ROE_%', 'ROIC_%', 'Debt_to_Equity', 'Net_Margin_%', 'EBITDA_MUSD']


def test_empresa_con_todos_los_datos():
    """Empresa con todos los datos (debe conservar el cálculo original)"""
    completa = FalsaAccion(
        {'returnOnAssets': 0.10, 'returnOnEquity': 0.25, 'profitMargins': 0.20,
         'debtToEquity': 25.0, 'ebitda': 1.5e9},
        financials=estado({'EBIT': 1000, 'Tax Provision': 210, 'Pretax Income': 1000}),
        balance_sheet=estado({'Total Debt': 500, 'Stockholders Equity': 2000, 'Cash And Cash Equivalents': 300}))
    r = sr.get_stock_fundamentals(completa)
    # NOPAT = 1000 * (1 - 0.21) = 790 ; capital = (500 + 2000) - 300 = 2200 ; ROIC = 35.91 %
    comprobar('ROIC_%', r['ROIC_%'], 35.91)
    comprobar('ROA_%', r['ROA_%'], 10.0)
    comprobar('ROE_%', r['ROE_%'], 25.0)
    comprobar('Net_Margin_%', r['Net_Margin_%'], 20.0)
    comprobar('Debt_to_Equity', r['Debt_to_Equity'], 0.25)
    comprobar('EBITDA_MUSD', r['EBITDA_MUSD'], 1500.0)


def test_banco_sin_ebit_ni_ebitda():
    """Banco: Yahoo no entrega EBIT ni EBITDA (deben ser None, no 0)"""
    banco = FalsaAccion(
        {'returnOnAssets': 0.011, 'returnOnEquity': 0.12, 'profitMargins': 0.30, 'debtToEquity': 100.0},
        financials=estado({'Pretax Income': 5e9}),
        balance_sheet=estado({'Stockholders Equity': 5e10}))
    r = sr.get_stock_fundamentals(banco)
    comprobar('ROIC_%', r['ROIC_%'], None)
    comprobar('EBITDA_MUSD', r['EBITDA_MUSD'], None)
    comprobar('ROE_%', r['ROE_%'], 12.0)
    comprobar('Debt_to_Equity', r['Debt_to_Equity'], 1.0)


def test_deuda_equity_derivada_del_balance():
    """Deuda/Equity: derivada del balance cuando Yahoo no la trae"""
    sin_de = {'returnOnAssets': 0.1, 'returnOnEquity': 0.1, 'profitMargins': 0.1, 'ebitda': 1e9}
    r = sr.get_stock_fundamentals(FalsaAccion(
        sin_de, balance_sheet=estado({'Total Debt': 300, 'Stockholders Equity': 1500})))
    comprobar('con deuda (300 / 1500)', r['Debt_to_Equity'], 0.2)
    r = sr.get_stock_fundamentals(FalsaAccion(
        sin_de, balance_sheet=estado({'Total Debt': 0, 'Stockholders Equity': 1500})))
    comprobar('sin deuda: el 0 es un dato real', r['Debt_to_Equity'], 0.0)
    r = sr.get_stock_fundamentals(FalsaAccion(sin_de))
    comprobar('imposible de determinar', r['Debt_to_Equity'], None)


def test_capital_invertido_negativo():
    """Capital invertido <= 0: ROIC no es interpretable (comportamiento actual: None)"""
    r = sr.get_stock_fundamentals(FalsaAccion(
        {'returnOnAssets': 0.1, 'returnOnEquity': 0.1, 'profitMargins': 0.1, 'debtToEquity': 10.0},
        financials=estado({'EBIT': 100, 'Tax Provision': 20, 'Pretax Income': 100}),
        balance_sheet=estado({'Total Debt': 100, 'Stockholders Equity': -500, 'Cash And Cash Equivalents': 50})))
    comprobar('ROIC_%', r['ROIC_%'], None)


def test_yahoo_falla_por_completo():
    """Yahoo falla por completo: todas las métricas None"""
    r = sr.get_stock_fundamentals(FalsaAccion(RuntimeError('sin datos')))
    comprobar('métricas', [r[m] for m in METRICAS], [None] * len(METRICAS))


def test_descarga_de_precios_fallida():
    """Descarga de precios fallida: None, no 0"""
    with patch.object(sr.yf, 'download', side_effect=RuntimeError('sin red')):
        r = sr.calculate_stock_performance('XXXX')
    comprobar('acciones', r, {'CAGR_%': None, 'Volatilidad_%': None, 'Sortino': None})
    with patch.object(er.yf, 'download', side_effect=RuntimeError('sin red')):
        r = er.calculate_etf_performance('XXXX')
    comprobar('ETFs', r, {'CAGR_%': None, 'Volatilidad_%': None, 'Sharpe': None,
                          'Sortino': None, 'Max_Drawdown_%': None})


def test_info_bloqueada_con_estados_financieros():
    """Yahoo bloquea info (p. ej. en la nube) pero sí entrega los estados financieros"""
    r = sr.get_stock_fundamentals(FalsaAccion(
        RuntimeError('429 Too Many Requests'),
        financials=estado({'EBIT': 1000, 'Tax Provision': 210, 'Pretax Income': 1000,
                           'Net Income': 790, 'Total Revenue': 4000, 'EBITDA': 1500e6}),
        balance_sheet=estado({'Total Debt': 500, 'Stockholders Equity': 2000,
                              'Cash And Cash Equivalents': 300, 'Total Assets': 7900})))
    # Con ventas de 4000 solo se resta el efectivo excedente: 300 - 2 % · 4000 = 220
    # capital = (500 + 2000) - 220 = 2280 ; ROIC = 790 / 2280 = 34.65 %
    comprobar('ROIC_%', r['ROIC_%'], 34.65)
    comprobar('ROA_% (790 / 7900)', r['ROA_%'], 10.0)
    comprobar('ROE_% (790 / 2000)', r['ROE_%'], 39.5)
    comprobar('Net_Margin_% (790 / 4000)', r['Net_Margin_%'], 19.75)
    comprobar('Debt_to_Equity (500 / 2000)', r['Debt_to_Equity'], 0.25)
    comprobar('EBITDA_MUSD', r['EBITDA_MUSD'], 1500.0)


# --- ROIC ---------------------------------------------------------------------
def roic(financials, balance_sheet):
    return sr.get_stock_fundamentals(FalsaAccion({}, financials=financials, balance_sheet=balance_sheet))['ROIC_%']


def test_roic_con_capital_promedio():
    """El capital invertido es el promedio del cierre de este año y del anterior"""
    r = roic(estado({'EBIT': 1000, 'Tax Provision': 210, 'Pretax Income': 1000}),
             estado_dos_anios({'Total Debt': (500, 300), 'Stockholders Equity': (2000, 1700),
                               'Cash And Cash Equivalents': (300, 200)}))
    # capital: 2200 (este año) y 1800 (anterior) -> promedio 2000 ; ROIC = 790 / 2000 = 39.5 %
    comprobar('ROIC_%', r, 39.5)


def test_roic_capital_anterior_no_valido_usa_el_actual():
    r = roic(estado({'EBIT': 1000, 'Tax Provision': 210, 'Pretax Income': 1000}),
             estado_dos_anios({'Total Debt': (500, 0), 'Stockholders Equity': (2000, -100),
                               'Cash And Cash Equivalents': (300, 50)}))
    comprobar('ROIC_% (solo capital actual)', r, 35.91)


def test_roic_tasa_de_impuestos():
    """Tasa efectiva acotada a 35 %; si no es positiva se usa 21 %"""
    balance = estado({'Stockholders Equity': 1000})
    comprobar('tasa de 60 % -> 35 %', roic(
        estado({'EBIT': 100, 'Tax Provision': 60, 'Pretax Income': 100}), balance), 6.5)
    comprobar('impuesto negativo -> 21 %', roic(
        estado({'EBIT': 100, 'Tax Provision': -5, 'Pretax Income': 100}), balance), 7.9)
    comprobar('pérdida antes de impuestos -> 21 %', roic(
        estado({'EBIT': 100, 'Tax Provision': 10, 'Pretax Income': -50}), balance), 7.9)
    comprobar('sin datos de impuestos -> 21 %', roic(estado({'EBIT': 100}), balance), 7.9)


def test_roic_efectivo_excedente():
    """Solo se resta el efectivo que supera el 2 % de las ventas"""
    fin = estado({'EBIT': 1000, 'Tax Provision': 210, 'Pretax Income': 1000, 'Total Revenue': 50000})
    # efectivo operativo = 1000 >= 300: no hay excedente ; capital = 2500 ; ROIC = 31.6 %
    comprobar('sin excedente', roic(fin, estado({'Total Debt': 500, 'Stockholders Equity': 2000,
                                                  'Cash And Cash Equivalents': 300})), 31.6)


def test_roic_deuda_por_partes_y_sin_deuda():
    fin = estado({'EBIT': 1000, 'Tax Provision': 210, 'Pretax Income': 1000})
    comprobar('deuda = largo + corto plazo', roic(fin, estado({
        'Long Term Debt': 400, 'Current Debt': 100, 'Stockholders Equity': 2000,
        'Cash And Cash Equivalents': 300})), 35.91)
    comprobar('sin filas de deuda', roic(fin, estado({'Stockholders Equity': 2000})), 39.5)


def test_roic_sin_respaldo_con_roa():
    """Si el cálculo falla, el ROIC queda sin dato: ya no se sustituye por el ROA"""
    accion = FalsaAccion({'returnOnAssets': 0.10}, financials=estado({'EBIT': 1000}),
                         balance_sheet=estado({'Stockholders Equity': 2000}))
    with patch.object(sr, '_calcular_roic', side_effect=ZeroDivisionError):
        r = sr.get_stock_fundamentals(accion)
    comprobar('ROIC_%', r['ROIC_%'], None)
    comprobar('ROA_%', r['ROA_%'], 10.0)
