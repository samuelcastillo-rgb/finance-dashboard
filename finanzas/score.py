"""Score cuantitativo: percentiles ponderados dentro del universo cargado.

Las listas COMPONENTES_* son la ÚNICA fuente de verdad de la fórmula: se usan para
calcular el score, para el gráfico de aportes, para el inspector y para los textos
explicativos de la interfaz.
"""
import numpy as np
import pandas as pd

# (umbral mínimo, nombre, clase CSS). El orden importa: de mayor a menor.
NIVELES_SCORE = [(80, 'Excelente', 'excelente'), (60, 'Bueno', 'bueno'),
                 (40, 'Neutral', 'neutral'), (0, 'Débil', 'debil')]

# Cobertura mínima (fracción del peso total con dato) para calcular un score. Por debajo,
# el score reflejaría muy pocos criterios y se deja sin calcular.
MIN_COBERTURA = 0.5

# Cada componente: (etiqueta, columna de percentil, peso, columna con el valor real).
# Estas listas son la ÚNICA fuente de verdad de la fórmula: se usan para calcular el
# score, para el gráfico de aportes, para el inspector y para los textos explicativos.
COMPONENTES_ETFS = [
    ('Sortino', 'Pctl_Sortino', 0.34, 'Sortino'),
    ('CAGR 5a', 'Pctl_CAGR', 0.34, 'CAGR_%'),
    ('Costo (TER inv.)', 'Pctl_Exp_Ratio_Inv', 0.17, 'Expense_Ratio_%'),
    ('AUM (tamaño)', 'Pctl_AUM', 0.15, 'AUM_BUSD'),
]
COMPONENTES_ACCIONES = [
    ('ROIC', 'Pctl_ROIC', 0.20, 'ROIC_%'),
    ('Sortino', 'Pctl_Sortino', 0.20, 'Sortino'),
    ('CAGR 5a', 'Pctl_CAGR', 0.15, 'CAGR_%'),
    ('Margen neto', 'Pctl_Margin', 0.15, 'Net_Margin_%'),
    ('ROE', 'Pctl_ROE', 0.10, 'ROE_%'),
    ('Deuda/Equity (inv.)', 'Pctl_Debt_Inv', 0.10, 'Debt_to_Equity'),
    ('ROA', 'Pctl_ROA', 0.05, 'ROA_%'),
    ('EBITDA', 'Pctl_EBITDA', 0.05, 'EBITDA_MUSD'),
]


def nivel_score(score):
    """Devuelve (nombre, clase_css) del nivel cualitativo de un score 0-100."""
    try:
        valor = float(score)
    except (TypeError, ValueError):
        return 'Sin dato', 'neutral'
    if pd.isna(valor):
        return 'Sin dato', 'neutral'
    for umbral, nombre, clase in NIVELES_SCORE:
        if valor >= umbral:
            return nombre, clase
    return 'Débil', 'debil'


def peso_disponible(df, componentes):
    """Suma de los pesos de los criterios CON dato, por fila (un NaN no aporta peso)."""
    disponible = 0
    for _, col_pctl, peso, _ in componentes:
        disponible = disponible + peso * df[col_pctl].notna()
    return disponible.round(10)


def cobertura_pct(df, componentes):
    """% del peso total del score que tiene dato (100 = todos los criterios disponibles)."""
    total_pesos = round(sum(c[2] for c in componentes), 10)
    return (peso_disponible(df, componentes) / total_pesos * 100).round(0)


def calcular_score(df, componentes):
    """Score 0-100 = promedio ponderado de percentiles sobre los criterios CON dato.

    Si a un activo le falta un criterio (NaN) no se le castiga con 0: su peso se reparte
    proporcionalmente entre los criterios disponibles. Con todos los datos el resultado es
    idéntico a la suma ponderada clásica. Si el peso disponible es menor que MIN_COBERTURA
    del total, no hay base suficiente y el score es NaN.
    """
    total_pesos = round(sum(c[2] for c in componentes), 10)
    disponible = peso_disponible(df, componentes)
    suma = 0
    for _, col_pctl, peso, _ in componentes:
        suma = suma + peso * df[col_pctl].fillna(0)
    score = suma / disponible.where(disponible > 0)
    score = score.where(disponible / total_pesos >= MIN_COBERTURA)
    return score.round(1)


def puntuar_etfs(df):
    """Normaliza las columnas de ETFs, calcula percentiles, score y cobertura; ordena por score."""
    # Columnas informativas: sin dato = 0.
    columnas_default = {
        'Category': 'General', '52W_Change_%': 0.0, 'Yield_%': 0.0
    }
    for col, default_val in columnas_default.items():
        if col not in df.columns:
            df[col] = default_val
        else:
            if isinstance(default_val, (int, float)):
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(default_val)
            else:
                df[col] = df[col].fillna(default_val)

    # Las que alimentan el score o el análisis de riesgo se quedan como NaN = "sin dato":
    # ni 0 (que puntuaría como un valor real) ni el mejor percentil.
    for col in ['Expense_Ratio_%', 'AUM_BUSD', 'Sortino', 'CAGR_%', 'Volatilidad_%', 'Sharpe', 'Max_Drawdown_%']:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors='coerce')
    # TER = 0 es el valor de relleno de un dato no reportado (como "mejor costo" falsearía el score)
    df.loc[df['Expense_Ratio_%'] <= 0, 'Expense_Ratio_%'] = np.nan
    # Igual con el AUM: 0 es el relleno de "no reportado", y ahora el AUM puntúa
    df.loc[df['AUM_BUSD'] <= 0, 'AUM_BUSD'] = np.nan

    df['Pctl_Exp_Ratio_Inv'] = (1 - df['Expense_Ratio_%'].rank(pct=True, ascending=True)) * 100
    df['Pctl_AUM'] = df['AUM_BUSD'].rank(pct=True, ascending=True) * 100
    df['Pctl_Sortino'] = df['Sortino'].rank(pct=True, ascending=True) * 100
    df['Pctl_CAGR'] = df['CAGR_%'].rank(pct=True, ascending=True) * 100

    df['Score_Final'] = calcular_score(df, COMPONENTES_ETFS)
    df['Cobertura_%'] = cobertura_pct(df, COMPONENTES_ETFS)

    return df.sort_values(by='Score_Final', ascending=False)


def puntuar_acciones(df):
    """Normaliza las columnas de acciones, calcula percentiles, score y cobertura; ordena por score."""
    # Un criterio sin dato (Yahoo no lo entrega, p. ej. EBITDA/ROIC en bancos) queda como NaN:
    # no puntúa como 0 ni como el mejor, y el score re-escala los pesos de los demás.
    # Un ticker que falló por completo trae solo su registro de emergencia: todo NaN.
    for _, _, _, col_valor in COMPONENTES_ACCIONES:
        if col_valor not in df.columns:
            df[col_valor] = np.nan
        df[col_valor] = pd.to_numeric(df[col_valor], errors='coerce')
    for col in ['52W_Change_%', 'CAGR_Equity_%', 'CAGR_FCF_%', 'CAGR_EBITDA_%', 'Volatilidad_%']:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Asegurar tamaño positivo para Plotly (sin dato -> tamaño mínimo)
    df['EBITDA_Size'] = df['EBITDA_MUSD'].fillna(0).clip(lower=0.1)

    # Percentiles y Score
    df['Pctl_ROIC'] = df['ROIC_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Sortino'] = df['Sortino'].rank(pct=True, ascending=True) * 100
    df['Pctl_CAGR'] = df['CAGR_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Margin'] = df['Net_Margin_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_ROE'] = df['ROE_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_Debt_Inv'] = (1 - df['Debt_to_Equity'].rank(pct=True, ascending=True)) * 100
    df['Pctl_ROA'] = df['ROA_%'].rank(pct=True, ascending=True) * 100
    df['Pctl_EBITDA'] = df['EBITDA_MUSD'].rank(pct=True, ascending=True) * 100

    df['Score_Final'] = calcular_score(df, COMPONENTES_ACCIONES)
    df['Cobertura_%'] = cobertura_pct(df, COMPONENTES_ACCIONES)

    return df.sort_values(by='Score_Final', ascending=False)
