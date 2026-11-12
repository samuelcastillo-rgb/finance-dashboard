# finanzas/stock_ratios.py
import numpy as np
import pandas as pd
import yfinance as yf


def _numero(valor):
    """Convierte a float. Devuelve None si el dato falta (None, NaN o no numérico):
    un dato que Yahoo no entregó NO es un 0 y no debe puntuar como tal."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v

def _redondear(valor, decimales=2):
    return None if valor is None else round(valor, decimales)

def _porcentaje(info, clave):
    v = _numero(info.get(clave))
    return None if v is None else v * 100

def _ultimo_valor(df, fila):
    """Valor más reciente de una fila de un estado financiero; None si no existe o es NaN."""
    try:
        if fila not in df.index:
            return None
        return _numero(df.loc[fila].iloc[0])
    except Exception:
        return None

# Supuestos del ROIC
TASA_IMPUESTOS_DEFECTO = 0.21   # tasa corporativa federal de EE. UU.
TASA_IMPUESTOS_MAXIMA = 0.35    # una tasa efectiva mayor suele venir de un cargo extraordinario
EFECTIVO_OPERATIVO = 0.02       # caja que la operación necesita (2 % de las ventas): no es excedente


def _valor(df, fila, col=0):
    """Valor de una fila en la columna `col` (0 = año más reciente, 1 = el anterior)."""
    try:
        if df is None or fila not in df.index or df.shape[1] <= col:
            return None
        return _numero(df.loc[fila].iloc[col])
    except Exception:
        return None

def _primer_valor(df, filas, col=0):
    """Primer dato disponible entre varias filas equivalentes."""
    for fila in filas:
        v = _valor(df, fila, col)
        if v is not None:
            return v
    return None

def _tasa_impuestos(fin):
    """Tasa efectiva (impuestos / utilidad antes de impuestos) acotada a TASA_IMPUESTOS_MAXIMA.
    Si no es positiva o no se puede calcular, se usa la tasa normal (21 %)."""
    impuestos = _valor(fin, 'Tax Provision')
    antes = _valor(fin, 'Pretax Income')
    if impuestos is None or antes is None or antes <= 0 or impuestos <= 0:
        return TASA_IMPUESTOS_DEFECTO
    return min(impuestos / antes, TASA_IMPUESTOS_MAXIMA)

def _capital_invertido(fin, bs, col):
    """Deuda + capital contable − efectivo excedente al cierre del año `col`. None si falta
    el capital contable. El efectivo excedente es el que supera el 2 % de las ventas; sin
    ventas se resta todo el efectivo."""
    equity = _valor(bs, 'Stockholders Equity', col)
    if equity is None:
        return None
    deuda = _valor(bs, 'Total Debt', col)
    if deuda is None:
        # Sin la fila del total, se suman sus partes; si tampoco existen, la empresa no reporta deuda.
        partes = [_valor(bs, fila, col) for fila in ('Long Term Debt', 'Current Debt')]
        deuda = sum(p for p in partes if p is not None)
    efectivo = _primer_valor(bs, ['Cash And Cash Equivalents',
                                  'Cash Cash Equivalents And Short Term Investments'], col) or 0
    ventas = _valor(fin, 'Total Revenue', col)
    if ventas is not None and ventas > 0:
        efectivo = max(0.0, efectivo - EFECTIVO_OPERATIVO * ventas)
    return deuda + equity - efectivo

def _calcular_roic(fin, bs):
    """ROIC = NOPAT / Capital invertido promedio, en %.

    - NOPAT = EBIT × (1 − tasa de impuestos), con la tasa de _tasa_impuestos.
    - Capital invertido promedio = promedio del cierre de este año y del anterior (si el
      anterior no está o no es positivo, solo el de este año).
    None si no es calculable: sin EBIT o sin capital contable (p. ej. bancos y
    financieras, que Yahoo reporta sin EBIT) o con capital invertido <= 0."""
    ebit = _valor(fin, 'EBIT')
    if ebit is None:
        return None
    capital_final = _capital_invertido(fin, bs, 0)
    if capital_final is None or capital_final <= 0:
        return None
    capital_inicial = _capital_invertido(fin, bs, 1)
    capital = (capital_final + capital_inicial) / 2 if capital_inicial is not None and capital_inicial > 0 \
        else capital_final
    nopat = ebit * (1 - _tasa_impuestos(fin))
    return nopat / capital * 100

def _calcular_debt_equity(stock, info):
    """Deuda/Equity. Usa el dato de Yahoo; si falta, lo deriva del balance. Una empresa
    sin deuda (Total Debt = 0) sí vale 0. Si no se puede determinar, devuelve None."""
    de_info = _numero(info.get('debtToEquity'))
    if de_info is not None:
        return de_info / 100
    try:
        bs = stock.balance_sheet
        debt = _ultimo_valor(bs, 'Total Debt')
        if debt is None:
            return None
        if debt == 0:
            return 0.0
        equity = _ultimo_valor(bs, 'Stockholders Equity')
        return debt / equity if equity is not None and equity > 0 else None
    except Exception:
        return None

def _estado(stock, nombre):
    """Estado financiero ('financials' o 'balance_sheet'); DataFrame vacío si Yahoo falla."""
    try:
        df = getattr(stock, nombre)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def _ratio_pct(numerador, denominador):
    """numerador / denominador en %; None si falta alguno o el denominador no es positivo."""
    if numerador is None or denominador is None or denominador <= 0:
        return None
    return numerador / denominador * 100

def get_stock_fundamentals(stock):
    """Extrae las métricas fundamentales requeridas para acciones individuales.
    Una métrica que no se pueda obtener se devuelve como None (no como 0).
    Si Yahoo no entrega `info` (p. ej. bloquea las peticiones desde servidores en la nube),
    las métricas se calculan con los estados financieros anuales más recientes."""
    try:
        try:
            info = stock.info or {}
        except Exception:
            info = {}
        fin = _estado(stock, 'financials')
        bs = _estado(stock, 'balance_sheet')
        net_income = _ultimo_valor(fin, 'Net Income')

        # 1. Rentabilidades (convertidas a %)
        roa = _porcentaje(info, 'returnOnAssets')
        if roa is None:
            roa = _ratio_pct(net_income, _ultimo_valor(bs, 'Total Assets'))
        roe = _porcentaje(info, 'returnOnEquity')
        if roe is None:
            roe = _ratio_pct(net_income, _ultimo_valor(bs, 'Stockholders Equity'))
        net_margin = _porcentaje(info, 'profitMargins')
        if net_margin is None:
            net_margin = _ratio_pct(net_income, _ultimo_valor(fin, 'Total Revenue'))

        # 2. ROIC (NOPAT / Capital invertido promedio). Si no se puede calcular queda sin dato:
        #    usar otra métrica en su lugar mezclaría cosas distintas en el mismo percentil.
        try:
            roic = _calcular_roic(fin, bs)
        except Exception:
            roic = None

        # 3. Solvencia y Escala
        debt_equity = _calcular_debt_equity(stock, info)
        ebitda_raw = _numero(info.get('ebitda'))
        if ebitda_raw is None:
            ebitda_raw = _ultimo_valor(fin, 'EBITDA')
        ebitda_mbusd = None if ebitda_raw is None else ebitda_raw / 1e6  # Millones USD

        return {
            'Empresa': info.get('shortName', 'N/A'),
            'Sector': info.get('sector', 'N/A'),
            'ROA_%': _redondear(roa),
            'ROE_%': _redondear(roe),
            'ROIC_%': _redondear(roic),
            'Debt_to_Equity': _redondear(debt_equity),
            'Net_Margin_%': _redondear(net_margin),
            'EBITDA_MUSD': _redondear(ebitda_mbusd)
        }
    except Exception:
        return {
            'Empresa': 'N/A', 'Sector': 'N/A', 'ROA_%': None,
            'ROE_%': None, 'ROIC_%': None, 'Debt_to_Equity': None,
            'Net_Margin_%': None, 'EBITDA_MUSD': None
        }

def calculate_stock_performance(ticker_symbol, period="5y", rf=0.04):
    """Calcula el Sortino Ratio y rendimiento histórico a 5 años.
    Si no hay precios (descarga fallida) devuelve None, no 0."""
    try:
        df = yf.download(ticker_symbol, period=period, progress=False, auto_adjust=True)
        prices = df['Close']
    except Exception:
        prices = None
    return calculate_stock_performance_from_prices(prices, rf=rf)

def calculate_stock_performance_from_prices(prices, rf=0.04):
    """Igual que calculate_stock_performance, pero sobre una serie de precios de cierre ya
    descargada (permite descargar todos los tickers en una sola llamada)."""
    try:
        if isinstance(prices, pd.DataFrame):
            prices = prices.squeeze()

        prices = prices.dropna()
        returns = prices.pct_change().dropna()

        years = (prices.index[-1] - prices.index[0]).days / 365.25
        cagr = ((prices.iloc[-1] / prices.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
        vol_anual = returns.std() * np.sqrt(252) * 100

        excess_returns = (returns.mean() * 252) - rf
        downside_returns = returns[returns < 0]
        vol_bajista = downside_returns.std() * np.sqrt(252) * 100
        sortino = excess_returns / (vol_bajista / 100) if vol_bajista > 0 else 0

        return {
            'CAGR_%': round(cagr, 2),
            'Volatilidad_%': round(vol_anual, 2),
            'Sortino': round(sortino, 2)
        }
    except Exception:
        return {'CAGR_%': None, 'Volatilidad_%': None, 'Sortino': None}

def calcular_cagr_serie(serie):
    """
    Calcula el CAGR (%) de una serie contable anual de yfinance.
    Protegida contra filas duplicadas, datos corruptos y divisiones por cero.
    """
    try:
        if serie is None or serie.empty:
            return 0.0

        # BLINDAJE: Si yfinance entrega un DataFrame por filas duplicadas, tomamos solo la primera
        if isinstance(serie, pd.DataFrame):
            serie = serie.iloc[0]

        s = serie.dropna()
        if len(s) < 2:
            return 0.0

        # Ordenar cronológicamente
        s = s.sort_index(ascending=True)
        val_inicial = float(s.iloc[0])
        val_final = float(s.iloc[-1])
        n_anios = len(s) - 1

        if val_inicial > 0 and val_final > 0 and n_anios > 0:
            cagr = ((val_final / val_inicial) ** (1 / n_anios) - 1) * 100
            return round(cagr, 2)
        elif val_inicial != 0 and n_anios > 0:
            return round(((val_final - val_inicial) / abs(val_inicial)) * (100 / n_anios), 2)
        return 0.0
    except Exception:
        return 0.0
