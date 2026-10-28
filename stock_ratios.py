# stock_ratios.py
import yfinance as yf
import pandas as pd
import numpy as np

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

def _calcular_roic(stock):
    """ROIC = NOPAT / Capital invertido. None si no es calculable (p. ej. bancos y
    financieras, que Yahoo reporta sin EBIT)."""
    fin = stock.financials
    bs = stock.balance_sheet
    ebit = _ultimo_valor(fin, 'EBIT')
    equity = _ultimo_valor(bs, 'Stockholders Equity')
    if ebit is None or equity is None:
        return None

    tax_provision = _ultimo_valor(fin, 'Tax Provision') or 0
    pretax = _ultimo_valor(fin, 'Pretax Income')
    pretax = 1 if pretax is None else pretax
    tax_rate = (tax_provision / pretax) if pretax > 0 and tax_provision > 0 else 0.21
    nopat = ebit * (1 - tax_rate)

    debt = _ultimo_valor(bs, 'Total Debt') or 0
    cash = _ultimo_valor(bs, 'Cash And Cash Equivalents') or 0
    capital = (debt + equity) - cash
    return (nopat / capital) * 100 if capital > 0 else None

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

def get_stock_fundamentals(stock):
    """Extrae las métricas fundamentales requeridas para acciones individuales.
    Una métrica que no se pueda obtener se devuelve como None (no como 0)."""
    try:
        info = stock.info

        # 1. Rentabilidades (convertidas a %)
        roa = _porcentaje(info, 'returnOnAssets')
        roe = _porcentaje(info, 'returnOnEquity')
        net_margin = _porcentaje(info, 'profitMargins')

        # 2. ROIC personalizado (NOPAT / Capital Invertido)
        try:
            roic = _calcular_roic(stock)
        except Exception:
            roic = roa  # Respaldo

        # 3. Solvencia y Escala
        debt_equity = _calcular_debt_equity(stock, info)
        ebitda_raw = _numero(info.get('ebitda'))
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