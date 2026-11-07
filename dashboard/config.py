"""Constantes de presentación: paleta, escalas de color, columnas del explorador y textos."""

FUENTE_GRAFICOS = "DM Sans, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"

PALETA = {
    'primario': '#1dbe83',
    'tinta': '#0F172A',
    'texto': '#334155',
    'suave': '#64748B',
    'borde': '#E2E8F0',
    'fondo': '#F8FAFC',
    'alerta': '#F59E0B',
    'riesgo': '#EF4444',
}
ESCALA_SCORE = [PALETA['riesgo'], PALETA['alerta'], PALETA['primario']]
ESCALA_CORR = [PALETA['riesgo'], '#F8FAFC', PALETA['primario']]
COLORES_COMPONENTES = ['#6366F1', '#1dbe83', '#38BDF8', '#F59E0B',
                       '#A78BFA', '#F472B6', '#94A3B8', '#FB923C']

# Columnas que el explorador (componente TypeScript) ofrece en sus selectores:
# (columna, etiqueta, tipo 'num'/'cat', sufijo, decimales)
COLUMNAS_EXPLORADOR_ETFS = [
    ('Ticker', 'Ticker', 'cat', '', 0), ('Category', 'Categoría', 'cat', '', 0),
    ('Score_Final', 'Score', 'num', '', 1), ('52W_Change_%', 'Cambio 52 sem.', 'num', '%', 2),
    ('CAGR_%', 'CAGR', 'num', '%', 2), ('Volatilidad_%', 'Volatilidad', 'num', '%', 2),
    ('Max_Drawdown_%', 'Caída máxima', 'num', '%', 1), ('Sortino', 'Sortino', 'num', '', 2),
    ('Sharpe', 'Sharpe', 'num', '', 2), ('Expense_Ratio_%', 'TER', 'num', '%', 2),
    ('Yield_%', 'Rendimiento por dividendo', 'num', '%', 2), ('AUM_BUSD', 'AUM (miles de MDD)', 'num', '', 2),
    ('Cobertura_%', 'Cobertura de datos', 'num', '%', 0),
]
COLUMNAS_EXPLORADOR_ACCIONES = [
    ('Ticker', 'Ticker', 'cat', '', 0), ('Sector', 'Sector', 'cat', '', 0),
    ('Score_Final', 'Score', 'num', '', 1), ('52W_Change_%', 'Cambio 52 sem.', 'num', '%', 2),
    ('CAGR_%', 'CAGR ingresos', 'num', '%', 2), ('CAGR_Equity_%', 'CAGR capital', 'num', '%', 2),
    ('CAGR_FCF_%', 'CAGR flujo libre', 'num', '%', 2), ('CAGR_EBITDA_%', 'CAGR EBITDA', 'num', '%', 2),
    ('ROIC_%', 'ROIC', 'num', '%', 2), ('ROE_%', 'ROE', 'num', '%', 2), ('ROA_%', 'ROA', 'num', '%', 2),
    ('Net_Margin_%', 'Margen neto', 'num', '%', 2), ('Debt_to_Equity', 'Deuda/Capital', 'num', '', 2),
    ('Sortino', 'Sortino', 'num', '', 2), ('EBITDA_MUSD', 'EBITDA (MDD)', 'num', '', 0),
    ('Cobertura_%', 'Cobertura de datos', 'num', '%', 0),
]

NOTA_REESCALADO = ('Si a un activo le falta un criterio (sin dato en Yahoo Finance), su peso se reparte '
                   'entre los demás: cada barra siempre suma su score.')

# Lista inicial si no hay tickers guardados ni en la base ni en datos/portfolio_tickers.json
TICKERS_DEFECTO = {
    'etf_list': ['VOO', 'IVV', 'SPY'],
    'stock_list': ['AAPL', 'MSFT', 'GOOGL']
}
