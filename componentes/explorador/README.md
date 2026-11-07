# Explorador de métricas (TypeScript)

Componente de Streamlit (`st.components.v2`) que dibuja en SVG una gráfica configurable:
dispersión, barras o histograma, eligiendo eje X, eje Y, color y tamaño desde el navegador.

- `src/explorador.ts`: lógica y dibujo (sin librerías externas).
- `src/explorador.css`: estilos; heredan el tema claro/oscuro de Streamlit.
- `dist/`: versión compilada que carga `explorador.py`. **Se sube al repo** para que
  Streamlit Cloud no necesite Node.

## Modificarlo

```bash
cd componentes/explorador
npm install
npm run typecheck   # revisa tipos con TypeScript
npm run build       # regenera dist/
```

Después reinicia `streamlit run app.py` (el JS se lee al importar `explorador.py`).
