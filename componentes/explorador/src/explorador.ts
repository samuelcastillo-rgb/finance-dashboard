// Explorador de métricas para Streamlit (st.components.v2).
//
// Python manda una tabla (columnas + filas) y el usuario elige en el navegador
// qué graficar: tipo de gráfica, eje X, eje Y, color y tamaño. Todo se dibuja en
// SVG sin librerías externas, así que el bundle pesa unos pocos KB y los colores
// salen del tema activo de Streamlit (modo claro u oscuro).
//
// Compilar:  npm install && npm run build   ->  dist/explorador.js

// ----------------------------------------------------------------------------
// Tipos del contrato con Python
// ----------------------------------------------------------------------------
type TipoColumna = "num" | "cat";

interface Columna {
  id: string;
  etiqueta: string;
  tipo: TipoColumna;
  sufijo?: string;
  decimales?: number;
}

type Valor = number | string | null;
type Fila = Record<string, Valor>;

type TipoGrafica = "dispersion" | "barras" | "histograma";
type Calculo = "promedio" | "mediana" | "suma" | "conteo";

interface Config {
  tipo: TipoGrafica;
  x: string;
  y: string;
  color: string; // "" = sin color
  tamano: string; // "" = sin tamaño
  calculo: Calculo;
  etiquetas: boolean;
  tendencia: boolean;
}

interface Datos {
  columnas: Columna[];
  filas: Fila[];
  id_col: string;
  nombre_col?: string;
  inicial?: Partial<Config>;
}

interface Componente {
  data: Datos;
  key: string;
  parentElement: HTMLElement | ShadowRoot;
}

// La selección del usuario vive aquí: el módulo se carga una sola vez por sesión
// del navegador, así que sobrevive a los reruns de Streamlit sin forzar otro rerun.
const memoria = new Map<string, Config>();

// ----------------------------------------------------------------------------
// Colores
// ----------------------------------------------------------------------------
// Paleta categórica validada (orden fijo, nunca cíclica). Pasos claro/oscuro.
const CATEGORICA = {
  claro: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  oscuro: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};
const COLOR_OTROS = "#94a3b8";
// Score: misma escala que el resto del dashboard (riesgo -> alerta -> verde).
const ESCALA_SCORE = ["#EF4444", "#F59E0B", "#1dbe83"];
// Otras métricas: secuencial de un solo tono (azul), de suave a intenso.
const ESCALA_SECUENCIAL = {
  claro: ["#cfe1f7", "#2a78d6", "#0d3f80"],
  oscuro: ["#123a66", "#3987e5", "#b9d6f7"],
};
const MAX_CATEGORIAS = 8;
const MAX_BARRAS = 25;

function hexARgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function interpolar(escala: string[], t: number): string {
  const u = Math.min(1, Math.max(0, t)) * (escala.length - 1);
  const i = Math.min(escala.length - 2, Math.floor(u));
  const a = hexARgb(escala[i]);
  const b = hexARgb(escala[i + 1]);
  const f = u - i;
  const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

// Modo oscuro = el texto heredado de Streamlit es claro.
function esOscuro(el: Element): boolean {
  const m = getComputedStyle(el).color.match(/\d+(\.\d+)?/g);
  if (!m) return false;
  const [r, g, b] = m.map(Number);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
}

// ----------------------------------------------------------------------------
// Utilidades numéricas
// ----------------------------------------------------------------------------
function esNumero(v: Valor): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function mediana(vals: number[]): number {
  const s = [...vals].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function agregar(vals: number[], calculo: Calculo): number {
  if (calculo === "conteo") return vals.length;
  if (calculo === "suma") return vals.reduce((a, b) => a + b, 0);
  if (calculo === "mediana") return mediana(vals);
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

// Correlación de Pearson y recta de mínimos cuadrados.
function regresion(xs: number[], ys: number[]) {
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) {
    sxy += (xs[i] - mx) * (ys[i] - my);
    sxx += (xs[i] - mx) ** 2;
    syy += (ys[i] - my) ** 2;
  }
  const pendiente = sxx ? sxy / sxx : 0;
  return { pendiente, corte: my - pendiente * mx, r: sxx && syy ? sxy / Math.sqrt(sxx * syy) : NaN };
}

// Marcas "redondas" para un eje (1, 2, 2.5, 5 × 10^k).
function marcas(min: number, max: number, cuantas = 5): number[] {
  if (min === max) { min -= 1; max += 1; }
  const paso0 = (max - min) / cuantas;
  const pot = 10 ** Math.floor(Math.log10(paso0));
  const paso = [1, 2, 2.5, 5, 10].map((f) => f * pot).find((p) => p >= paso0) ?? 10 * pot;
  const res: number[] = [];
  for (let v = Math.ceil(min / paso) * paso; v <= max + paso * 1e-9; v += paso) res.push(+v.toFixed(10));
  return res;
}

function dominio(vals: number[], incluirCero = false, margen = 0): [number, number] {
  let lo = Math.min(...vals), hi = Math.max(...vals);
  // Margen relativo para que los puntos grandes no se corten en los bordes.
  const holgura = (hi - lo) * margen;
  lo -= holgura;
  hi += holgura;
  if (incluirCero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (lo === hi) { lo -= 1; hi += 1; }
  const m = marcas(lo, hi);
  return [Math.min(lo, m[0]), Math.max(hi, m[m.length - 1])];
}

function escalaLineal(d: [number, number], r: [number, number]) {
  return (v: number) => r[0] + ((v - d[0]) / (d[1] - d[0])) * (r[1] - r[0]);
}

// ----------------------------------------------------------------------------
// DOM / SVG
// ----------------------------------------------------------------------------
const SVG_NS = "http://www.w3.org/2000/svg";

function svg<K extends keyof SVGElementTagNameMap>(
  tag: K, attrs: Record<string, string | number> = {}, padre?: Element,
): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  padre?.appendChild(el);
  return el;
}

function html<K extends keyof HTMLElementTagNameMap>(
  tag: K, clase = "", texto = "", padre?: Element,
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (clase) el.className = clase;
  if (texto) el.textContent = texto;
  padre?.appendChild(el);
  return el;
}

function selector(
  padre: Element, etiqueta: string, opciones: [string, string][], valor: string,
  alCambiar: (v: string) => void,
): void {
  const caja = html("label", "campo", "", padre);
  html("span", "campo-titulo", etiqueta, caja);
  const sel = html("select", "", "", caja);
  for (const [v, t] of opciones) {
    const op = html("option", "", t, sel);
    op.value = v;
  }
  sel.value = opciones.some(([v]) => v === valor) ? valor : opciones[0]?.[0] ?? "";
  sel.addEventListener("change", () => alCambiar(sel.value));
}

function casilla(padre: Element, etiqueta: string, valor: boolean, alCambiar: (v: boolean) => void): void {
  const caja = html("label", "casilla", "", padre);
  const inp = html("input", "", "", caja);
  inp.type = "checkbox";
  inp.checked = valor;
  inp.addEventListener("change", () => alCambiar(inp.checked));
  html("span", "", etiqueta, caja);
}

// ----------------------------------------------------------------------------
// Componente
// ----------------------------------------------------------------------------
export default function explorador(componente: Componente): () => void {
  const { data, key, parentElement } = componente;
  const columnas = data.columnas;
  const porId = new Map(columnas.map((c) => [c.id, c]));
  const numericas = columnas.filter((c) => c.tipo === "num");
  const categoricas = columnas.filter((c) => c.tipo === "cat");
  const idCol = data.id_col;

  const fmt = (colId: string, v: Valor): string => {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "string") return v;
    const c = porId.get(colId);
    const dec = c?.decimales ?? 2;
    return v.toLocaleString("es-MX", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + (c?.sufijo ?? "");
  };
  const fmtEje = (colId: string, v: number): string => {
    const c = porId.get(colId);
    const abs = Math.abs(v);
    const dec = abs >= 100 || Number.isInteger(v) ? 0 : abs >= 10 ? 1 : 2;
    return v.toLocaleString("es-MX", { maximumFractionDigits: dec }) + (c?.sufijo ?? "");
  };
  const etiqueta = (id: string) => porId.get(id)?.etiqueta ?? id;

  // Configuración inicial: memoria del navegador > sugerencia de Python > primeras columnas.
  const base: Config = {
    tipo: "dispersion",
    x: numericas[1]?.id ?? numericas[0]?.id ?? "",
    y: numericas[0]?.id ?? "",
    color: "",
    tamano: "",
    calculo: "promedio",
    etiquetas: true,
    tendencia: false,
    ...data.inicial,
  };
  const cfg: Config = { ...base, ...memoria.get(key) };
  const guardar = () => memoria.set(key, { ...cfg });

  // Estructura fija: barra de controles, resumen, lienzo y tooltip.
  const raiz = html("div", "explorador");
  parentElement.appendChild(raiz);
  const controles = html("div", "controles", "", raiz);
  const resumen = html("div", "resumen", "", raiz);
  const lienzo = html("div", "lienzo", "", raiz);
  const leyenda = html("div", "leyenda", "", raiz);
  const tooltip = html("div", "tooltip", "", raiz);

  let ancho = 0;
  let oscuro = esOscuro(raiz);

  // --- Tooltip -------------------------------------------------------------
  const mostrarTooltip = (ev: MouseEvent, titulo: string, lineas: [string, string][]) => {
    tooltip.replaceChildren();
    html("div", "tt-titulo", titulo, tooltip);
    for (const [k, v] of lineas) {
      const fila = html("div", "tt-fila", "", tooltip);
      html("span", "tt-k", k, fila);
      html("span", "tt-v", v, fila);
    }
    tooltip.style.display = "block";
    const caja = raiz.getBoundingClientRect();
    const tt = tooltip.getBoundingClientRect();
    let x = ev.clientX - caja.left + 14;
    let y = ev.clientY - caja.top + 14;
    if (x + tt.width > caja.width) x = ev.clientX - caja.left - tt.width - 14;
    if (y + tt.height > caja.height) y = ev.clientY - caja.top - tt.height - 14;
    tooltip.style.left = `${Math.max(0, x)}px`;
    tooltip.style.top = `${Math.max(0, y)}px`;
  };
  const ocultarTooltip = () => { tooltip.style.display = "none"; };

  const lineasFila = (f: Fila, ids: string[]): [string, string][] => {
    const vistos = new Set<string>();
    const res: [string, string][] = [];
    for (const id of ids) {
      if (!id || vistos.has(id) || id === idCol) continue;
      vistos.add(id);
      res.push([etiqueta(id), fmt(id, f[id])]);
    }
    return res;
  };
  const tituloFila = (f: Fila) => {
    const nombre = data.nombre_col ? f[data.nombre_col] : null;
    return nombre ? `${f[idCol]} · ${nombre}` : String(f[idCol]);
  };

  // --- Controles -----------------------------------------------------------
  const pintarControles = () => {
    controles.replaceChildren();
    const optsNum: [string, string][] = numericas.map((c) => [c.id, c.etiqueta]);
    const optsCat: [string, string][] = categoricas.map((c) => [c.id, c.etiqueta]);
    const cambiar = <K extends keyof Config>(k: K) => (v: Config[K]) => {
      cfg[k] = v;
      guardar();
      pintarTodo();
    };

    selector(controles, "Gráfica", [["dispersion", "Dispersión"], ["barras", "Barras"], ["histograma", "Histograma"]],
      cfg.tipo, (v) => {
        cfg.tipo = v as TipoGrafica;
        // Al cambiar de tipo, el eje X debe ser del tipo de dato correcto.
        if (cfg.tipo === "barras" && porId.get(cfg.x)?.tipo !== "cat") cfg.x = idCol;
        if (cfg.tipo !== "barras" && porId.get(cfg.x)?.tipo !== "num") cfg.x = numericas[0]?.id ?? "";
        if (cfg.tipo === "histograma" && porId.get(cfg.y)) cfg.x = cfg.y;
        guardar();
        pintarTodo();
      });

    if (cfg.tipo === "dispersion") {
      selector(controles, "Eje X", optsNum, cfg.x, cambiar("x"));
      selector(controles, "Eje Y", optsNum, cfg.y, cambiar("y"));
      selector(controles, "Color", [["", "Sin color"], ...optsCat.filter(([v]) => v !== idCol), ...optsNum],
        cfg.color, cambiar("color"));
      selector(controles, "Tamaño", [["", "Uniforme"], ...optsNum], cfg.tamano, cambiar("tamano"));
      casilla(controles, "Etiquetas", cfg.etiquetas, cambiar("etiquetas"));
      casilla(controles, "Tendencia", cfg.tendencia, cambiar("tendencia"));
    } else if (cfg.tipo === "barras") {
      selector(controles, "Agrupar por", optsCat, cfg.x, cambiar("x"));
      selector(controles, "Valor", optsNum, cfg.y, cambiar("y"));
      if (cfg.x !== idCol) {
        selector(controles, "Cálculo",
          [["promedio", "Promedio"], ["mediana", "Mediana"], ["suma", "Suma"], ["conteo", "Conteo"]],
          cfg.calculo, (v) => cambiar("calculo")(v as Calculo));
      } else {
        selector(controles, "Color", [["", "Sin color"], ...optsCat.filter(([v]) => v !== idCol), ...optsNum],
          cfg.color, cambiar("color"));
      }
    } else {
      selector(controles, "Métrica", optsNum, cfg.x, cambiar("x"));
    }
  };

  // --- Codificación de color (categórica o secuencial) ----------------------
  type Pintor = { color: (f: Fila) => string; leyenda: () => void };
  const crearPintor = (filas: Fila[]): Pintor => {
    const primario = oscuro ? "#2fd398" : "#159a6a";
    const col = porId.get(cfg.color);
    if (!col) return { color: () => primario, leyenda: () => leyenda.replaceChildren() };

    if (col.tipo === "cat") {
      // Categorías por frecuencia; las que no caben en 8 colores van a "Otros".
      const cuenta = new Map<string, number>();
      for (const f of filas) {
        const v = String(f[col.id] ?? "Sin dato");
        cuenta.set(v, (cuenta.get(v) ?? 0) + 1);
      }
      const orden = [...cuenta.keys()].sort((a, b) => cuenta.get(b)! - cuenta.get(a)! || a.localeCompare(b));
      const hayOtros = orden.length > MAX_CATEGORIAS;
      const visibles = hayOtros ? orden.slice(0, MAX_CATEGORIAS - 1) : orden;
      // El color sigue a la categoría (orden alfabético), no a su ranking.
      const paleta = oscuro ? CATEGORICA.oscuro : CATEGORICA.claro;
      const asignado = new Map([...visibles].sort((a, b) => a.localeCompare(b)).map((v, i) => [v, paleta[i]]));
      const color = (f: Fila) => asignado.get(String(f[col.id] ?? "Sin dato")) ?? COLOR_OTROS;
      return {
        color,
        leyenda: () => {
          leyenda.replaceChildren();
          html("span", "leyenda-titulo", col.etiqueta, leyenda);
          const items: [string, string][] = [...asignado.entries()];
          if (hayOtros) items.push([`Otros (${orden.length - visibles.length})`, COLOR_OTROS]);
          for (const [nombre, c] of items) {
            const it = html("span", "leyenda-item", "", leyenda);
            const p = html("span", "punto", "", it);
            p.style.background = c;
            html("span", "", nombre, it);
          }
        },
      };
    }

    const vals = filas.map((f) => f[col.id]).filter(esNumero);
    const lo = vals.length ? Math.min(...vals) : 0;
    const hi = vals.length ? Math.max(...vals) : 1;
    const esScore = col.id === "Score_Final";
    const escala = esScore ? ESCALA_SCORE : oscuro ? ESCALA_SECUENCIAL.oscuro : ESCALA_SECUENCIAL.claro;
    const [a, b] = esScore ? [0, 100] : [lo, hi];
    return {
      color: (f) => (esNumero(f[col.id]) ? interpolar(escala, (Number(f[col.id]) - a) / (b - a || 1)) : COLOR_OTROS),
      leyenda: () => {
        leyenda.replaceChildren();
        html("span", "leyenda-titulo", col.etiqueta, leyenda);
        html("span", "", fmtEje(col.id, a), leyenda);
        const barra = html("span", "gradiente", "", leyenda);
        barra.style.background = `linear-gradient(90deg, ${escala.join(", ")})`;
        html("span", "", fmtEje(col.id, b), leyenda);
      },
    };
  };

  // --- Ejes compartidos ----------------------------------------------------
  const ejeY = (g: SVGGElement, ticks: number[], y: (v: number) => number, x0: number, x1: number, col: string) => {
    for (const t of ticks) {
      svg("line", { x1: x0, x2: x1, y1: y(t), y2: y(t), class: t === 0 ? "cero" : "rejilla" }, g);
      const tx = svg("text", { x: x0 - 8, y: y(t), class: "tick", "text-anchor": "end", "dominant-baseline": "middle" }, g);
      tx.textContent = fmtEje(col, t);
    }
  };
  const ejeX = (g: SVGGElement, ticks: number[], x: (v: number) => number, y0: number, y1: number, col: string) => {
    for (const t of ticks) {
      svg("line", { x1: x(t), x2: x(t), y1: y0, y2: y1, class: t === 0 ? "cero" : "rejilla" }, g);
      const tx = svg("text", { x: x(t), y: y1 + 18, class: "tick", "text-anchor": "middle" }, g);
      tx.textContent = fmtEje(col, t);
    }
  };
  const tituloEje = (g: SVGGElement, texto: string, x: number, y: number, vertical = false) => {
    const t = svg("text", { x, y, class: "titulo-eje", "text-anchor": "middle" }, g);
    if (vertical) t.setAttribute("transform", `rotate(-90 ${x} ${y})`);
    t.textContent = texto;
  };

  // --- Dispersión ----------------------------------------------------------
  const dibujarDispersion = () => {
    const validas = data.filas.filter((f) => esNumero(f[cfg.x]) && esNumero(f[cfg.y]));
    const omitidas = data.filas.length - validas.length;
    if (validas.length < 2) return sinDatos(validas.length, omitidas);

    const xs = validas.map((f) => f[cfg.x] as number);
    const ys = validas.map((f) => f[cfg.y] as number);
    const alto = 440;
    const m = { izq: 64, der: 20, arr: 16, aba: 52 };
    const [dx, dy] = [dominio(xs, false, 0.06), dominio(ys, false, 0.08)];
    const x = escalaLineal(dx, [m.izq, ancho - m.der]);
    const y = escalaLineal(dy, [alto - m.aba, m.arr]);

    const reg = regresion(xs, ys);
    resumen.textContent = `${validas.length} puntos` +
      (omitidas ? ` · ${omitidas} sin dato omitidos` : "") +
      (Number.isFinite(reg.r) ? ` · correlación r = ${reg.r.toFixed(2)}` : "");

    const s = svg("svg", { width: ancho, height: alto, role: "img" }, lienzo);
    const g = svg("g", {}, s);
    ejeY(g, marcas(dy[0], dy[1]), y, m.izq, ancho - m.der, cfg.y);
    ejeX(g, marcas(dx[0], dx[1], Math.max(3, Math.floor(ancho / 110))), x, m.arr, alto - m.aba, cfg.x);
    tituloEje(g, etiqueta(cfg.x), (m.izq + ancho - m.der) / 2, alto - 10);
    tituloEje(g, etiqueta(cfg.y), 14, (m.arr + alto - m.aba) / 2, true);

    // Medianas: dividen el gráfico en cuadrantes.
    const mx = mediana(xs), my = mediana(ys);
    svg("line", { x1: x(mx), x2: x(mx), y1: m.arr, y2: alto - m.aba, class: "mediana" }, g);
    svg("line", { x1: m.izq, x2: ancho - m.der, y1: y(my), y2: y(my), class: "mediana" }, g);

    if (cfg.tendencia && Number.isFinite(reg.r)) {
      const yA = reg.corte + reg.pendiente * dx[0];
      const yB = reg.corte + reg.pendiente * dx[1];
      const clip = svg("clipPath", { id: `clip-${key}` }, s);
      svg("rect", { x: m.izq, y: m.arr, width: ancho - m.izq - m.der, height: alto - m.arr - m.aba }, clip);
      svg("line", { x1: x(dx[0]), x2: x(dx[1]), y1: y(yA), y2: y(yB), class: "tendencia", "clip-path": `url(#clip-${key})` }, g);
    }

    const pintor = crearPintor(validas);
    pintor.leyenda();
    const colTam = porId.get(cfg.tamano);
    const tams = colTam ? validas.map((f) => f[colTam.id]).filter(esNumero) : [];
    const tMax = tams.length ? Math.max(...tams.map(Math.abs)) : 1;
    // Área proporcional al valor: radio = sqrt.
    const radio = (f: Fila) => (colTam && esNumero(f[colTam.id]) ? 5 + 17 * Math.sqrt(Math.abs(Number(f[colTam.id])) / (tMax || 1)) : 6);

    // Los puntos grandes se dibujan primero para que los chicos queden encima.
    const orden = [...validas].sort((a, b) => radio(b) - radio(a));
    const capa = svg("g", {}, s);
    for (const f of orden) {
      const c = svg("circle", {
        cx: x(f[cfg.x] as number), cy: y(f[cfg.y] as number), r: radio(f),
        fill: pintor.color(f), class: "punto-svg",
      }, capa);
      c.addEventListener("mousemove", (ev) =>
        mostrarTooltip(ev, tituloFila(f), lineasFila(f, [cfg.x, cfg.y, cfg.color, cfg.tamano])));
      c.addEventListener("mouseleave", ocultarTooltip);
    }

    // Etiquetas selectivas: solo los extremos y el mejor score, sin saturar.
    if (cfg.etiquetas) {
      const elegir = new Set<Fila>();
      const porScore = [...validas].sort((a, b) => Number(b.Score_Final ?? 0) - Number(a.Score_Final ?? 0));
      porScore.slice(0, 5).forEach((f) => elegir.add(f));
      for (const k of [cfg.x, cfg.y]) {
        const ord = [...validas].sort((a, b) => (a[k] as number) - (b[k] as number));
        elegir.add(ord[0]);
        elegir.add(ord[ord.length - 1]);
      }
      const capaTxt = svg("g", { class: "etiquetas" }, s);
      for (const f of elegir) {
        const t = svg("text", {
          x: x(f[cfg.x] as number), y: y(f[cfg.y] as number) - radio(f) - 4,
          class: "etiqueta", "text-anchor": "middle",
        }, capaTxt);
        t.textContent = String(f[idCol]);
      }
    }
  };

  // --- Barras (horizontales: nombres legibles) ------------------------------
  const dibujarBarras = () => {
    type Barra = { nombre: string; valor: number; fila?: Fila; n: number };
    let barras: Barra[];
    let omitidas = 0;
    if (cfg.x === idCol) {
      const validas = data.filas.filter((f) => esNumero(f[cfg.y]));
      omitidas = data.filas.length - validas.length;
      barras = validas.map((f) => ({ nombre: String(f[idCol]), valor: f[cfg.y] as number, fila: f, n: 1 }));
    } else {
      const grupos = new Map<string, number[]>();
      for (const f of data.filas) {
        const v = f[cfg.y];
        if (!esNumero(v)) { omitidas++; continue; }
        const k = String(f[cfg.x] ?? "Sin dato");
        if (!grupos.has(k)) grupos.set(k, []);
        grupos.get(k)!.push(v);
      }
      barras = [...grupos.entries()].map(([nombre, vals]) => ({ nombre, valor: agregar(vals, cfg.calculo), n: vals.length }));
    }
    if (!barras.length) return sinDatos(0, omitidas);

    barras.sort((a, b) => b.valor - a.valor);
    const total = barras.length;
    barras = barras.slice(0, MAX_BARRAS);
    resumen.textContent = `${total > MAX_BARRAS ? `Top ${MAX_BARRAS} de ${total}` : `${total} barras`}` +
      (omitidas ? ` · ${omitidas} sin dato omitidos` : "") + " · ordenado de mayor a menor";

    const filasPintor = barras.map((b) => b.fila).filter((f): f is Fila => !!f);
    const pintor = cfg.x === idCol ? crearPintor(filasPintor) : crearPintor([]);
    if (cfg.x !== idCol) leyenda.replaceChildren();
    else pintor.leyenda();
    const colorBarra = (b: Barra) => (b.fila && cfg.x === idCol ? pintor.color(b.fila) : (oscuro ? "#2fd398" : "#159a6a"));

    const alturaBarra = 24, hueco = 4;
    const etiquetaMax = Math.min(200, Math.max(60, Math.max(...barras.map((b) => Math.min(24, b.nombre.length))) * 8 + 20));
    const m = { izq: etiquetaMax, der: 64, arr: 8, aba: 40 };
    const alto = m.arr + m.aba + barras.length * (alturaBarra + hueco);
    const valoresCalc = cfg.calculo === "conteo" && cfg.x !== idCol ? "" : cfg.y;
    const dx = dominio(barras.map((b) => b.valor), true);
    const x = escalaLineal(dx, [m.izq, ancho - m.der]);

    const s = svg("svg", { width: ancho, height: alto, role: "img" }, lienzo);
    const g = svg("g", {}, s);
    ejeX(g, marcas(dx[0], dx[1], Math.max(3, Math.floor(ancho / 120))), x, m.arr, alto - m.aba, valoresCalc);
    const tituloX = cfg.x === idCol ? etiqueta(cfg.y)
      : cfg.calculo === "conteo" ? `Número de ${data.id_col === "Ticker" ? "activos" : "filas"}`
      : `${etiqueta(cfg.y)} (${cfg.calculo})`;
    tituloEje(g, tituloX, (m.izq + ancho - m.der) / 2, alto - 6);

    barras.forEach((b, i) => {
      const yTop = m.arr + i * (alturaBarra + hueco);
      const x0 = x(0), x1 = x(b.valor);
      const rect = svg("rect", {
        x: Math.min(x0, x1), y: yTop, width: Math.max(1, Math.abs(x1 - x0)), height: alturaBarra,
        rx: 4, fill: colorBarra(b), class: "barra",
      }, g);
      const nom = svg("text", { x: m.izq - 8, y: yTop + alturaBarra / 2, class: "tick", "text-anchor": "end", "dominant-baseline": "middle" }, g);
      nom.textContent = b.nombre.length > 24 ? b.nombre.slice(0, 23) + "…" : b.nombre;
      const val = svg("text", {
        x: b.valor >= 0 ? x1 + 6 : x1 - 6, y: yTop + alturaBarra / 2, class: "valor",
        "text-anchor": b.valor >= 0 ? "start" : "end", "dominant-baseline": "middle",
      }, g);
      val.textContent = valoresCalc ? fmt(cfg.y, b.valor) : String(b.valor);
      // Zona de hover de toda la fila (más grande que la barra).
      const zona = svg("rect", { x: 0, y: yTop - hueco / 2, width: ancho, height: alturaBarra + hueco, class: "zona" }, g);
      zona.addEventListener("mousemove", (ev) => {
        rect.classList.add("activa");
        if (b.fila) mostrarTooltip(ev, tituloFila(b.fila), lineasFila(b.fila, [cfg.y, cfg.color]));
        else mostrarTooltip(ev, b.nombre, [[tituloX, valoresCalc ? fmt(cfg.y, b.valor) : String(b.valor)], ["Activos", String(b.n)]]);
      });
      zona.addEventListener("mouseleave", () => { rect.classList.remove("activa"); ocultarTooltip(); });
    });
  };

  // --- Histograma ----------------------------------------------------------
  const dibujarHistograma = () => {
    const vals = data.filas.map((f) => f[cfg.x]).filter(esNumero);
    const omitidas = data.filas.length - vals.length;
    if (vals.length < 2) return sinDatos(vals.length, omitidas);

    const nBins = Math.min(20, Math.max(5, Math.ceil(Math.log2(vals.length) + 1)));
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const paso = (hi - lo || 1) / nBins;
    const bins = Array.from({ length: nBins }, (_, i) => ({ desde: lo + i * paso, hasta: lo + (i + 1) * paso, filas: [] as Fila[] }));
    for (const f of data.filas) {
      const v = f[cfg.x];
      if (!esNumero(v)) continue;
      bins[Math.min(nBins - 1, Math.floor((v - lo) / paso))].filas.push(f);
    }
    const med = mediana(vals);
    resumen.textContent = `${vals.length} activos` + (omitidas ? ` · ${omitidas} sin dato omitidos` : "") +
      ` · mediana ${fmt(cfg.x, med)}`;

    const alto = 380;
    const m = { izq: 48, der: 20, arr: 16, aba: 52 };
    const x = escalaLineal([lo, lo + paso * nBins], [m.izq, ancho - m.der]);
    const maxN = Math.max(...bins.map((b) => b.filas.length));
    const dy: [number, number] = [0, dominio([0, maxN])[1]];
    const y = escalaLineal(dy, [alto - m.aba, m.arr]);

    const s = svg("svg", { width: ancho, height: alto, role: "img" }, lienzo);
    const g = svg("g", {}, s);
    ejeY(g, marcas(0, dy[1]).filter(Number.isInteger), y, m.izq, ancho - m.der, "");
    const ticks = marcas(lo, hi, Math.max(3, Math.floor(ancho / 110)));
    for (const t of ticks) {
      const tx = svg("text", { x: x(t), y: alto - m.aba + 18, class: "tick", "text-anchor": "middle" }, g);
      tx.textContent = fmtEje(cfg.x, t);
    }
    tituloEje(g, etiqueta(cfg.x), (m.izq + ancho - m.der) / 2, alto - 10);
    tituloEje(g, "Número de activos", 14, (m.arr + alto - m.aba) / 2, true);

    const color = oscuro ? "#2fd398" : "#159a6a";
    for (const b of bins) {
      const x0 = x(b.desde) + 1, x1 = x(b.hasta) - 1;
      const rect = svg("rect", {
        x: x0, y: y(b.filas.length), width: Math.max(1, x1 - x0), height: y(0) - y(b.filas.length),
        rx: 3, fill: color, class: "barra",
      }, g);
      const zona = svg("rect", { x: x(b.desde), y: m.arr, width: x(b.hasta) - x(b.desde), height: alto - m.arr - m.aba, class: "zona" }, g);
      zona.addEventListener("mousemove", (ev) => {
        rect.classList.add("activa");
        const nombres = b.filas.map((f) => String(f[idCol]));
        mostrarTooltip(ev, `${fmt(cfg.x, b.desde)} a ${fmt(cfg.x, b.hasta)}`, [
          ["Activos", String(b.filas.length)],
          ...(nombres.length ? [["", nombres.slice(0, 8).join(", ") + (nombres.length > 8 ? "…" : "")] as [string, string]] : []),
        ]);
      });
      zona.addEventListener("mouseleave", () => { rect.classList.remove("activa"); ocultarTooltip(); });
    }
    svg("line", { x1: x(med), x2: x(med), y1: m.arr, y2: alto - m.aba, class: "mediana-hist" }, g);
    const tMed = svg("text", { x: x(med) + 6, y: m.arr + 4, class: "valor", "dominant-baseline": "hanging" }, g);
    tMed.textContent = `Mediana ${fmt(cfg.x, med)}`;
    leyenda.replaceChildren();
  };

  const sinDatos = (validas: number, omitidas: number) => {
    resumen.textContent = "";
    leyenda.replaceChildren();
    html("div", "vacio",
      `No hay suficientes datos para esta combinación (${validas} con dato, ${omitidas} sin dato). Prueba con otras métricas.`,
      lienzo);
  };

  // --- Render principal ----------------------------------------------------
  const pintarGrafica = () => {
    lienzo.replaceChildren();
    ocultarTooltip();
    if (!ancho) return;
    if (cfg.tipo === "barras") dibujarBarras();
    else if (cfg.tipo === "histograma") dibujarHistograma();
    else dibujarDispersion();
  };
  const pintarTodo = () => { pintarControles(); pintarGrafica(); };

  // Validar columnas guardadas (pueden no existir si cambió la pestaña o los datos).
  const valida = (id: string, tipo?: TipoColumna) => !!porId.get(id) && (!tipo || porId.get(id)!.tipo === tipo);
  if (cfg.tipo === "barras" ? !valida(cfg.x, "cat") : !valida(cfg.x, "num")) cfg.x = cfg.tipo === "barras" ? idCol : base.x;
  if (!valida(cfg.y, "num")) cfg.y = base.y;
  if (cfg.color && !valida(cfg.color)) cfg.color = "";
  if (cfg.tamano && !valida(cfg.tamano, "num")) cfg.tamano = "";

  pintarControles();

  // Redibujar al cambiar el ancho del contenedor.
  const obs = new ResizeObserver((entradas) => {
    const w = Math.floor(entradas[0].contentRect.width);
    if (w && w !== ancho) { ancho = w; pintarGrafica(); }
  });
  obs.observe(lienzo);

  // Streamlit cambia de tema sin rerun: revisar el color del texto cada segundo.
  const vigilante = window.setInterval(() => {
    const o = esOscuro(raiz);
    if (o !== oscuro) { oscuro = o; pintarGrafica(); }
  }, 1000);

  return () => {
    obs.disconnect();
    window.clearInterval(vigilante);
    raiz.remove();
  };
}
