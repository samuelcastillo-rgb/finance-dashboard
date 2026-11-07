# tests/test_score.py
# Pruebas de la fórmula del score (finanzas/score.py): pesos, re-escalado cuando falta
# un criterio, cobertura mínima, niveles y percentiles invertidos.
import numpy as np
import pandas as pd
import pytest

from finanzas import score as sc

# Fórmula de juguete con dos criterios: A pesa 75% y B 25%
COMPONENTES = [('A', 'Pctl_A', 0.75, 'A'), ('B', 'Pctl_B', 0.25, 'B')]


def test_pesos_suman_uno():
    for componentes in (sc.COMPONENTES_ETFS, sc.COMPONENTES_ACCIONES):
        assert sum(c[2] for c in componentes) == pytest.approx(1.0)


def test_score_con_todos_los_datos_es_la_suma_ponderada():
    df = pd.DataFrame({'Pctl_A': [80.0], 'Pctl_B': [40.0]})
    assert sc.calcular_score(df, COMPONENTES).iloc[0] == pytest.approx(0.75 * 80 + 0.25 * 40)


def test_criterio_sin_dato_reparte_su_peso():
    # Falta B (25%): la cobertura es 75% y el score es solo el percentil de A, no A*0.75
    df = pd.DataFrame({'Pctl_A': [80.0], 'Pctl_B': [np.nan]})
    assert sc.calcular_score(df, COMPONENTES).iloc[0] == pytest.approx(80.0)
    assert sc.cobertura_pct(df, COMPONENTES).iloc[0] == 75


def test_cobertura_insuficiente_deja_score_vacio():
    # Falta A (75%): solo queda 25% del peso, menos que MIN_COBERTURA
    df = pd.DataFrame({'Pctl_A': [np.nan], 'Pctl_B': [90.0]})
    assert sc.cobertura_pct(df, COMPONENTES).iloc[0] < sc.MIN_COBERTURA * 100
    assert pd.isna(sc.calcular_score(df, COMPONENTES).iloc[0])


@pytest.mark.parametrize('score, nivel', [
    (95, 'Excelente'), (80, 'Excelente'), (79.9, 'Bueno'), (60, 'Bueno'),
    (45, 'Neutral'), (10, 'Débil'), (None, 'Sin dato'), (np.nan, 'Sin dato'), ('abc', 'Sin dato'),
])
def test_nivel_score(score, nivel):
    assert sc.nivel_score(score)[0] == nivel


def _etfs():
    return pd.DataFrame({
        'Ticker': ['BARATO', 'MEDIO', 'CARO'],
        'Expense_Ratio_%': [0.03, 0.20, 0.75],
        'AUM_BUSD': [500.0, 50.0, 5.0],
        'Sortino': [1.5, 1.0, 0.5],
        'CAGR_%': [15.0, 10.0, 5.0],
    })


def test_puntuar_etfs_ordena_y_invierte_el_costo():
    df = sc.puntuar_etfs(_etfs())
    assert df['Ticker'].tolist() == ['BARATO', 'MEDIO', 'CARO']
    # Menor TER = mejor percentil (criterio invertido)
    pctl = df.set_index('Ticker')['Pctl_Exp_Ratio_Inv']
    assert pctl['BARATO'] > pctl['MEDIO'] > pctl['CARO']
    assert df['Cobertura_%'].eq(100).all()
    assert df['Score_Final'].between(0, 100).all()


def test_puntuar_etfs_ter_cero_es_sin_dato():
    # Un TER de 0 es el relleno de "no reportado": no debe contar como el más barato
    datos = _etfs()
    datos.loc[2, 'Expense_Ratio_%'] = 0.0
    df = sc.puntuar_etfs(datos).set_index('Ticker')
    assert pd.isna(df.loc['CARO', 'Expense_Ratio_%'])
    assert pd.isna(df.loc['CARO', 'Pctl_Exp_Ratio_Inv'])
    assert df.loc['CARO', 'Cobertura_%'] == 83  # le falta el 17% del costo


def test_puntuar_acciones_columnas_faltantes_quedan_sin_dato():
    # Un ticker que falló por completo solo trae Ticker: no debe romper ni puntuar como 0
    datos = pd.DataFrame({
        'Ticker': ['BUENA', 'MALA', 'VACIA'],
        'ROIC_%': [30.0, 5.0, None], 'Sortino': [2.0, 0.5, None], 'CAGR_%': [20.0, 2.0, None],
        'Net_Margin_%': [25.0, 3.0, None], 'ROE_%': [30.0, 5.0, None],
        'Debt_to_Equity': [0.2, 2.5, None], 'ROA_%': [12.0, 1.0, None], 'EBITDA_MUSD': [5000.0, 50.0, None],
    })
    df = sc.puntuar_acciones(datos).set_index('Ticker')
    assert df.loc['BUENA', 'Score_Final'] > df.loc['MALA', 'Score_Final']
    assert pd.isna(df.loc['VACIA', 'Score_Final'])
    assert df.loc['VACIA', 'Cobertura_%'] == 0
