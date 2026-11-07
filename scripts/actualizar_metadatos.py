import json
import time
import yfinance as yf

import almacenamiento

ARCH_METADATOS = almacenamiento.ARCH_METADATOS


def _info_real(simbolo):
    """`info` de Yahoo, o {} si Yahoo no respondió con datos (bloqueo, límite, error)."""
    try:
        info = yf.Ticker(simbolo).info or {}
    except Exception as e:
        print(f"  Error en {simbolo}: {e}")
        return {}
    # Una respuesta bloqueada suele traer solo un par de claves sin datos
    return info if len(info) > 5 else {}


def actualizar_metadatos(escribir_json=True):
    """Descarga nombre, categoría/sector, expense ratio y AUM de todos los tickers.

    Solo guarda los tickers para los que Yahoo respondió con datos reales, para no
    pisar metadatos buenos con "General" cuando Yahoo bloquea (por ejemplo, en la nube).
    Devuelve (n_ok, n_total)."""
    # Listas actuales: de la base de datos si está configurada
    # (.streamlit/secrets.toml) o, si no, de portfolio_tickers.json.
    datos = almacenamiento.cargar_tickers({"etf_list": [], "stock_list": []})
    etfs = datos.get("etf_list", [])
    stocks = datos.get("stock_list", [])

    cache = {"etf_list": {}, "stock_list": {}}

    print(f"Descargando metadatos de {len(etfs)} ETFs...")
    for t in etfs:
        info = _info_real(t)
        if info:
            exp = info.get('netExpenseRatio') or info.get('annualReportExpenseRatio') or info.get('expenseRatio') or 0.0
            exp_f = float(exp)
            cache["etf_list"][t] = {
                "Nombre": info.get("shortName") or info.get("longName") or t,
                "Category": info.get("category") or info.get("legalType") or "General",
                "Expense_Ratio_%": round(exp_f * 100, 3) if 0 < exp_f < 0.005 else round(exp_f, 3),
                "AUM_BUSD": round((info.get("totalAssets") or 0) / 1e9, 2)
            }
        time.sleep(0.1)

    print(f"Descargando metadatos de {len(stocks)} Acciones...")
    for s in stocks:
        info = _info_real(s)
        if info:
            cache["stock_list"][s] = {
                "Empresa": info.get("shortName") or info.get("longName") or s,
                "Sector": info.get("sector") or "General",
                "Industry": info.get("industry") or "General"
            }
        time.sleep(0.1)

    n_ok = len(cache["etf_list"]) + len(cache["stock_list"])
    n_total = len(etfs) + len(stocks)

    if escribir_json:
        # Se combina con el archivo existente: los tickers que fallaron conservan su dato anterior
        try:
            with open(ARCH_METADATOS, "r", encoding="utf-8") as f:
                anterior = json.load(f)
        except Exception:
            anterior = {}
        combinado = {clave: {**anterior.get(clave, {}), **cache[clave]} for clave in cache}
        with open(ARCH_METADATOS, "w", encoding="utf-8") as f:
            json.dump(combinado, f, indent=4, ensure_ascii=False)

    # Y en la base de datos, para que la app en línea los tenga aunque Yahoo la bloquee
    almacenamiento.guardar_metadatos(cache)

    print(f"Metadatos obtenidos: {n_ok} de {n_total} tickers.")
    return n_ok, n_total


if __name__ == "__main__":
    # Ejecutar desde la carpeta del proyecto: python -m scripts.actualizar_metadatos
    actualizar_metadatos()
    print("¡Listo! metadata_cache.json generado exitosamente.")
