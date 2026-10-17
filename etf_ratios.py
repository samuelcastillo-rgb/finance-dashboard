# etf_ratios.py
import yfinance as yf
import pandas as pd
import numpy as np

def get_etf_fundamentals(stock):
    """
    Extrae la información estructural del ETF ajustando el Expense Ratio
    directamente al valor en porcentaje real sin multiplicar por 100.
    """
    try:
        info = stock.info
        
        # Extracción del Expense Ratio
        ter = (
            info.get('expenseRatio') or 
            info.get('annualReportExpenseRatio') or 
            info.get('netExpenseRatio') or 
            0
        )
        
        # Respaldo desde el objeto funds_data si estuviera presente
        if ter == 0 and hasattr(stock, 'funds_data') and stock.funds_data:
            try:
                ter = getattr(stock.funds_data, 'expense_ratio', 0) or 0
            except Exception:
                ter = 0

        # yfinance entrega el dato directamente en valor porcentual (ej. 0.03 = 0.03%, 0.50 = 0.50%)
        ter_pct = ter
        
        # Conversión de AUM a miles de millones de USD (Billions USD)
        aum_raw = info.get('totalAssets') or info.get('marketCap') or info.get('navPrice', 0) or 0
        aum_busd = round(aum_raw / 1e9, 2)
        
        # Rendimiento por dividendo
        raw_yield = (
            info.get('yield') or 
            info.get('trailingAnnualDividendYield') or 
            info.get('dividendYield') or 
            0
        )
        dividend_yield = raw_yield * 100 if raw_yield < 1 else raw_yield
        
        return {
            'Familia': info.get('fundFamily', 'N/A'),
            'Expense_Ratio_%': round(ter_pct, 4),
            'AUM_BUSD': aum_busd,
            'Yield_%': round(dividend_yield, 2),
            'Categoria': info.get('category', 'N/A')
        }
    except Exception:
        return {'Familia': 'N/A', 'Expense_Ratio_%': 0, 'AUM_BUSD': 0, 'Yield_%': 0, 'Categoria': 'N/A'}
    
def calculate_etf_performance(ticker_symbol, period="5y", rf=0.04):
    """
    Calcula las métricas de rendimiento histórico y riesgo:
    CAGR, Volatilidad Anualizada, Sharpe, Sortino y Max Drawdown.
    """
    try:
        df = yf.download(ticker_symbol, period=period, progress=False, auto_adjust=True)
        prices = df['Close']
        if isinstance(prices, pd.DataFrame):
            prices = prices.squeeze()
            
        prices = prices.dropna()
        returns = prices.pct_change().dropna()
        
        # 1. Retorno Anualizado Compuesto (CAGR)
        years = (prices.index[-1] - prices.index[0]).days / 365.25
        cagr = ((prices.iloc[-1] / prices.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
        
        # 2. Volatilidad Anualizada
        vol_anual = returns.std() * np.sqrt(252) * 100
        
        # 3. Sharpe Ratio: (Retorno Anual - Tasa Libre Riesgo) / Volatilidad
        excess_returns = (returns.mean() * 252) - rf
        sharpe = excess_returns / (vol_anual / 100) if vol_anual > 0 else 0
        
        # 4. Sortino Ratio (mide volatilidad solo en días bajistas)
        downside_returns = returns[returns < 0]
        vol_bajista = downside_returns.std() * np.sqrt(252) * 100
        sortino = excess_returns / (vol_bajista / 100) if vol_bajista > 0 else 0
        
        # 5. Max Drawdown
        picos = prices.cummax()
        drawdowns = (prices - picos) / picos
        max_dd = abs(drawdowns.min()) * 100
        
        return {
            'CAGR_%': round(cagr, 2),
            'Volatilidad_%': round(vol_anual, 2),
            'Sharpe': round(sharpe, 2),
            'Sortino': round(sortino, 2),
            'Max_Drawdown_%': round(max_dd, 2)
        }
    except Exception:
        return {'CAGR_%': 0, 'Volatilidad_%': 0, 'Sharpe': 0, 'Sortino': 0, 'Max_Drawdown_%': 0}


def calculate_tracking_metrics(etf_ticker, benchmark_ticker="^GSPC", period="3y"):
    """
    Calcula el Tracking Error y la Correlación frente a un Benchmark (ej. ^GSPC para el S&P 500).
    Tracking Error = Desviación estándar anualizada de la diferencia de retornos.
    """
    try:
        data = yf.download([etf_ticker, benchmark_ticker], period=period, progress=False, auto_adjust=True)['Close']
        data = data.dropna()
        returns = data.pct_change().dropna()
        
        # Diferencia diaria de retornos
        diff = returns[etf_ticker] - returns[benchmark_ticker]
        
        # Tracking Error Anualizado
        tracking_error = diff.std() * np.sqrt(252) * 100
        correlacion = returns[etf_ticker].corr(returns[benchmark_ticker])
        
        return {
            'Tracking_Error_%': round(tracking_error, 2),
            'Correlacion_BM': round(correlacion, 2)
        }
    except Exception:
        return {'Tracking_Error_%': 0, 'Correlacion_BM': 0}