# Finance Quantitative Dashboard

Dashboard en Streamlit que califica ETFs y acciones con un score cuantitativo
(percentiles dentro de tu universo) y lleva el control de tu portafolio personal.

App publicada: https://finance-dashboard-sam.streamlit.app

## Estructura

```
├── app.py                    Punto de entrada: solo arma la página
├── finanzas/                 Lógica de negocio (sin interfaz)
│   ├── score.py              Fórmula del score, percentiles y cobertura
│   ├── etf_ratios.py         Métricas de ETFs
│   ├── stock_ratios.py       Métricas fundamentales de acciones
│   ├── datos_mercado.py      Consultas a Yahoo Finance (app y scripts)
│   ├── almacenamiento.py     Postgres (Neon) o respaldo en datos/*.json
│   └── portafolio.py         Cálculos del portafolio personal
├── dashboard/                Interfaz de Streamlit
│   ├── config.py             Paleta, columnas del explorador, tickers por defecto
│   ├── estilos.py            CSS global
│   ├── carga.py              Carga de datos con caché (base + Yahoo en vivo)
│   ├── barra_lateral.py      Gestor de tickers y filtros
│   ├── graficos.py           Figuras de Plotly
│   ├── tarjetas.py           KPIs, tarjetas, tablas e inspector
│   ├── formato.py            Formato de números
│   ├── explorador.py         Puente Python del explorador (TypeScript)
│   └── pestanas/             etfs.py, acciones.py, portafolio.py
├── componentes/explorador/   Código TypeScript del explorador (src/ y dist/ compilado)
├── scripts/                  Procesos que se corren a mano o desde GitHub Actions
├── datos/                    Respaldo local: lista de tickers y metadatos
├── tests/                    Pruebas sin red
├── .streamlit/config.toml    Tema claro/oscuro (secrets.toml NO se sube)
└── .github/workflows/        Actualización diaria de datos
```

Regla de dependencias: `dashboard/` puede importar de `finanzas/`, nunca al revés.
`finanzas/` no dibuja nada (solo `almacenamiento.py` usa `st.secrets`/`st.connection` para leer la base).

## Correr en local

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

Sin `.streamlit/secrets.toml` la app funciona igual, leyendo `datos/` y consultando a Yahoo en vivo.
Con la sección `[connections.postgresql]` lee los datos ya calculados de la base.

## Scripts

Se ejecutan **desde la carpeta raíz del proyecto** con `python -m` para que encuentren los módulos:

| Comando | Qué hace |
|---|---|
| `python -m scripts.actualizar_datos` | Proceso diario: precios y métricas a la base (lo corre la GitHub Action) |
| `python -m scripts.actualizar_metadatos` | Regenera `datos/metadata_cache.json` (nombre, categoría, sector) |
| `python -m scripts.sp500_extraction` | Lista de mayores alzas y bajas del S&P 500 contra su media de 50 días |
| `python -m tests.test_datos_faltantes` | Prueba que los datos faltantes salgan como "sin dato" y no como 0 |
