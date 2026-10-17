
import io
import pandas as pd
import requests
import yfinance as yf

# 1. Obtener lista oficial del S&P 500
url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

response = requests.get(url, headers=headers)
sp500_table = pd.read_html(io.StringIO(response.text))[0]

df_sp500 = sp500_table[["Symbol", "Security", "GICS Sector"]].copy()
df_sp500.columns = ["Ticker", "Empresa", "Sector"]
df_sp500["Ticker_YF"] = df_sp500["Ticker"].str.replace(".", "-", regex=False)

tickers_list = df_sp500["Ticker_YF"].tolist()

# 2. Descarga masiva con ajuste automático
print("Descargando precios del S&P 500...")
datos = yf.download(
    tickers_list, period="6mo", progress=False, auto_adjust=True
)

# Extraer precios de cierre manejando posibles estructuras MultiIndex
if isinstance(datos.columns, pd.MultiIndex):
    precios = datos["Close"]
else:
    precios = datos["Close"] if "Close" in datos else datos

# 3. Limpieza de datos y cálculo de métricas
precios_limpios = precios.ffill()  # Rellena posibles días sin cotización

precio_actual = precios_limpios.iloc[-1]
sma_50 = precios_limpios.rolling(window=50).mean().iloc[-1]
tendencia_pct = ((precio_actual - sma_50) / sma_50) * 100

# 4. Crear DataFrame temporal de cálculos
df_calculos = pd.DataFrame(
    {
        "Ticker_YF": precio_actual.index,
        "Precio_USD": precio_actual.values.round(2),
        "Tendencia_%": tendencia_pct.values.round(2),
    }
)

# 5. Fusionar ambas tablas mediante merge (garantiza coincidencia exacta)
df_final = pd.merge(df_sp500, df_calculos, on="Ticker_YF", how="inner")
df_final.drop(columns=["Ticker_YF"], inplace=True)

# Eliminar acciones que no devolvieron datos en yfinance
df_final.dropna(subset=["Precio_USD", "Tendencia_%"], inplace=True)

# 6. Mostrar las 20 empresas con mayor tendencia alcista
top_bajistas = df_final.sort_values(
    by="Tendencia_%", ascending=True
).head(20)

top_alcistas = df_final.sort_values(
    by="Tendencia_%", ascending=False
).head(20)

# 7. Mostrar la lista de stocks top bajistas y top alcistas solo de la columna Ticker
print("Top 20 bajistas del S&P 500:")
print(top_bajistas["Ticker"].tolist())
print("Top 20 alcistas del S&P 500:")
print(top_alcistas["Ticker"].tolist())







