# stock_ratios.py
import yfinance as yf
import pandas as pd
import numpy as np

def get_stock_fundamentals(stock):
    """Extrae las métricas fundamentales requeridas para acciones individuales."""
    try:
        info = stock.info
        
        # 1. Rentabilidades (convertidas a %)
        roa = (info.get('returnOnAssets', 0) or 0) * 100
        roe = (info.get('returnOnEquity', 0) or 0) * 100
        net_margin = (info.get('profitMargins', 0) or 0) * 100
        
        # 2. ROIC personalizado (NOPAT / Capital Invertido)
        try:
            fin = stock.financials
            bs = stock.balance_sheet
            ebit = fin.loc['EBIT'].iloc[0] if 'EBIT' in fin.index else 0
            tax_provision = fin.loc['Tax Provision'].iloc[0] if 'Tax Provision' in fin.index else 0
            pretax = fin.loc['Pretax Income'].iloc[0] if 'Pretax Income' in fin.index else 1
            
            tax_rate = (tax_provision / pretax) if pretax > 0 and tax_provision > 0 else 0.21
            nopat = ebit * (1 - tax_rate)
            
            debt = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
            equity = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 0
            cash = bs.loc['Cash And Cash Equivalents'].iloc[0] if 'Cash And Cash Equivalents' in bs.index else 0
            
            capital = (debt + equity) - cash
            roic = (nopat / capital) * 100 if capital > 0 else 0
        except Exception:
            roic = (info.get('returnOnAssets', 0) or 0) * 100  # Respaldo
            
        # 3. Solvencia y Escala
        debt_equity = (info.get('debtToEquity', 0) or 0) / 100
        ebitda_raw = info.get('ebitda', 0) or 0
        ebitda_mbusd = round(ebitda_raw / 1e6, 2)  # Expresado en Millones USD
        
        return {
            'Empresa': info.get('shortName', 'N/A'),
            'Sector': info.get('sector', 'N/A'),
            'ROA_%': round(roa, 2),
            'ROE_%': round(roe, 2),
            'ROIC_%': round(roic, 2),
            'Debt_to_Equity': round(debt_equity, 2),
            'Net_Margin_%': round(net_margin, 2),
            'EBITDA_MUSD': ebitda_mbusd
        }
    except Exception:
        return {
            'Empresa': 'N/A', 'Sector': 'N/A', 'ROA_%': 0, 
            'ROE_%': 0, 'ROIC_%': 0, 'Debt_to_Equity': 0, 
            'Net_Margin_%': 0, 'EBITDA_MUSD': 0
        }

def calculate_stock_performance(ticker_symbol, period="5y", rf=0.04):
    """Calcula el Sortino Ratio y rendimiento histórico a 5 años."""
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
        return {'CAGR_%': 0, 'Volatilidad_%': 0, 'Sortino': 0}

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