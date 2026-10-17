#Obtener el patrimonio neto de una empresa en los ultimos 4 años

import yfinance as yf

# Obtener datos de la empresa (ejemplo: Apple)
ticker = "AAPL"
data = yf.Ticker(ticker)

# Obtener el patrimonio neto (equity) para los últimos 4 años
balance_sheet = data.balance_sheet
net_worth = balance_sheet.loc['Stockholders Equity'] / 1e9 # Convertir a billones para mejor legibilidad
net_worth_last_4_years = net_worth.sort_index(ascending=True).head(4)
print(f"Patrimonio neto de {ticker} en los últimos 4 años:")
print(net_worth_last_4_years)

#Calcular el crecimiento anual compuesto CAGR
n_anios = len(net_worth_last_4_years) - 1
cagr = ((net_worth_last_4_years.iloc[-1] / net_worth_last_4_years.iloc[0]) ** (1 / n_anios) - 1) * 100
print(f"Crecimiento anual compuesto (CAGR): {cagr:.2f}%")