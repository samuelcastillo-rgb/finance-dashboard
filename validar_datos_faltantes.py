# validar_datos_faltantes.py
# Validación SIN red de cómo stock_ratios.py y etf_ratios.py tratan los datos faltantes:
# un dato que Yahoo Finance no entrega debe salir como None ("sin dato"), nunca como 0.
#
# Uso:  python validar_datos_faltantes.py     (termina con "OK" si todo pasa)
from unittest.mock import patch

import pandas as pd

import etf_ratios as er
import stock_ratios as sr


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


def comprobar(nombre, obtenido, esperado):
    assert obtenido == esperado, f'{nombre}: esperado {esperado!r}, obtenido {obtenido!r}'
    print(f'  ok  {nombre}: {obtenido!r}')


METRICAS = ['ROA_%', 'ROE_%', 'ROIC_%', 'Debt_to_Equity', 'Net_Margin_%', 'EBITDA_MUSD']

print('1. Empresa con todos los datos (debe conservar el cálculo original)')
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

print('2. Banco: Yahoo no entrega EBIT ni EBITDA (deben ser None, no 0)')
banco = FalsaAccion(
    {'returnOnAssets': 0.011, 'returnOnEquity': 0.12, 'profitMargins': 0.30, 'debtToEquity': 100.0},
    financials=estado({'Pretax Income': 5e9}),
    balance_sheet=estado({'Stockholders Equity': 5e10}))
r = sr.get_stock_fundamentals(banco)
comprobar('ROIC_%', r['ROIC_%'], None)
comprobar('EBITDA_MUSD', r['EBITDA_MUSD'], None)
comprobar('ROE_%', r['ROE_%'], 12.0)
comprobar('Debt_to_Equity', r['Debt_to_Equity'], 1.0)

print('3. Deuda/Equity: derivada del balance cuando Yahoo no la trae')
sin_de = {'returnOnAssets': 0.1, 'returnOnEquity': 0.1, 'profitMargins': 0.1, 'ebitda': 1e9}
r = sr.get_stock_fundamentals(FalsaAccion(
    sin_de, balance_sheet=estado({'Total Debt': 300, 'Stockholders Equity': 1500})))
comprobar('con deuda (300 / 1500)', r['Debt_to_Equity'], 0.2)
r = sr.get_stock_fundamentals(FalsaAccion(
    sin_de, balance_sheet=estado({'Total Debt': 0, 'Stockholders Equity': 1500})))
comprobar('sin deuda: el 0 es un dato real', r['Debt_to_Equity'], 0.0)
r = sr.get_stock_fundamentals(FalsaAccion(sin_de))
comprobar('imposible de determinar', r['Debt_to_Equity'], None)

print('4. Capital invertido <= 0: ROIC no es interpretable (comportamiento actual: None)')
r = sr.get_stock_fundamentals(FalsaAccion(
    {'returnOnAssets': 0.1, 'returnOnEquity': 0.1, 'profitMargins': 0.1, 'debtToEquity': 10.0},
    financials=estado({'EBIT': 100, 'Tax Provision': 20, 'Pretax Income': 100}),
    balance_sheet=estado({'Total Debt': 100, 'Stockholders Equity': -500, 'Cash And Cash Equivalents': 50})))
comprobar('ROIC_%', r['ROIC_%'], None)

print('5. Yahoo falla por completo: todas las métricas None')
r = sr.get_stock_fundamentals(FalsaAccion(RuntimeError('sin datos')))
comprobar('métricas', [r[m] for m in METRICAS], [None] * len(METRICAS))

print('6. Descarga de precios fallida: None, no 0')
with patch.object(sr.yf, 'download', side_effect=RuntimeError('sin red')):
    r = sr.calculate_stock_performance('XXXX')
comprobar('acciones', r, {'CAGR_%': None, 'Volatilidad_%': None, 'Sortino': None})
with patch.object(er.yf, 'download', side_effect=RuntimeError('sin red')):
    r = er.calculate_etf_performance('XXXX')
comprobar('ETFs', r, {'CAGR_%': None, 'Volatilidad_%': None, 'Sharpe': None,
                      'Sortino': None, 'Max_Drawdown_%': None})

print('7. Yahoo bloquea info (p. ej. en la nube) pero sí entrega los estados financieros')
r = sr.get_stock_fundamentals(FalsaAccion(
    RuntimeError('429 Too Many Requests'),
    financials=estado({'EBIT': 1000, 'Tax Provision': 210, 'Pretax Income': 1000,
                       'Net Income': 790, 'Total Revenue': 4000, 'EBITDA': 1500e6}),
    balance_sheet=estado({'Total Debt': 500, 'Stockholders Equity': 2000,
                          'Cash And Cash Equivalents': 300, 'Total Assets': 7900})))
comprobar('ROIC_%', r['ROIC_%'], 35.91)
comprobar('ROA_% (790 / 7900)', r['ROA_%'], 10.0)
comprobar('ROE_% (790 / 2000)', r['ROE_%'], 39.5)
comprobar('Net_Margin_% (790 / 4000)', r['Net_Margin_%'], 19.75)
comprobar('Debt_to_Equity (500 / 2000)', r['Debt_to_Equity'], 0.25)
comprobar('EBITDA_MUSD', r['EBITDA_MUSD'], 1500.0)

print('OK')
