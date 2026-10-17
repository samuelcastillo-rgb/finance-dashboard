# analisis_etf.py
#%%
import pandas as pd
import yfinance as yf
import dtale

# Importar el paquete modular de funciones de ETFs
import etf_ratios as er

# Lista de ETFs diversificados por sectores y geografías (Disponibles en el SIC / GBM)
etfs_analisis = ['IHAK','CIBR','SOXX','SMH','URNM','NLR','ARKX','CHAT','AIQ','ROBO','BOTZ','GNOM','CQTM','QTUM','WQTM', 'QTUP', 'ARKG','VOO', 'SPY', 'IVV', 'REXC', 'REMX', 'EART', 'FTXL', 'GSG', 'XLC', 'VHT', 'XLV', 'FIDU', 'VIS', 'VGT', 'FIW', 'PHO']
resultados = []

for symbol in etfs_analisis:
    stock = yf.Ticker(symbol)
    
    # 1. Métricas estructurales
    fundamentales = er.get_etf_fundamentals(stock)
    
    # 2. Métricas de desempeño histórico (a 5 años)
    performance = er.calculate_etf_performance(symbol, period="5y")
    
    # 3. Métricas de réplica frente al S&P 500 (^GSPC)
    tracking = er.calculate_tracking_metrics(symbol, benchmark_ticker="^GSPC", period="3y")
    
    # Consolidar en un solo diccionario por ETF
    registro = {'Ticker': symbol}
    registro.update(fundamentales)
    registro.update(performance)
    registro.update(tracking)
    
    resultados.append(registro)

df_etfs = pd.DataFrame(resultados)

# Visualización interactiva en D-Tale manteniendo el proceso activo
d = dtale.show(df_etfs)
print(f"Panel D-Tale disponible en: {d.main_url()}")
d.open_browser()
input("\n[INFO] Presiona ENTER en la terminal para finalizar...")
#%%