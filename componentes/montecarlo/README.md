# Simulación Monte Carlo (Rust + WebAssembly + TypeScript)

Componente de Streamlit que simula miles de escenarios del valor de tu portafolio,
en la pestaña **Mi portafolio**.

| Parte | Lenguaje | Archivo |
|---|---|---|
| Motor de simulación | Rust → WebAssembly | `rust/src/lib.rs` |
| Interfaz y gráficas (SVG) | TypeScript | `src/montecarlo.ts`, `src/montecarlo.css` |
| Datos de entrada | Python | `finanzas/montecarlo.py` |
| Registro en Streamlit | Python | `dashboard/montecarlo.py` |

Python manda los rendimientos diarios históricos y los pesos de cada ticker. El navegador
ejecuta el motor de Rust, así que cambiar el horizonte, el número de escenarios o el modelo
recalcula al instante sin volver al servidor.

## Modelos

- **Días históricos (bootstrap):** cada día simulado copia un día real completo de los
  últimos 5 años (todos los tickers a la vez). Conserva las caídas fuertes y la
  correlación entre activos.
- **Normal multivariada:** rendimientos logarítmicos normales con la media y la covarianza
  históricas (Cholesky). Más suave en las colas.

Ambos suponen compra y mantén (sin rebalanceo, aportes ni retiros). Los precios son
ajustados, así que incluyen dividendos reinvertidos. No es una predicción: supone que el
futuro se parece al pasado.

## Compilar

Requiere [Rust](https://rustup.rs) (la versión se fija en `rust-toolchain.toml`) y Node 22.

```bash
cd componentes/montecarlo
npm install
npm test          # pruebas de Rust (cargo test)
npm run build     # Rust -> .wasm, y TypeScript + .wasm -> dist/montecarlo.js
```

El `.wasm` queda incrustado en `dist/montecarlo.js`, que se sube al repositorio: Streamlit
Cloud no necesita Rust ni Node. CI vuelve a compilar y falla si `dist/` no coincide.
