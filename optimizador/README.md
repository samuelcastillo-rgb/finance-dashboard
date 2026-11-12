# Optimizador: frontera eficiente en Rust

Programa de línea de comandos (`frontera`) que calcula la **frontera eficiente de
Markowitz** de una lista de activos. Lo ejecuta el proceso diario
(`scripts/actualizar_datos.py`, a través de `finanzas/frontera.py`) para los ETFs y para las
acciones, y el resultado se guarda en la tabla `fronteras` de la base. La sub-pestaña
**Portafolio óptimo** del dashboard solo lo lee.

## Qué calcula

- **Rendimiento esperado:** media histórica de los últimos 3 años, anualizada.
- **Covarianza:** muestral con contracción de **Ledoit-Wolf** hacia una identidad escalada,
  para que no sea tan ruidosa con muchos activos.
- **Restricciones:** solo compras, pesos que suman 100 % y como máximo 20 % por activo.
- **Frontera:** resuelve `min w'Σw − λ·μ'w` para muchos valores de λ con FISTA (gradiente
  proyectado acelerado) y la proyección exacta al símplex acotado.
- **Carteras destacadas:** mínima volatilidad y máximo Sharpe (tasa libre de riesgo 4 %).

Los resultados coinciden con `scipy.optimize` (SLSQP) a 6 decimales. Con 81 ETFs y 3 años
de datos tarda menos de medio segundo.

## Uso

```bash
cd optimizador
cargo build --release
cargo test
```

```bash
./target/release/frontera < entrada.txt > resultado.json
```

El formato de entrada está documentado en `leer_entrada` (`src/lib.rs`):

```text
tasa_libre 0.04
peso_maximo 0.2
puntos 40
tickers VOO QQQ SCHD
datos
0.0012 -0.0031 0.0004
...
```

La versión de Rust se fija en `rust-toolchain.toml`. No usa dependencias externas.
