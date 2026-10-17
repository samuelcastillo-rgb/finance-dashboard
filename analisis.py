# %%
import dtale
import yfinance as yf
import pandas as pd
import ratios as r

tickers = ['PANW', 'CGNX', 'TER', 'JNJ', 'AMZN', 'MP']
resultados = []

for ticker in tickers:
    stock = yf.Ticker(ticker)
    nombre_empresa = stock.info.get('longName', 'N/A')
    sector = stock.info.get('sector', 'N/A')
    roa = r.calculate_roa(stock)
    roe = r.calculate_roe(stock)
    roic = r.calculate_roic(stock)
    liquidity_ratio = r.calculate_liquidity_ratio(stock)
    immediate_liquidity_ratio = r.calculate_immediate_liquidity_ratio(stock)
    debt_to_equity_ratio = r.calculate_debt_to_equity_ratio(stock)
    interest_coverage_ratio = r.calculate_interest_coverage(stock)
    average_collection_period = r.calculate_average_collection_period(stock)
    average_payment_period = r.calculate_average_payment_period(stock)
    inventory_days = r.calculate_inventory_days(stock)
    net_margin = r.calculate_net_margin(stock)
    


    resultados.append({
        'Ticker': ticker,
        'Empresa': nombre_empresa,
        'Sector': sector,
        'ROA (%)': roa,
        'ROE (%)': roe,
        'ROIC (%)': roic,
        'Liquidity Ratio': liquidity_ratio,
        'Immediate Liquidity Ratio': immediate_liquidity_ratio,
        'Debt to Equity Ratio': debt_to_equity_ratio,
        'Interest Coverage Ratio': interest_coverage_ratio,
        'Average Collection Period(days)': average_collection_period,
        'Average Payment Period(days)': average_payment_period,
        'Inventory Days(days)': inventory_days,
        'Net Margin(%)': net_margin
    })

df = pd.DataFrame(resultados)
dtale.show(df).open_browser()
# %%
