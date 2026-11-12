# Agent Instructions

## Project Scope

- Streamlit dashboard (`app.py`) that scores ETFs and stocks from Yahoo Finance data, plus a personal portfolio tab.
- Preserve the existing Spanish naming and comments. Keep edits minimal and focused.
- See `README.md` for the folder layout. `app.py` only wires the page; business logic lives in `finanzas/` and Streamlit UI in `dashboard/` (one module per tab in `dashboard/pestanas/`).
- `dashboard/` may import from `finanzas/`, never the other way around.

## Dependencies and Execution

- Dependencies are pinned in `requirements.txt` (Streamlit, pandas, numpy, plotly, yfinance, SQLAlchemy, psycopg).
- Run the app with `streamlit run app.py` from the repository root.
- Scripts in `scripts/` are run as modules from the root: `python -m scripts.actualizar_datos`.
- Dev tools: `pip install -r requirements-dev.txt`, then `pytest` and `ruff check .` (config in `pyproject.toml`). CI runs both on every PR (`.github/workflows/pruebas.yml`).
- Calculation modules in `finanzas/` (`etf_ratios.py`, `stock_ratios.py`, `score.py`, `portafolio.py`, `montecarlo.py`, `frontera.py`, `datos_mercado.py`) expose functions only; do not add top-level network calls or execution side effects.
- Local data files live in `datos/`; reference them through `finanzas.almacenamiento.CARPETA_DATOS`, never with cwd-relative paths.

## Coding Conventions

- Follow the existing `snake_case` style and keep public function names unless a rename is requested.
- Missing financial data must be `None`/NaN ("sin dato"), never 0. Run `pytest` after changing ratio, score or portfolio calculations, and add a test for new behavior.
- Do not commit `__pycache__`, `node_modules`, `venv` or `.streamlit/secrets.toml`.

## Presentation

- UI font: DM Sans with fallback `system-ui, -apple-system, Segoe UI, Roboto, sans-serif`, defined in `dashboard/estilos.py` and `dashboard/config.py`.
- Theme colors come from `.streamlit/config.toml` (light and dark). Avoid hardcoded text/background colors in CSS or Plotly figures so both modes stay readable.
- The TypeScript explorer lives in `componentes/explorador/`; after editing `src/`, run `npm run build` and commit `dist/`.
- The Monte Carlo simulation lives in `componentes/montecarlo/`: engine in Rust (`rust/src/lib.rs`, compiled to WebAssembly with the toolchain pinned in `rust-toolchain.toml`) and UI in TypeScript (`src/`). After editing either, run `npm test` and `npm run build` there and commit `dist/` (the `.wasm` is embedded in `dist/montecarlo.js`). Input data is prepared by `finanzas/montecarlo.py`.
- The efficient frontier optimizer is a Rust binary in `optimizador/` (`cargo build --release` there; `cargo test`, `cargo clippy --all-targets -- -D warnings`, `cargo fmt --check`). The daily job runs it through `finanzas/frontera.py` and stores the result in the `fronteras` table; `dashboard/frontera.py` only reads it.
