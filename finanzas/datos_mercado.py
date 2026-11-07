# finanzas/datos_mercado.py
# Obtención de datos de Yahoo Finance por ticker (info, estados financieros, dividendos).
# Lo usan dashboard/carga.py (para tickers que aún no están en la base) y scripts/actualizar_datos.py
# (proceso diario que guarda los registros en la base). No depende de Streamlit:
# los cálculos son los mismos que antes vivían en app.py.

import time

import pandas as pd
import yfinance as yf

from finanzas import almacenamiento
from finanzas import etf_ratios as er
from finanzas import stock_ratios as sr

# --- CONEXIÓN CON YAHOO FINANCE DESDE LA NUBE ---
# No se pasa una sesión propia: yfinance usa curl_cffi, que imita la huella TLS de un navegador.
# Una sesión de `requests` con cabeceras falsas no la imita, y Yahoo suele bloquear `info`
# (error 429) desde servidores en la nube aunque los precios sí se descarguen.

# Hilos simultáneos para consultar Yahoo (info y estados financieros son E/S de red).
# Más hilos acelera la carga inicial pero aumenta el riesgo de que Yahoo limite peticiones.
MAX_HILOS_YAHOO = 4
INTENTOS_INFO = 3


def obtener_info(ticker):
    """`ticker.info` con reintentos y espera creciente (Yahoo rechaza ráfagas con 429).
    Devuelve {} si no hay respuesta útil tras todos los intentos."""
    for intento in range(INTENTOS_INFO):
        try:
            info = ticker.info or {}
            # Una respuesta bloqueada suele traer solo un par de claves sin datos
            if len(info) > 5:
                return info
        except Exception:
            pass
        if intento < INTENTOS_INFO - 1:
            time.sleep(1.5 * (intento + 1))
    return {}


# ------------------------------------------------------------------------------
# ETFS
# ------------------------------------------------------------------------------
def obtener_metrica_etf(symbol, metadatos):
    """Registro de un ETF con datos de Yahoo (info + dividendos). `metadatos` es el respaldo
    de almacenamiento.cargar_metadatos() para cuando Yahoo bloquea `info`.
    Devuelve None si falla. El rendimiento (CAGR, Sortino...) se calcula aparte con los precios."""
    try:
        etf = yf.Ticker(symbol)
        info = obtener_info(etf)

        # Soportar ambas formas posibles en las que se pudo haber guardado el JSON
        dict_etfs = metadatos.get("etfs") or metadatos.get("etf_list") or {}
        fallback = dict_etfs.get(symbol.upper(), {
            'Nombre': symbol, 'Category': 'General', 'Expense_Ratio_%': 0.0, 'AUM_BUSD': 0.0
        })

        nombre = info.get('shortName') or info.get('longName') or fallback.get('Nombre', symbol)

        categoria = (
            info.get('category') or info.get('legalType') or
            info.get('quoteType') or info.get('fundFamily')
        )
        if not categoria or categoria in ['General', 'Sin Categoría']:
            categoria = fallback.get('Category', 'General')

        exp_raw = info.get('netExpenseRatio') or info.get('annualReportExpenseRatio') or info.get('expenseRatio')
        if exp_raw is not None and float(exp_raw) > 0:
            exp_float = float(exp_raw)
            exp_ratio = round(exp_float * 100, 3) if exp_float < 0.005 else round(exp_float, 3)
        else:
            exp_ratio = fallback.get('Expense_Ratio_%', 0.0)

        aum_raw = info.get('totalAssets')
        if aum_raw and float(aum_raw) > 0:
            aum_busd = round(float(aum_raw) / 1e9, 2)
        else:
            aum_busd = fallback.get('AUM_BUSD', 0.0)

        # Yahoo respondió con datos reales: los guardamos en la base para la app en línea
        if info and categoria not in ['General', 'Sin Categoría']:
            almacenamiento.guardar_metadato('etf_list', symbol.upper(), {
                'Nombre': nombre, 'Category': categoria,
                'Expense_Ratio_%': exp_ratio, 'AUM_BUSD': aum_busd
            })

        raw_52w = info.get('52WeekChange')
        change_52w = round(float(raw_52w) * 100, 2) if raw_52w is not None else 0.0

        fund = {
            'Nombre': nombre,
            'Category': categoria,
            'Expense_Ratio_%': exp_ratio,
            'AUM_BUSD': aum_busd,
            '52W_Change_%': change_52w
        }

        # El rendimiento (CAGR, Sortino, etc.) se calcula en cargar_datos_etfs a partir de la
        # descarga conjunta de precios.

        # Rendimiento por dividendo (informativo, no entra al score)
        try:
            rendimiento = er.get_etf_fundamentals(etf).get('Yield_%', 0.0)
        except Exception:
            rendimiento = 0.0

        reg = {'Ticker': symbol}
        reg.update(fund)
        reg['Yield_%'] = rendimiento
        return reg
    except Exception:
        return None


# ------------------------------------------------------------------------------
# ACCIONES
# ------------------------------------------------------------------------------
def obtener_metrica_accion(symbol, metadatos):
    """Registro de una acción con datos de Yahoo (info + estados financieros). `metadatos` es el
    respaldo de almacenamiento.cargar_metadatos(). Si falla todo, devuelve un registro de
    emergencia (con 'Score_Final': 0). El rendimiento se calcula aparte con los precios."""
    try:
        stock = yf.Ticker(symbol)
        info = obtener_info(stock)

        dict_stocks = metadatos.get("stocks") or metadatos.get("stock_list") or {}
        fallback = dict_stocks.get(symbol.upper(), {
            'Empresa': symbol, 'Sector': 'General'
        })

        empresa = info.get('shortName') or info.get('longName') or fallback.get('Empresa', symbol)

        sector = info.get('sector') or info.get('industry')
        if not sector or sector in ['General', 'Sin Sector']:
            sector = fallback.get('Sector', 'General')

        # Yahoo respondió con datos reales: los guardamos en la base para la app en línea
        if info and sector not in ['General', 'Sin Sector']:
            almacenamiento.guardar_metadato('stock_list', symbol.upper(), {
                'Empresa': empresa, 'Sector': sector,
                'Industry': info.get('industry') or fallback.get('Industry', 'General')
            })

        # Sin dato de Yahoo -> None ("—" en la tabla), no un +0.00% engañoso
        try:
            raw_52w = info.get('52WeekChange')
            change_52w = round(float(raw_52w) * 100, 2) if raw_52w is not None else None
        except Exception:
            change_52w = None

        try:
            bs = stock.balance_sheet
            cf = stock.cashflow
            fin = stock.financials
        except Exception:
            bs, cf, fin = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        # Columnas informativas (no entran al score): si Yahoo no trae la fila, "sin dato" (None)
        try:
            clave_eq = next((k for k in ['Stockholders Equity', 'Total Equity Gross Minority Interest', 'Common Stock Equity'] if k in bs.index), None)
            cagr_equity = sr.calcular_cagr_serie(bs.loc[clave_eq]) if clave_eq is not None else None
        except Exception:
            cagr_equity = None

        try:
            clave_fcf = next((k for k in ['Free Cash Flow', 'FreeCashFlow'] if k in cf.index), None)
            cagr_fcf = sr.calcular_cagr_serie(cf.loc[clave_fcf]) if clave_fcf is not None else None
        except Exception:
            cagr_fcf = None

        try:
            clave_ebitda = next((k for k in ['Normalized EBITDA', 'EBITDA'] if k in fin.index), None)
            cagr_ebitda = sr.calcular_cagr_serie(fin.loc[clave_ebitda]) if clave_ebitda is not None else None
        except Exception:
            cagr_ebitda = None

        try:
            fund = sr.get_stock_fundamentals(stock) if hasattr(sr, 'get_stock_fundamentals') else {}
        except Exception:
            fund = {}

        # El rendimiento (CAGR, Sortino) se calcula en cargar_datos_acciones a partir de la
        # descarga conjunta de precios.
        reg = {
            'Ticker': symbol,
            'Empresa': empresa,
            'Sector': sector,
            '52W_Change_%': change_52w,
            'CAGR_Equity_%': cagr_equity,
            'CAGR_FCF_%': cagr_fcf,
            'CAGR_EBITDA_%': cagr_ebitda
        }

        if 'Empresa' in fund: del fund['Empresa']
        if 'Sector' in fund: del fund['Sector']

        reg.update(fund)

        return reg
    except Exception:
        return {'Ticker': symbol, 'Score_Final': 0, 'Sector': 'General', 'Empresa': symbol}


def es_registro_de_emergencia(registro):
    """True si obtener_metrica_accion no pudo obtener nada (no conviene guardarlo en la base)."""
    return not registro or 'Score_Final' in registro
