// Simulación Monte Carlo del portafolio para Streamlit (st.components.v2).
//
// El cálculo está en Rust (../rust/src/lib.rs), compilado a WebAssembly e incrustado en
// este bundle. Python solo manda los rendimientos diarios históricos y los pesos; los
// controles (horizonte, escenarios, modelo) recalculan aquí mismo, en el navegador, sin
// volver a Streamlit. Las gráficas se dibujan en SVG sin librerías externas.
//
// Compilar:  npm install && npm run build   ->  dist/montecarlo.js

import bytesWasm from "../rust/target/wasm32-unknown-unknown/release/montecarlo.wasm";

// ----------------------------------------------------------------------------
// Contrato con Python (finanzas/montecarlo.py) y con Rust
// ----------------------------------------------------------------------------
interface Datos {
  tickers: string[];
  rendimientos: number[];
  n_dias: number;
  pesos: number[];
  valor_inicial: number;
  desde: string;
  hasta: string;
}

interface Componente {
  data: Datos;
  key: string;
  parentElement: HTMLElement | ShadowRoot;
}

type Modelo = "historico" | "normal";

interface Config {
  anios: number;
  escenarios: number;
  modelo: Modelo;
  semilla: number;
}

interface Motor {
  memory: WebAssembly.Memory;
  reservar(n: number): number;
  liberar(ptr: number, n: number): void;
  simular_portafolio(
    rendimientos: number, nDias: number, nActivos: number, pesos: number, valorInicial: number,
    dias: number, cada: number, nSims: number, modelo: number, semilla: number,
  ): number;
}

interface Resultado {
  dias: number[];
  bandas: number[][]; // [p5, p25, p50, p75, p95] por punto
  media: number;
  finales: number[];
  probPerdida: number;
  var95: number;
  cvar95: number;
  caidaMediana: number;
  caidaP95: number;
  histDesde: number;
  histHasta: number;
  conteos: number[];
  ms: number;
}

const DIAS_ANIO = 252;
const CADA = 21; // un punto por mes

// El módulo se carga una vez por sesión del navegador: el WebAssembly se compila una
// sola vez y la configuración y el último resultado sobreviven a los reruns de Streamlit.
let motor: Promise<Motor> | null = null;
const memoria = new Map<string, Config>();
const resultados = new Map<string, Resultado>();

function cargarMotor(): Promise<Motor> {
  motor ??= WebAssembly.instantiate(bytesWasm, {}).then((r) => r.instance.exports as unknown as Motor);
  return motor;
}

/** Copia los datos a la memoria del WebAssembly, simula y lee el arreglo plano de Rust. */
function simular(m: Motor, d: Datos, cfg: Config): Resultado | null {
  const inicio = performance.now();
  const nR = d.rendimientos.length;
  const nA = d.pesos.length;
  // Cada reserva puede agrandar la memoria y dejar inválidas las vistas anteriores,
  // por eso se crea una vista nueva justo antes de cada uso.
  const pR = m.reservar(nR);
  new Float64Array(m.memory.buffer, pR, nR).set(d.rendimientos);
  const pP = m.reservar(nA);
  new Float64Array(m.memory.buffer, pP, nA).set(d.pesos);
  const pS = m.simular_portafolio(pR, d.n_dias, nA, pP, d.valor_inicial, cfg.anios * DIAS_ANIO, CADA,
    cfg.escenarios, cfg.modelo === "normal" ? 1 : 0, cfg.semilla);
  let plano: Float64Array | null = null;
  if (pS) {
    const n = new Float64Array(m.memory.buffer, pS, 1)[0];
    plano = new Float64Array(m.memory.buffer, pS, n).slice();
    m.liberar(pS, n);
  }
  m.liberar(pR, nR);
  m.liberar(pP, nA);
  if (!plano) return null;

  // [longitud, n_puntos, (día, p5..p95) × n, media, p5..p95, prob, var, cvar, caída_med,
  //  caída_p95, n_bins, desde, hasta, conteos…]  (ver Resultado::aplanar en lib.rs)
  let i = 1;
  const nPuntos = plano[i++];
  const dias: number[] = [];
  const bandas: number[][] = [];
  for (let k = 0; k < nPuntos; k++) {
    dias.push(plano[i]);
    bandas.push(Array.from(plano.subarray(i + 1, i + 6)));
    i += 6;
  }
  const media = plano[i++];
  const finales = Array.from(plano.subarray(i, i + 5));
  i += 5;
  const [probPerdida, var95, cvar95, caidaMediana, caidaP95] = plano.subarray(i, i + 5);
  i += 5;
  const nBins = plano[i++];
  const histDesde = plano[i++];
  const histHasta = plano[i++];
  const conteos = Array.from(plano.subarray(i, i + nBins));
  return {
    dias, bandas, media, finales, probPerdida, var95, cvar95, caidaMediana, caidaP95,
    histDesde, histHasta, conteos, ms: performance.now() - inicio,
  };
}

// ----------------------------------------------------------------------------
// Formato, colores y utilidades (mismo estilo que el explorador de métricas)
// ----------------------------------------------------------------------------
const usd = (v: number, dec = 0) =>
  (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("es-MX", { minimumFractionDigits: dec, maximumFractionDigits: dec });
const pct = (v: number, signo = false) =>
  (signo && v > 0 ? "+" : "") + v.toLocaleString("es-MX", { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + "%";

function usdCorto(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e6) return `$${(v / 1e6).toLocaleString("es-MX", { maximumFractionDigits: 2 })}M`;
  if (a >= 1e4) return `$${(v / 1e3).toLocaleString("es-MX", { maximumFractionDigits: 0 })}k`;
  if (a >= 1e3) return `$${(v / 1e3).toLocaleString("es-MX", { maximumFractionDigits: 1 })}k`;
  return usd(v);
}

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

/** Fecha aproximada dentro de `dias` días hábiles. */
function fechaFutura(dias: number): string {
  const f = new Date();
  f.setDate(f.getDate() + Math.round((dias * 365.25) / DIAS_ANIO));
  return `${MESES[f.getMonth()]} ${f.getFullYear()}`;
}

function plazo(dias: number): string {
  if (dias === 0) return "Hoy";
  const meses = Math.round(dias / CADA);
  if (meses % 12 === 0) return meses === 12 ? "1 año" : `${meses / 12} años`;
  return meses === 1 ? "1 mes" : `${meses} meses`;
}

// Modo oscuro = el texto heredado de Streamlit es claro.
function esOscuro(el: Element): boolean {
  const m = getComputedStyle(el).color.match(/\d+(\.\d+)?/g);
  if (!m) return false;
  const [r, g, b] = m.map(Number);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 140;
}

function colores(oscuro: boolean) {
  return oscuro
    ? { banda: "#2fd398", mediana: "#2fd398", ganancia: "#199e70", perdida: "#e66767" }
    : { banda: "#1dbe83", mediana: "#127a55", ganancia: "#1baf7a", perdida: "#e34948" };
}

function marcas(min: number, max: number, cuantas = 5): number[] {
  if (min === max) { min -= 1; max += 1; }
  const paso0 = (max - min) / cuantas;
  const pot = 10 ** Math.floor(Math.log10(paso0));
  const paso = [1, 2, 2.5, 5, 10].map((f) => f * pot).find((p) => p >= paso0) ?? 10 * pot;
  const res: number[] = [];
  for (let v = Math.ceil(min / paso) * paso; v <= max + paso * 1e-9; v += paso) res.push(+v.toFixed(10));
  return res;
}

function escalaLineal(d: [number, number], r: [number, number]) {
  return (v: number) => r[0] + ((v - d[0]) / (d[1] - d[0])) * (r[1] - r[0]);
}

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
  padre: Element, etiqueta: string, opciones: [string, string][], valor: string, alCambiar: (v: string) => void,
): void {
  const caja = html("label", "campo", "", padre);
  html("span", "campo-titulo", etiqueta, caja);
  const sel = html("select", "", "", caja);
  for (const [v, t] of opciones) html("option", "", t, sel).value = v;
  sel.value = valor;
  sel.addEventListener("change", () => alCambiar(sel.value));
}

// ----------------------------------------------------------------------------
// Componente
// ----------------------------------------------------------------------------
export default function montecarlo(componente: Componente): () => void {
  const { data, key, parentElement } = componente;
  const cfg: Config = { anios: 1, escenarios: 5000, modelo: "historico", semilla: 1, ...memoria.get(key) };
  // Firma de los datos: si cambian las compras, el resultado guardado ya no sirve.
  const firma = [data.n_dias, data.valor_inicial, data.pesos.join(","), data.rendimientos.length,
    data.rendimientos[0], data.rendimientos[data.rendimientos.length - 1]].join("|");
  const claveResultado = () => `${key}|${firma}|${cfg.anios}|${cfg.escenarios}|${cfg.modelo}|${cfg.semilla}`;

  const raiz = html("div", "montecarlo");
  parentElement.appendChild(raiz);
  const controles = html("div", "controles", "", raiz);
  const kpis = html("div", "kpis", "", raiz);
  const tituloAbanico = html("div", "subtitulo", "", raiz);
  const lienzoAbanico = html("div", "lienzo", "", raiz);
  const leyenda = html("div", "leyenda", "", raiz);
  const tituloHist = html("div", "subtitulo", "", raiz);
  const lienzoHist = html("div", "lienzo", "", raiz);
  const pie = html("div", "pie", "", raiz);
  const tooltip = html("div", "tooltip", "", raiz);

  let ancho = 0;
  let oscuro = esOscuro(raiz);
  let res: Resultado | null = resultados.get(claveResultado()) ?? null;
  let vivo = true;
  let pendiente = 0;

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

  // --- Controles -----------------------------------------------------------
  const pintarControles = () => {
    controles.replaceChildren();
    const cambiar = (k: "anios" | "escenarios") => (v: string) => { cfg[k] = Number(v); recalcular(); };
    selector(controles, "Horizonte", [1, 2, 3, 5, 10].map((a) => [String(a), a === 1 ? "1 año" : `${a} años`]),
      String(cfg.anios), cambiar("anios"));
    selector(controles, "Escenarios", [1000, 5000, 10000].map((n) => [String(n), n.toLocaleString("es-MX")]),
      String(cfg.escenarios), cambiar("escenarios"));
    selector(controles, "Modelo", [["historico", "Días históricos (bootstrap)"], ["normal", "Normal multivariada"]],
      cfg.modelo, (v) => { cfg.modelo = v as Modelo; recalcular(); });
    const boton = html("button", "boton", "🎲 Otros escenarios", controles);
    boton.type = "button";
    boton.title = "Vuelve a simular con otra semilla aleatoria";
    boton.addEventListener("click", () => { cfg.semilla = (cfg.semilla % 1_000_000) + 1; recalcular(); });
  };

  // --- KPIs ----------------------------------------------------------------
  const tarjeta = (titulo: string, valor: string, detalle: string, clase = "") => {
    const t = html("div", "kpi", "", kpis);
    html("div", "kpi-titulo", titulo, t);
    html("div", `kpi-valor ${clase}`, valor, t);
    html("div", "kpi-detalle", detalle, t);
  };

  const pintarKpis = (r: Resultado) => {
    kpis.replaceChildren();
    const v0 = data.valor_inicial;
    const [p5, , p50, , p95] = r.finales;
    const cambio = (p50 / v0 - 1) * 100;
    const anual = ((p50 / v0) ** (1 / cfg.anios) - 1) * 100;
    tarjeta(`Valor mediano en ${plazo(cfg.anios * DIAS_ANIO).toLowerCase()}`, usd(p50),
      cfg.anios === 1 ? `${pct(cambio, true)} vs hoy` : `${pct(cambio, true)} · ${pct(anual, true)} anual`,
      cambio >= 0 ? "sube" : "baja");
    tarjeta("Rango probable (90 %)", `${usdCorto(p5)} – ${usdCorto(p95)}`,
      "9 de cada 10 escenarios terminan aquí");
    tarjeta("Probabilidad de perder", pct(r.probPerdida * 100),
      `de terminar abajo de ${usd(v0)}`, r.probPerdida >= 0.5 ? "baja" : "");
    tarjeta("Peor 5 % (VaR 95 %)", r.var95 > 0 ? `-${usd(r.var95)}` : "Sin pérdida",
      r.cvar95 > 0 ? `pérdida promedio en ese 5 %: -${usd(r.cvar95)}` : "aun el peor 5 % gana", r.var95 > 0 ? "baja" : "");
    tarjeta("Caída máxima típica", `-${pct(r.caidaMediana)}`,
      `desde un pico; 1 de cada 20 escenarios cae más de ${pct(r.caidaP95)}`);
  };

  // --- Gráfica de abanico --------------------------------------------------
  const dibujarAbanico = (r: Resultado) => {
    lienzoAbanico.replaceChildren();
    const c = colores(oscuro);
    const alto = 340;
    const m = { izq: 68, der: 16, arr: 14, aba: 34 };
    const v0 = data.valor_inicial;
    const lo = Math.min(v0, ...r.bandas.map((b) => b[0]));
    const hi = Math.max(v0, ...r.bandas.map((b) => b[4]));
    const ticksY = marcas(lo, hi, 5);
    const dy: [number, number] = [Math.min(lo, ticksY[0]), Math.max(hi, ticksY[ticksY.length - 1])];
    const diasMax = r.dias[r.dias.length - 1];
    const x = escalaLineal([0, diasMax], [m.izq, ancho - m.der]);
    const y = escalaLineal(dy, [alto - m.aba, m.arr]);

    const s = svg("svg", {
      width: ancho, height: alto, role: "img",
      "aria-label": `Valor proyectado del portafolio a ${plazo(diasMax)}: mediana ${usd(r.finales[2])}`,
    }, lienzoAbanico);
    const g = svg("g", {}, s);
    for (const t of ticksY) {
      svg("line", { x1: m.izq, x2: ancho - m.der, y1: y(t), y2: y(t), class: "rejilla" }, g);
      svg("text", { x: m.izq - 8, y: y(t), class: "tick", "text-anchor": "end", "dominant-baseline": "middle" }, g)
        .textContent = usdCorto(t);
    }
    // Marcas del eje X: cada año (o cada 3 meses si el horizonte es de 1 año).
    const angosto = ancho < 520;
    const pasoX = cfg.anios === 1 ? (angosto ? 6 : 3) * CADA
      : cfg.anios >= 5 && angosto ? (cfg.anios === 10 ? 5 : 2) * DIAS_ANIO
        : cfg.anios === 10 ? 2 * DIAS_ANIO : DIAS_ANIO;
    for (let d = 0; d <= diasMax; d += pasoX) {
      const ancla = d === 0 ? "start" : d + pasoX > diasMax ? "end" : "middle";
      svg("text", { x: x(d), y: alto - m.aba + 20, class: "tick", "text-anchor": ancla }, g).textContent = plazo(d);
    }

    const camino = (k: number) => r.bandas.map((b, i) => `${x(r.dias[i]).toFixed(1)},${y(b[k]).toFixed(1)}`);
    const area = (a: number, b: number) => `M${camino(b).join("L")}L${camino(a).reverse().join("L")}Z`;
    svg("path", { d: area(0, 4), fill: c.banda, "fill-opacity": oscuro ? 0.2 : 0.16 }, g);
    svg("path", { d: area(1, 3), fill: c.banda, "fill-opacity": oscuro ? 0.38 : 0.32 }, g);
    svg("line", { x1: m.izq, x2: ancho - m.der, y1: y(v0), y2: y(v0), class: "referencia" }, g);
    svg("text", { x: ancho - m.der - 4, y: y(v0) - 6, class: "valor", "text-anchor": "end" }, g)
      .textContent = `Hoy: ${usd(v0)}`;
    svg("path", { d: `M${camino(2).join("L")}`, fill: "none", stroke: c.mediana, "stroke-width": 2.5,
      "stroke-linejoin": "round" }, g);

    // Interacción: guía vertical en el mes más cercano al cursor.
    const guia = svg("line", { y1: m.arr, y2: alto - m.aba, class: "guia", visibility: "hidden" }, g);
    const punto = svg("circle", { r: 4.5, fill: c.mediana, class: "punto-guia", visibility: "hidden" }, g);
    const zona = svg("rect", { x: m.izq, y: m.arr, width: ancho - m.izq - m.der, height: alto - m.arr - m.aba,
      class: "zona" }, g);
    zona.addEventListener("mousemove", (ev) => {
      const caja = s.getBoundingClientRect();
      const dia = ((ev.clientX - caja.left - m.izq) / (ancho - m.izq - m.der)) * diasMax;
      let i = 0;
      for (let k = 1; k < r.dias.length; k++) if (Math.abs(r.dias[k] - dia) < Math.abs(r.dias[i] - dia)) i = k;
      const b = r.bandas[i];
      guia.setAttribute("x1", String(x(r.dias[i])));
      guia.setAttribute("x2", String(x(r.dias[i])));
      punto.setAttribute("cx", String(x(r.dias[i])));
      punto.setAttribute("cy", String(y(b[2])));
      guia.setAttribute("visibility", "visible");
      punto.setAttribute("visibility", "visible");
      const titulo = r.dias[i] === 0 ? "Hoy" : `En ${plazo(r.dias[i]).toLowerCase()} (${fechaFutura(r.dias[i])})`;
      mostrarTooltip(ev, titulo, [
        ["Optimista (p95)", usd(b[4])],
        ["Favorable (p75)", usd(b[3])],
        ["Mediana (p50)", usd(b[2])],
        ["Desfavorable (p25)", usd(b[1])],
        ["Pesimista (p5)", usd(b[0])],
      ]);
    });
    zona.addEventListener("mouseleave", () => {
      guia.setAttribute("visibility", "hidden");
      punto.setAttribute("visibility", "hidden");
      ocultarTooltip();
    });

    leyenda.replaceChildren();
    const item = (muestra: HTMLElement, texto: string) => {
      const it = html("span", "leyenda-item", "", leyenda);
      it.appendChild(muestra);
      html("span", "", texto, it);
    };
    const linea = html("span", "muestra-linea");
    linea.style.background = c.mediana;
    item(linea, "Mediana");
    const b50 = html("span", "muestra-banda");
    b50.style.background = c.banda;
    b50.style.opacity = oscuro ? "0.55" : "0.5";
    item(b50, "50 % de los escenarios (p25–p75)");
    const b90 = html("span", "muestra-banda");
    b90.style.background = c.banda;
    b90.style.opacity = oscuro ? "0.28" : "0.22";
    item(b90, "90 % de los escenarios (p5–p95)");
  };

  // --- Histograma del valor final -----------------------------------------
  const dibujarHistograma = (r: Resultado) => {
    lienzoHist.replaceChildren();
    const c = colores(oscuro);
    const alto = 230;
    const m = { izq: 68, der: 16, arr: 22, aba: 34 };
    const v0 = data.valor_inicial;
    const total = r.conteos.reduce((a, b) => a + b, 0);
    const paso = (r.histHasta - r.histDesde) / r.conteos.length;
    const dx: [number, number] = [Math.min(r.histDesde, v0), Math.max(r.histHasta, v0)];
    const x = escalaLineal(dx, [m.izq, ancho - m.der]);
    const maxPct = Math.max(...r.conteos) / total * 100;
    const ticksY = marcas(0, maxPct, 4);
    const y = escalaLineal([0, Math.max(maxPct, ticksY[ticksY.length - 1])], [alto - m.aba, m.arr]);

    const s = svg("svg", { width: ancho, height: alto, role: "img",
      "aria-label": `Distribución del valor final: ${pct(r.probPerdida * 100)} de los escenarios terminan con pérdida` },
    lienzoHist);
    const g = svg("g", {}, s);
    for (const t of ticksY) {
      svg("line", { x1: m.izq, x2: ancho - m.der, y1: y(t), y2: y(t), class: "rejilla" }, g);
      svg("text", { x: m.izq - 8, y: y(t), class: "tick", "text-anchor": "end", "dominant-baseline": "middle" }, g)
        .textContent = `${t.toLocaleString("es-MX")}%`;
    }
    for (const t of marcas(dx[0], dx[1], Math.max(3, Math.floor(ancho / 120)))) {
      if (t < dx[0] || t > dx[1]) continue;
      svg("text", { x: x(t), y: alto - m.aba + 20, class: "tick", "text-anchor": "middle" }, g).textContent = usdCorto(t);
    }
    r.conteos.forEach((n, i) => {
      const desde = r.histDesde + i * paso;
      const hasta = desde + paso;
      const p = (n / total) * 100;
      const x0 = x(desde) + 0.5;
      const x1 = x(hasta) - 0.5;
      const color = (desde + hasta) / 2 < v0 ? c.perdida : c.ganancia;
      const barra = svg("rect", { x: x0, y: y(p), width: Math.max(1, x1 - x0), height: y(0) - y(p), rx: 2,
        fill: color, class: "barra" }, g);
      const zona = svg("rect", { x: x(desde), y: m.arr, width: x(hasta) - x(desde), height: alto - m.arr - m.aba,
        class: "zona" }, g);
      const extremo = i === 0 ? " o menos" : i === r.conteos.length - 1 ? " o más" : "";
      zona.addEventListener("mousemove", (ev) => {
        barra.classList.add("activa");
        mostrarTooltip(ev, `${usd(desde)} a ${usd(hasta)}${extremo}`, [
          ["Escenarios", `${n.toLocaleString("es-MX")} (${pct(p)})`],
          ["Cambio vs hoy", `${pct(((desde + hasta) / 2 / v0 - 1) * 100, true)}`],
        ]);
      });
      zona.addEventListener("mouseleave", () => { barra.classList.remove("activa"); ocultarTooltip(); });
    });
    svg("line", { x1: x(v0), x2: x(v0), y1: m.arr - 6, y2: alto - m.aba, class: "referencia-v" }, g);
    const derecha = x(v0) > ancho * 0.7;
    svg("text", { x: x(v0) + (derecha ? -6 : 6), y: m.arr - 8, class: "valor",
      "text-anchor": derecha ? "end" : "start" }, g).textContent = `Hoy: ${usd(v0)}`;
  };

  // --- Render y cálculo ----------------------------------------------------
  const pintarResultado = () => {
    ocultarTooltip();
    if (!res) return;
    pintarKpis(res);
    tituloAbanico.textContent = `Cómo podría evolucionar tu portafolio (${plazo(cfg.anios * DIAS_ANIO).toLowerCase()})`;
    tituloHist.textContent = `Valor del portafolio al final del horizonte (${fechaFutura(cfg.anios * DIAS_ANIO)})`;
    if (ancho) {
      dibujarAbanico(res);
      dibujarHistograma(res);
    }
    const modelo = cfg.modelo === "normal" ? "normal multivariada" : "días históricos remuestreados";
    pie.textContent = `${cfg.escenarios.toLocaleString("es-MX")} escenarios · modelo: ${modelo} · `
      + `${data.n_dias.toLocaleString("es-MX")} días de historia (${data.desde} a ${data.hasta}) · `
      + `calculado en Rust/WebAssembly en ${Math.max(1, Math.round(res.ms)).toLocaleString("es-MX")} ms`;
  };

  const error = (texto: string) => {
    kpis.replaceChildren();
    lienzoAbanico.replaceChildren();
    lienzoHist.replaceChildren();
    leyenda.replaceChildren();
    tituloAbanico.textContent = "";
    tituloHist.textContent = "";
    pie.textContent = "";
    html("div", "vacio", texto, lienzoAbanico);
  };

  function recalcular() {
    memoria.set(key, { ...cfg });
    pintarControles();
    const clave = claveResultado();
    const guardado = resultados.get(clave);
    if (guardado) {
      res = guardado;
      pintarResultado();
      return;
    }
    raiz.classList.add("calculando");
    pie.textContent = "Calculando escenarios…";
    const turno = ++pendiente;
    cargarMotor()
      // Un instante para que el navegador pinte el aviso antes del cálculo.
      .then((m) => new Promise<Motor>((ok) => setTimeout(() => ok(m), 16)))
      .then((m) => {
        if (!vivo || turno !== pendiente) return;
        const r = simular(m, data, cfg);
        raiz.classList.remove("calculando");
        if (!r) { error("No se pudo simular con estos datos."); return; }
        resultados.set(clave, r);
        res = r;
        pintarResultado();
      })
      .catch((e) => {
        raiz.classList.remove("calculando");
        error(`Tu navegador no pudo cargar el motor de simulación (WebAssembly): ${e}`);
      });
  }

  const obs = new ResizeObserver((entradas) => {
    const w = Math.floor(entradas[0].contentRect.width);
    if (w && w !== ancho) { ancho = w; pintarResultado(); }
  });
  obs.observe(lienzoAbanico);

  const vigilante = window.setInterval(() => {
    const o = esOscuro(raiz);
    if (o !== oscuro) { oscuro = o; pintarResultado(); }
  }, 1000);

  if (res) { pintarControles(); pintarResultado(); } else recalcular();

  return () => {
    vivo = false;
    obs.disconnect();
    window.clearInterval(vigilante);
    raiz.remove();
  };
}
