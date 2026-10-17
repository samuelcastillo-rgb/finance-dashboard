# escaner_etfs.py
#%%
import pandas as pd
import yfinance as yf
import dtale

# Importar las funciones de tu módulo modular
import etf_ratios as er

# 1. UNIVERSO DE ETFs POR SECTOR Y CATEGORÍA (AMPLIABLE)
universo_etfs = [
    # Mercado Amplio / Núcleo
    'VOO', 'IVV', 'SPY', 'VTI', 'QQQ', 'SCHX', 'IWM',
    # Tecnología y Semiconductores
    'XLK', 'VGT', 'SMH', 'SOXX', 'IGV',
    # Salud y Biotecnología
    'XLV', 'VHT', 'IBB', 'XBI',
    # Financiero
    'XLF', 'VFH', 'KBE', 'KRE',
    # Energía y Agua / Infraestructura
    'XLE', 'VDE', 'FIW', 'PHO', 'GRID',
    # Bienes Raíces (REITs)
    'VNQ', 'SCHH', 'IYR',
    # Consumo e Industrial
    'XLY', 'XLP', 'XLI', 'VIS',
    # Internacional y Mercados Emergentes
    'VEA', 'IEFA', 'VWO', 'EEM'
]

print(f"Analizando un universo de {len(universo_etfs)} ETFs...")
resultados = []

# 2. EXTRACCIÓN DE DATOS Y CÁLCULO DE MÉTRICAS
for symbol in universo_etfs:
    try:
        stock = yf.Ticker(symbol)
        
        # Estructura y fundamentales (AUM, TER, Familia, Categoría)
        fundamentales = er.get_etf_fundamentals(stock)
        
        # Rendimiento e indicadores de riesgo (5 años)
        performance = er.calculate_etf_performance(symbol, period="5y")
        
        # Consolidar información en un registro
        registro = {'Ticker': symbol}
        registro.update(fundamentales)
        registro.update(performance)
        
        resultados.append(registro)
    except Exception as e:
        print(f"Error procesando {symbol}: {e}")

df = pd.DataFrame(resultados)

# 3. FILTRADO Y LIMPIEZA DE DATOS NULOS O INVÁLIDOS
df = df[df['AUM_BUSD'] > 0].copy()

# 4. CÁLCULO DEL SCORE COMPUESTO (PERCENTILES)
# Invertimos el Expense Ratio para que la comisión más baja reciba la nota más alta (100)
df['Pctl_Expense_Inv'] = (1 - df['Expense_Ratio_%'].rank(pct=True, ascending=True)) * 100
df['Pctl_AUM'] = df['AUM_BUSD'].rank(pct=True, ascending=True) * 100
df['Pctl_Sortino'] = df['Sortino'].rank(pct=True, ascending=True) * 100

# Fórmula del Puntaje Ponderado
df['Score_Final'] = (
    (0.40 * df['Pctl_Sortino']) +
    (0.30 * df['Pctl_AUM']) +
    (0.30 * df['Pctl_Expense_Inv'])
).round(2)

# Ordenar por el Score de evaluación general
df_evaluado = df.sort_values(by='Score_Final', ascending=False)

# Reorganizar columnas para lectura ejecutiva
columnas_ordenadas = [
    'Ticker', 'Familia', 'Categoria', 'Score_Final', 
    'Expense_Ratio_%', 'AUM_BUSD', 'Sortino', 
    'CAGR_%', 'Volatilidad_%', 'Max_Drawdown_%', 'Yield_%'
]
df_final = df_evaluado[columnas_ordenadas]

# 5. AGRUPACIÓN Y MEJORES ETFs POR SECTOR Y POR FAMILIA
print("\n" + "="*80)
print("TOP 1 ETF POR CATEGORÍA / SECTOR")
print("="*80)
top_por_sector = df_final.groupby('Categoria').head(1)
print(top_por_sector[['Ticker', 'Familia', 'Categoria', 'Score_Final', 'Expense_Ratio_%', 'Sortino']].to_string(index=False))

print("\n" + "="*80)
print("TOP 1 ETF POR FAMILIA GESTORA")
print("="*80)
top_por_familia = df_final.groupby('Familia').head(1)
print(top_por_familia[['Ticker', 'Familia', 'Categoria', 'Score_Final', 'Expense_Ratio_%', 'Sortino']].to_string(index=False))

# 6. APERTURA EN D-TALE PARA EXPLORACIÓN COMPLETA
d = dtale.show(df_final)
print(f"\n[D-TALE] Servidor activo en: {d.main_url()}")
d.open_browser()

input("\n[INFO] Presiona ENTER en la terminal de VS Code para detener el servidor...")
#%%
