import json
import time
import yfinance as yf

import almacenamiento

# Cargar listas actuales: de la base de datos si está configurada
# (.streamlit/secrets.toml) o, si no, de portfolio_tickers.json.
# Ejecutar desde la carpeta del proyecto: python actualizar_metadatos.py
datos = almacenamiento.cargar_tickers({"etf_list": [], "stock_list": []})

etfs = datos.get("etf_list", [])
stocks = datos.get("stock_list", [])

cache = {"etf_list": {}, "stock_list": {}}

print(f"Descargando metadatos de {len(etfs)} ETFs...")
for t in etfs:
    try:
        info = yf.Ticker(t).info or {}
        exp = info.get('netExpenseRatio') or info.get('annualReportExpenseRatio') or info.get('expenseRatio') or 0.0
        exp_f = float(exp)
        cache["etf_list"][t] = {
            "Nombre": info.get("shortName") or info.get("longName") or t,
            "Category": info.get("category") or info.get("legalType") or "General",
            "Expense_Ratio_%": round(exp_f * 100, 3) if 0 < exp_f < 0.005 else round(exp_f, 3),
            "AUM_BUSD": round((info.get("totalAssets") or 0) / 1e9, 2)
        }
    except Exception as e:
        print(f"Error en ETF {t}: {e}")
    time.sleep(0.1)

print(f"Descargando metadatos de {len(stocks)} Acciones...")
for s in stocks:
    try:
        info = yf.Ticker(s).info or {}
        cache["stock_list"][s] = {
            "Empresa": info.get("shortName") or info.get("longName") or s,
            "Sector": info.get("sector") or "General",
            "Industry": info.get("industry") or "General"
        }
    except Exception as e:
        print(f"Error en Acción {s}: {e}")
    time.sleep(0.1)

# Guardar automáticamente en disco
with open("metadata_cache.json", "w", encoding="utf-8") as f:
    json.dump(cache, f, indent=4, ensure_ascii=False)

# Y en la base de datos, para que la app en línea los tenga aunque Yahoo la bloquee
almacenamiento.guardar_metadatos(cache)

print("¡Listo! metadata_cache.json generado exitosamente.")