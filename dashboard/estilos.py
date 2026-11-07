"""CSS global de la app.

Tipografía de la UI: DM Sans (Google Fonts). Fallback: system-ui, -apple-system,
'Segoe UI', Roboto, sans-serif.
"""
import streamlit as st

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;800&display=swap');

/* Los colores de fondo, texto, pestañas, botones y barra lateral vienen del tema
   (.streamlit/config.toml), que tiene versión clara y oscura. Aquí NO se fijan colores
   de fondo ni de texto: los estilos propios se calculan a partir del color del texto
   (currentColor), así que se ven bien en los dos modos. */
:root { --verde: #1dbe83; --ambar: #F59E0B; --rojo: #EF4444; }

/* Fuente general de la app */
html, body, [class*="css"], .stApp {
    font-family: 'DM Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif !important;
}

.block-container { padding-top: 4.5rem !important; max-width: 1600px; }
footer { visibility: hidden; }

/* Títulos principales */
h1, h2, h3, h4, h5, h6 {
    font-family: 'DM Sans', system-ui, sans-serif !important;
    font-weight: 800 !important;
}

/* Pestañas: solo tamaño y grosor; el color lo pone el tema */
[data-testid="stTab"] p { font-size: 15px !important; font-weight: 700 !important; }
[data-testid="stTab"][aria-selected="true"] { color: inherit !important; }
[data-testid="stTab"][aria-selected="true"] p {
    color: color-mix(in srgb, var(--verde) 75%, currentColor) !important;
    font-weight: 800 !important;
}

/* Barra lateral: solo la fuente (los colores vienen de [theme.*.sidebar]) */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] .stCaption {
    font-family: 'DM Sans', system-ui, sans-serif !important;
}
.separador-lateral { margin: 15px 0; border: 0; border-top: 1px solid color-mix(in srgb, currentColor 25%, transparent); }

/* RESTAURAR FUENTE DE ICONOS DE STREAMLIT (MATERIAL SYMBOLS) */
[data-testid="stIconMaterial"],
.material-symbols-rounded,
.material-icons,
[data-testid="stSidebar"] [data-testid="stIconMaterial"],
[data-testid="stSidebar"] span[translate="no"] {
    font-family: "Material Symbols Rounded", "Material Symbols Outlined", "Material Icons" !important;
}

/* Colores derivados del texto: funcionan sobre fondo claro y oscuro */
.app-header, .kpi-card, .leader-card, .app-stamp, .bar {
    --suave: color-mix(in srgb, currentColor 62%, transparent);
    --linea: color-mix(in srgb, currentColor 14%, transparent);
    --superficie: color-mix(in srgb, currentColor 4%, transparent);
}

/* Encabezado de la app */
.app-header {
    display: flex; justify-content: space-between; align-items: flex-end;
    gap: 16px; margin-bottom: 14px; flex-wrap: wrap;
}
.app-title { font-size: 30px; font-weight: 800; line-height: 1.1; }
.app-subtitle { font-size: 14px; color: var(--suave); margin-top: 4px; }
.app-stamp {
    font-size: 12px; font-weight: 700; color: var(--suave); background: var(--superficie);
    border: 1px solid var(--linea); border-radius: 999px; padding: 5px 12px;
}

/* Títulos de sección dentro de tarjetas */
.section-title { font-size: 16px; font-weight: 800; margin-bottom: 2px; }
.section-help { font-size: 12.5px; opacity: .68; margin-bottom: 8px; }

/* Tarjetas KPI */
.kpi-card {
    background-color: var(--superficie); padding: 16px 14px; border-radius: 14px;
    border: 1px solid var(--linea); border-top: 4px solid var(--verde);
    box-shadow: 0px 4px 12px rgba(15, 23, 42, 0.04); text-align: center;
}
.kpi-title { font-size: 11.5px; color: var(--suave); font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
.kpi-value { font-size: 26px; font-weight: 800; line-height: 1.25; }
.kpi-sub { font-size: 13px; color: color-mix(in srgb, var(--verde) 70%, currentColor); font-weight: 700; margin-top: 2px; }

/* Píldoras de nivel de score (el color nunca es el único indicador: lleva texto).
   Fondo translúcido del color y texto mezclado con el color del tema: se oscurece en
   modo claro y se aclara en modo oscuro, con buen contraste en ambos. */
.pill { display: inline-block; font-size: 12px; font-weight: 800; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
.pill-excelente { background: color-mix(in srgb, var(--verde) 24%, transparent); color: color-mix(in srgb, var(--verde) 55%, currentColor); }
.pill-bueno { background: color-mix(in srgb, var(--verde) 10%, transparent); color: color-mix(in srgb, var(--verde) 65%, currentColor);
              border: 1px solid color-mix(in srgb, var(--verde) 40%, transparent); }
.pill-neutral { background: color-mix(in srgb, var(--ambar) 20%, transparent); color: color-mix(in srgb, var(--ambar) 55%, currentColor); }
.pill-debil { background: color-mix(in srgb, var(--rojo) 18%, transparent); color: color-mix(in srgb, var(--rojo) 60%, currentColor); }

/* Tarjetas de líderes con barra de score */
.leader-card {
    background-color: var(--superficie); padding: 12px 16px; border-radius: 12px;
    margin-bottom: 10px; border: 1px solid var(--linea); border-left: 5px solid var(--verde);
}
.leader-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.leader-ticker { font-size: 16px; font-weight: 800; }
.leader-sub { font-size: 12px; color: var(--suave); margin-top: 2px; }
.bar { height: 6px; background: var(--linea); border-radius: 999px; margin-top: 8px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; }
.bar-excelente { background: var(--verde); }
.bar-bueno { background: #6EE7B7; }
.bar-neutral { background: var(--ambar); }
.bar-debil { background: var(--rojo); }

.inspector-ticker { font-size: 24px; font-weight: 800; margin-right: 8px; }
</style>"""


def aplicar_estilos():
    st.markdown(CSS, unsafe_allow_html=True)
