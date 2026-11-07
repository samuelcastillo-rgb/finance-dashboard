# Agent Instructions

## Project Scope

- Streamlit dashboard (`app.py`) that scores ETFs and stocks from Yahoo Finance data, plus a personal portfolio tab.
- Preserve the existing Spanish naming and comments. Keep edits minimal and focused.
- See `README.md` for the folder layout.

## Dependencies and Execution

- Dependencies are pinned in `requirements.txt` (Streamlit, pandas, numpy, plotly, yfinance, SQLAlchemy, psycopg).
- Run the app with `streamlit run app.py` from the repository root.
- Scripts in `scripts/` and tests in `tests/` are run as modules from the root: `python -m scripts.actualizar_datos`, `python -m tests.test_datos_faltantes`.
- Calculation modules (`etf_ratios.py`, `stock_ratios.py`, `portafolio.py`, `datos_mercado.py`) expose functions only; do not add top-level network calls or execution side effects.
- Local data files live in `datos/`; reference them through `almacenamiento.CARPETA_DATOS`, never with cwd-relative paths.

## Coding Conventions

- Follow the existing `snake_case` style and keep public function names unless a rename is requested.
- Missing financial data must be `None`/NaN ("sin dato"), never 0. Run `python -m tests.test_datos_faltantes` after changing ratio calculations.
- Do not commit `__pycache__`, `node_modules`, `venv` or `.streamlit/secrets.toml`.

## Presentation

- UI font: DM Sans with fallback `system-ui, -apple-system, Segoe UI, Roboto, sans-serif`, defined in `app.py`.
- Theme colors come from `.streamlit/config.toml` (light and dark). Avoid hardcoded text/background colors in CSS or Plotly figures so both modes stay readable.
- The TypeScript explorer lives in `componentes/explorador/`; after editing `src/`, run `npm run build` and commit `dist/`.
