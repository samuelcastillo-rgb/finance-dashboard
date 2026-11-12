//! Simulación Monte Carlo del valor de un portafolio (compra y mantén).
//!
//! Se compila a WebAssembly (`wasm32-unknown-unknown`) y el componente TypeScript de
//! `componentes/montecarlo/src` lo ejecuta en el navegador: Python solo manda los
//! rendimientos diarios históricos y los pesos, y cada cambio de horizonte, modelo o
//! número de escenarios se recalcula al instante sin volver a Streamlit.
//!
//! Dos modelos:
//! - `Historico`: remuestreo (bootstrap) de días reales. Cada día simulado copia un día
//!   histórico completo, así conserva las colas gruesas y la correlación entre activos.
//! - `Normal`: rendimientos logarítmicos normales multivariados con la media y la
//!   covarianza históricas (descomposición de Cholesky).
//!
//! No usa dependencias externas: el generador aleatorio (xoshiro256**), Cholesky y los
//! percentiles están aquí mismo, con pruebas en `cargo test`.

/// Percentiles de las bandas de la gráfica de abanico.
pub const PERCENTILES: [f64; 5] = [5.0, 25.0, 50.0, 75.0, 95.0];
/// Barras del histograma del valor final.
pub const N_BINS: usize = 40;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Modelo {
    Historico,
    Normal,
}

/// Datos de entrada. `rendimientos` es una matriz de `n_dias × n_activos` guardada por
/// filas (un día por fila) con rendimientos simples: 0.01 = +1 %.
pub struct Entrada<'a> {
    pub rendimientos: &'a [f64],
    pub n_activos: usize,
    pub pesos: &'a [f64],
    pub valor_inicial: f64,
    /// Días hábiles a simular (252 ≈ 1 año).
    pub dias: usize,
    /// Cada cuántos días se guarda un punto de la gráfica (21 ≈ 1 mes).
    pub cada: usize,
    pub n_sims: usize,
    pub modelo: Modelo,
    pub semilla: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Estadisticas {
    pub media: f64,
    /// Valor final en los percentiles de `PERCENTILES`.
    pub percentiles: [f64; 5],
    /// Fracción de escenarios que terminan por debajo del valor inicial (0 a 1).
    pub prob_perdida: f64,
    /// Valor en riesgo al 95 %: pérdida (USD) del escenario del percentil 5.
    pub var95: f64,
    /// Pérdida esperada (USD) en el peor 5 % de los escenarios.
    pub cvar95: f64,
    /// Caída máxima desde un pico (%), en la mediana y en el percentil 95 de los escenarios.
    pub caida_max_mediana: f64,
    pub caida_max_p95: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Resultado {
    /// Día de cada punto de la gráfica (0 = hoy).
    pub dias: Vec<f64>,
    /// Valor del portafolio en cada percentil, por punto.
    pub bandas: Vec<[f64; 5]>,
    pub finales: Estadisticas,
    /// Histograma del valor final: límites y conteo por barra.
    pub hist_desde: f64,
    pub hist_hasta: f64,
    pub hist_conteos: Vec<f64>,
}

// ---------------------------------------------------------------------------
// Generador aleatorio: xoshiro256** sembrado con splitmix64
// ---------------------------------------------------------------------------
pub struct Rng {
    s: [u64; 4],
    normal_guardada: Option<f64>,
}

fn splitmix64(x: &mut u64) -> u64 {
    *x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *x;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^ (z >> 31)
}

impl Rng {
    pub fn new(semilla: u64) -> Self {
        let mut x = semilla;
        let s = [
            splitmix64(&mut x),
            splitmix64(&mut x),
            splitmix64(&mut x),
            splitmix64(&mut x),
        ];
        Rng {
            s,
            normal_guardada: None,
        }
    }

    pub fn siguiente(&mut self) -> u64 {
        let resultado = self.s[1].wrapping_mul(5).rotate_left(7).wrapping_mul(9);
        let t = self.s[1] << 17;
        self.s[2] ^= self.s[0];
        self.s[3] ^= self.s[1];
        self.s[1] ^= self.s[2];
        self.s[0] ^= self.s[3];
        self.s[2] ^= t;
        self.s[3] = self.s[3].rotate_left(45);
        resultado
    }

    /// Uniforme en [0, 1).
    pub fn uniforme(&mut self) -> f64 {
        (self.siguiente() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }

    /// Entero uniforme en [0, n) (método de multiplicación de Lemire).
    pub fn indice(&mut self, n: usize) -> usize {
        ((self.siguiente() as u128 * n as u128) >> 64) as usize
    }

    /// Normal estándar (método polar de Marsaglia: sin seno ni coseno, que en WebAssembly
    /// son lentos; guarda el segundo valor del par).
    pub fn normal(&mut self) -> f64 {
        if let Some(z) = self.normal_guardada.take() {
            return z;
        }
        loop {
            let u = 2.0 * self.uniforme() - 1.0;
            let v = 2.0 * self.uniforme() - 1.0;
            let s = u * u + v * v;
            if s > 0.0 && s < 1.0 {
                let f = (-2.0 * s.ln() / s).sqrt();
                self.normal_guardada = Some(v * f);
                return u * f;
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Álgebra y estadística
// ---------------------------------------------------------------------------

/// Factor de Cholesky L (triangular inferior, por filas) de una matriz simétrica n×n.
/// Si la matriz no es definida positiva (p. ej. dos activos idénticos) suma un poco a la
/// diagonal y reintenta. Devuelve None solo si ni así se puede.
pub fn cholesky(a: &[f64], n: usize) -> Option<Vec<f64>> {
    let traza_media = (0..n).map(|i| a[i * n + i]).sum::<f64>() / n as f64;
    let mut ajuste = 0.0;
    for _ in 0..8 {
        if let Some(l) = cholesky_exacto(a, n, ajuste) {
            return Some(l);
        }
        ajuste = if ajuste == 0.0 {
            traza_media.max(1e-12) * 1e-10
        } else {
            ajuste * 100.0
        };
    }
    None
}

fn cholesky_exacto(a: &[f64], n: usize, ajuste: f64) -> Option<Vec<f64>> {
    let mut l = vec![0.0; n * n];
    for i in 0..n {
        for j in 0..=i {
            let mut suma = a[i * n + j];
            if i == j {
                suma += ajuste;
            }
            for k in 0..j {
                suma -= l[i * n + k] * l[j * n + k];
            }
            if i == j {
                if suma <= 0.0 || !suma.is_finite() {
                    return None;
                }
                l[i * n + i] = suma.sqrt();
            } else {
                l[i * n + j] = suma / l[j * n + j];
            }
        }
    }
    Some(l)
}

/// Percentil `p` (0 a 100) de datos ya ordenados, con interpolación lineal (igual que
/// `numpy.percentile` por defecto).
pub fn percentil_ordenado(ordenados: &[f64], p: f64) -> f64 {
    let n = ordenados.len();
    if n == 0 {
        return f64::NAN;
    }
    let h = (n - 1) as f64 * (p / 100.0).clamp(0.0, 1.0);
    let i = h.floor() as usize;
    if i + 1 >= n {
        return ordenados[n - 1];
    }
    ordenados[i] + (h - i as f64) * (ordenados[i + 1] - ordenados[i])
}

/// Media y covarianza muestral (n-1) de los rendimientos logarítmicos.
fn media_y_covarianza(logs: &[f64], n_dias: usize, n: usize) -> (Vec<f64>, Vec<f64>) {
    let mut media = vec![0.0; n];
    for fila in logs.chunks_exact(n) {
        for (m, v) in media.iter_mut().zip(fila) {
            *m += v;
        }
    }
    for m in &mut media {
        *m /= n_dias as f64;
    }
    let mut cov = vec![0.0; n * n];
    for fila in logs.chunks_exact(n) {
        for i in 0..n {
            let di = fila[i] - media[i];
            for j in 0..=i {
                cov[i * n + j] += di * (fila[j] - media[j]);
            }
        }
    }
    let divisor = (n_dias - 1) as f64;
    for i in 0..n {
        for j in 0..=i {
            cov[i * n + j] /= divisor;
            cov[j * n + i] = cov[i * n + j];
        }
    }
    (media, cov)
}

// ---------------------------------------------------------------------------
// Simulación
// ---------------------------------------------------------------------------

/// Días que avanza cada paso del modelo normal. La suma de k días normales independientes
/// es normal con media k·μ y covarianza k·Σ, así que avanzar de 7 en 7 da exactamente la
/// misma distribución en cada punto de la gráfica con 7 veces menos cálculo. Solo la caída
/// máxima se mide sobre cierres cada 7 días en vez de diarios.
const PASO_NORMAL: usize = 7;

/// Días en los que se guarda un punto: 0, cada, 2·cada, … y siempre el último día.
fn dias_registrados(dias: usize, cada: usize) -> Vec<usize> {
    let mut res: Vec<usize> = (0..=dias).step_by(cada.max(1)).collect();
    if *res.last().unwrap_or(&0) != dias {
        res.push(dias);
    }
    res
}

pub fn simular(e: &Entrada) -> Result<Resultado, &'static str> {
    let n = e.n_activos;
    if n == 0 || e.pesos.len() != n {
        return Err("número de activos inválido");
    }
    if !e.rendimientos.len().is_multiple_of(n) || e.rendimientos.len() / n < 2 {
        return Err("se necesitan al menos 2 días de rendimientos");
    }
    if e.rendimientos.iter().any(|r| !r.is_finite() || *r <= -1.0) {
        return Err("rendimientos inválidos");
    }
    if e.dias == 0 || e.n_sims == 0 {
        return Err("horizonte o número de escenarios en cero");
    }
    if !(e.valor_inicial.is_finite() && e.valor_inicial > 0.0) {
        return Err("valor inicial inválido");
    }
    let suma_pesos: f64 = e.pesos.iter().sum();
    if !(suma_pesos.is_finite() && suma_pesos > 0.0)
        || e.pesos.iter().any(|p| !p.is_finite() || *p < 0.0)
    {
        return Err("pesos inválidos");
    }
    let n_dias = e.rendimientos.len() / n;
    let iniciales: Vec<f64> = e
        .pesos
        .iter()
        .map(|p| p / suma_pesos * e.valor_inicial)
        .collect();

    // Modelo normal: media y factor de Cholesky de los rendimientos logarítmicos,
    // escalados al tamaño del paso.
    let paso = if e.modelo == Modelo::Normal
        && e.dias.is_multiple_of(PASO_NORMAL)
        && e.cada.is_multiple_of(PASO_NORMAL)
    {
        PASO_NORMAL
    } else {
        1
    };
    let parametros_normal = if e.modelo == Modelo::Normal {
        let logs: Vec<f64> = e.rendimientos.iter().map(|r| r.ln_1p()).collect();
        let (media, cov) = media_y_covarianza(&logs, n_dias, n);
        let l = cholesky(&cov, n).ok_or("covarianza no válida")?;
        let k = paso as f64;
        Some((
            media.iter().map(|m| m * k).collect::<Vec<f64>>(),
            l.iter().map(|x| x * k.sqrt()).collect::<Vec<f64>>(),
        ))
    } else {
        None
    };

    let puntos = dias_registrados(e.dias, e.cada);
    let n_puntos = puntos.len();
    // valores[p * n_sims + s]: valor del escenario s en el punto p.
    let mut valores = vec![0.0; n_puntos * e.n_sims];
    let mut caidas = vec![0.0; e.n_sims];

    let mut rng = Rng::new(e.semilla);
    let mut activos = vec![0.0; n];
    let mut z = vec![0.0; n];

    for s in 0..e.n_sims {
        activos.copy_from_slice(&iniciales);
        let mut pico = e.valor_inicial;
        let mut caida_max: f64 = 0.0;
        valores[s] = e.valor_inicial;
        let mut siguiente_punto = 1;

        for dia in (paso..=e.dias).step_by(paso) {
            match &parametros_normal {
                None => {
                    let t = rng.indice(n_dias);
                    let fila = &e.rendimientos[t * n..(t + 1) * n];
                    for (a, r) in activos.iter_mut().zip(fila) {
                        *a *= 1.0 + r;
                    }
                }
                Some((media, l)) => {
                    for zi in z.iter_mut() {
                        *zi = rng.normal();
                    }
                    for i in 0..n {
                        let fila_l = &l[i * n..i * n + i + 1];
                        let choque: f64 = fila_l.iter().zip(&z).map(|(li, zi)| li * zi).sum();
                        activos[i] *= (media[i] + choque).exp();
                    }
                }
            }
            let valor: f64 = activos.iter().sum();
            if valor > pico {
                pico = valor;
            } else {
                caida_max = caida_max.max((pico - valor) / pico);
            }
            if siguiente_punto < n_puntos && puntos[siguiente_punto] == dia {
                valores[siguiente_punto * e.n_sims + s] = valor;
                siguiente_punto += 1;
            }
        }
        caidas[s] = caida_max * 100.0;
    }

    // Bandas: percentiles de cada punto.
    let mut bandas = Vec::with_capacity(n_puntos);
    for p in 0..n_puntos {
        let columna = &mut valores[p * e.n_sims..(p + 1) * e.n_sims];
        columna.sort_unstable_by(f64::total_cmp);
        bandas.push(PERCENTILES.map(|q| percentil_ordenado(columna, q)));
    }

    // Estadísticas del valor final (la última columna ya está ordenada).
    let finales = &valores[(n_puntos - 1) * e.n_sims..];
    let media = finales.iter().sum::<f64>() / e.n_sims as f64;
    let percentiles = *bandas.last().unwrap();
    let p5 = percentiles[0];
    let perdidas = finales.iter().filter(|v| **v < e.valor_inicial).count();
    let cola: Vec<f64> = finales.iter().copied().filter(|v| *v <= p5).collect();
    let media_cola = cola.iter().sum::<f64>() / cola.len().max(1) as f64;
    caidas.sort_unstable_by(f64::total_cmp);

    // Histograma entre los percentiles 0.5 y 99.5 (los extremos se suman a la primera y
    // última barra para que un escenario atípico no aplaste la gráfica).
    let mut desde = percentil_ordenado(finales, 0.5);
    let mut hasta = percentil_ordenado(finales, 99.5);
    if hasta <= desde {
        desde -= 0.5;
        hasta += 0.5;
    }
    let ancho = (hasta - desde) / N_BINS as f64;
    let mut conteos = vec![0.0; N_BINS];
    for v in finales {
        let b = ((v - desde) / ancho).floor();
        let b = if b < 0.0 {
            0
        } else {
            (b as usize).min(N_BINS - 1)
        };
        conteos[b] += 1.0;
    }

    Ok(Resultado {
        dias: puntos.iter().map(|d| *d as f64).collect(),
        bandas,
        finales: Estadisticas {
            media,
            percentiles,
            prob_perdida: perdidas as f64 / e.n_sims as f64,
            var95: e.valor_inicial - p5,
            cvar95: e.valor_inicial - media_cola,
            caida_max_mediana: percentil_ordenado(&caidas, 50.0),
            caida_max_p95: percentil_ordenado(&caidas, 95.0),
        },
        hist_desde: desde,
        hist_hasta: hasta,
        hist_conteos: conteos,
    })
}

impl Resultado {
    /// Todo el resultado en un solo arreglo de f64 para pasarlo a JavaScript:
    /// `[n_puntos, (día, p5, p25, p50, p75, p95) × n_puntos,
    ///   media, p5, p25, p50, p75, p95, prob_perdida, var95, cvar95, caída_mediana, caída_p95,
    ///   n_bins, desde, hasta, conteos…]`
    pub fn aplanar(&self) -> Vec<f64> {
        let mut v = Vec::with_capacity(1 + self.dias.len() * 6 + 11 + 3 + N_BINS);
        v.push(self.dias.len() as f64);
        for (d, b) in self.dias.iter().zip(&self.bandas) {
            v.push(*d);
            v.extend_from_slice(b);
        }
        let f = &self.finales;
        v.push(f.media);
        v.extend_from_slice(&f.percentiles);
        v.extend_from_slice(&[
            f.prob_perdida,
            f.var95,
            f.cvar95,
            f.caida_max_mediana,
            f.caida_max_p95,
        ]);
        v.push(self.hist_conteos.len() as f64);
        v.push(self.hist_desde);
        v.push(self.hist_hasta);
        v.extend_from_slice(&self.hist_conteos);
        v
    }
}

// ---------------------------------------------------------------------------
// Interfaz con JavaScript (ABI de C, sin wasm-bindgen)
//
// 1. JS pide memoria con `reservar(n)` y copia ahí los rendimientos y los pesos.
// 2. Llama a `simular_portafolio(...)`, que devuelve un puntero a un arreglo de f64 cuyo
//    primer elemento es su propia longitud (o 0 = nulo si la entrada no es válida).
// 3. JS copia el resultado y libera los tres bloques con `liberar(ptr, n)`.
// ---------------------------------------------------------------------------

fn bloque_a_puntero(v: Vec<f64>) -> *mut f64 {
    Box::into_raw(v.into_boxed_slice()) as *mut f64
}

/// Reserva `n` f64 (en ceros) para que JavaScript escriba en ellos.
#[unsafe(no_mangle)]
pub extern "C" fn reservar(n: usize) -> *mut f64 {
    bloque_a_puntero(vec![0.0; n])
}

/// Libera un bloque devuelto por `reservar` o `simular_portafolio`.
///
/// # Safety
/// `ptr` y `n` deben ser exactamente los de un bloque reservado aquí y no liberado.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn liberar(ptr: *mut f64, n: usize) {
    if !ptr.is_null() {
        drop(unsafe { Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, n)) });
    }
}

/// # Safety
/// `rendimientos` debe apuntar a `n_dias * n_activos` f64 y `pesos` a `n_activos` f64.
#[unsafe(no_mangle)]
#[allow(clippy::too_many_arguments)]
pub unsafe extern "C" fn simular_portafolio(
    rendimientos: *const f64,
    n_dias: usize,
    n_activos: usize,
    pesos: *const f64,
    valor_inicial: f64,
    dias: usize,
    cada: usize,
    n_sims: usize,
    modelo: u32,
    semilla: f64,
) -> *mut f64 {
    if rendimientos.is_null() || pesos.is_null() {
        return std::ptr::null_mut();
    }
    let entrada = Entrada {
        rendimientos: unsafe { std::slice::from_raw_parts(rendimientos, n_dias * n_activos) },
        n_activos,
        pesos: unsafe { std::slice::from_raw_parts(pesos, n_activos) },
        valor_inicial,
        dias,
        cada,
        n_sims,
        modelo: if modelo == 1 {
            Modelo::Normal
        } else {
            Modelo::Historico
        },
        semilla: semilla as u64,
    };
    match simular(&entrada) {
        Ok(res) => {
            let mut plano = res.aplanar();
            plano.insert(0, (plano.len() + 1) as f64);
            bloque_a_puntero(plano)
        }
        Err(_) => std::ptr::null_mut(),
    }
}

// ---------------------------------------------------------------------------
// Pruebas: cargo test
// ---------------------------------------------------------------------------
#[cfg(test)]
mod pruebas {
    use super::*;

    fn entrada<'a>(rend: &'a [f64], n: usize, pesos: &'a [f64], modelo: Modelo) -> Entrada<'a> {
        Entrada {
            rendimientos: rend,
            n_activos: n,
            pesos,
            valor_inicial: 1000.0,
            dias: 252,
            cada: 21,
            n_sims: 2000,
            modelo,
            semilla: 42,
        }
    }

    fn cerca(a: f64, b: f64, tol: f64) -> bool {
        (a - b).abs() <= tol * b.abs().max(1.0)
    }

    #[test]
    fn rendimiento_constante_es_determinista() {
        // Todos los días +0.1 %: todos los escenarios valen lo mismo, 1000 · 1.001^252.
        let rend = vec![0.001; 10 * 2];
        let pesos = [0.5, 0.5];
        let r = simular(&entrada(&rend, 2, &pesos, Modelo::Historico)).unwrap();
        let esperado = 1000.0 * 1.001f64.powi(252);
        for p in r.finales.percentiles {
            assert!(cerca(p, esperado, 1e-12), "{p} vs {esperado}");
        }
        assert_eq!(r.finales.prob_perdida, 0.0);
        assert_eq!(r.finales.caida_max_mediana, 0.0);
        assert!(cerca(r.finales.var95, 1000.0 - esperado, 1e-9));
        // Puntos cada 21 días: 0, 21, …, 252 -> 13 puntos; el primero es el valor inicial.
        assert_eq!(r.dias.len(), 13);
        assert_eq!(r.bandas[0], [1000.0; 5]);
    }

    #[test]
    fn misma_semilla_mismo_resultado() {
        let rend = [0.02, -0.01, -0.015, 0.012, 0.005, 0.0, -0.03, 0.025];
        let pesos = [3.0, 1.0];
        for modelo in [Modelo::Historico, Modelo::Normal] {
            let a = simular(&entrada(&rend, 2, &pesos, modelo)).unwrap();
            let b = simular(&entrada(&rend, 2, &pesos, modelo)).unwrap();
            assert_eq!(a, b);
            let mut otra = entrada(&rend, 2, &pesos, modelo);
            otra.semilla = 7;
            assert_ne!(simular(&otra).unwrap().finales.media, a.finales.media);
        }
    }

    #[test]
    fn bandas_ordenadas() {
        let rend = [0.02, -0.01, -0.015, 0.012, 0.005, 0.0, -0.03, 0.025];
        let r = simular(&entrada(&rend, 2, &[1.0, 1.0], Modelo::Historico)).unwrap();
        for b in &r.bandas {
            assert!(b.windows(2).all(|w| w[0] <= w[1]), "{b:?}");
        }
        let total: f64 = r.hist_conteos.iter().sum();
        assert_eq!(total, 2000.0);
        assert!(r.finales.cvar95 >= r.finales.var95);
        assert!(r.finales.caida_max_p95 >= r.finales.caida_max_mediana);
    }

    #[test]
    fn modelo_normal_recupera_la_media() {
        // Rendimientos logarítmicos de media 0.0004 diaria: la mediana a 1 año debe ser
        // cercana a 1000 · e^(0.0004 · 252).
        let mut rng = Rng::new(1);
        let rend: Vec<f64> = (0..5000)
            .map(|_| (0.0004 + 0.01 * rng.normal()).exp_m1())
            .collect();
        let mut e = entrada(&rend, 1, &[1.0], Modelo::Normal);
        e.n_sims = 20000;
        let r = simular(&e).unwrap();
        let logs: Vec<f64> = rend.iter().map(|x| x.ln_1p()).collect();
        let media_log = logs.iter().sum::<f64>() / logs.len() as f64;
        let esperado = 1000.0 * (media_log * 252.0).exp();
        assert!(
            cerca(r.finales.percentiles[2], esperado, 0.01),
            "{} vs {esperado}",
            r.finales.percentiles[2]
        );
    }

    #[test]
    fn modelo_normal_con_pasos_de_1_y_7_dias_coincide() {
        // 252 días (pasos de 7) vs 250 días (pasos de 1): la mediana debe escalar igual.
        let mut rng = Rng::new(3);
        let rend: Vec<f64> = (0..4000)
            .map(|_| (0.0005 + 0.012 * rng.normal()).exp_m1())
            .collect();
        let mut e = entrada(&rend, 1, &[1.0], Modelo::Normal);
        e.n_sims = 20000;
        let siete = simular(&e).unwrap();
        e.dias = 250;
        e.cada = 25;
        let uno = simular(&e).unwrap();
        let tasa = |r: &Resultado, d: f64| (r.finales.percentiles[2] / 1000.0).ln() / d;
        assert!((tasa(&siete, 252.0) - tasa(&uno, 250.0)).abs() < 5e-5);
        // La dispersión (p95/p5) también debe crecer con la raíz del tiempo.
        let ancho = |r: &Resultado, d: f64| {
            (r.finales.percentiles[4] / r.finales.percentiles[0]).ln() / d.sqrt()
        };
        assert!((ancho(&siete, 252.0) / ancho(&uno, 250.0) - 1.0).abs() < 0.02);
    }

    #[test]
    fn bootstrap_conserva_la_correlacion() {
        // Dos activos que siempre se mueven en sentido contrario y con pesos iguales: se
        // cubren entre sí (solo dispersa un poco que los pesos se desvían con el tiempo).
        let rend = [0.01, -0.01, -0.01, 0.01];
        let r = simular(&entrada(&rend, 2, &[1.0, 1.0], Modelo::Historico)).unwrap();
        let [p5, _, _, _, p95] = r.finales.percentiles;
        assert!(p95 - p5 < 0.1 * 1000.0, "{p5} – {p95}");
        // El mismo activo solo: dispersión mucho mayor.
        let solo = simular(&entrada(&[0.01, -0.01], 1, &[1.0], Modelo::Historico)).unwrap();
        let [q5, _, _, _, q95] = solo.finales.percentiles;
        assert!(q95 - q5 > 5.0 * (p95 - p5));
    }

    #[test]
    fn cholesky_conocido() {
        let a = [4.0, 2.0, 2.0, 3.0];
        let l = cholesky(&a, 2).unwrap();
        assert!(
            cerca(l[0], 2.0, 1e-12) && cerca(l[2], 1.0, 1e-12) && cerca(l[3], 2f64.sqrt(), 1e-12)
        );
        assert_eq!(l[1], 0.0);
        // Matriz singular (dos activos idénticos): se corrige con un ajuste mínimo.
        assert!(cholesky(&[1.0, 1.0, 1.0, 1.0], 2).is_some());
    }

    #[test]
    fn percentiles_como_numpy() {
        let d = [1.0, 2.0, 3.0, 4.0];
        assert_eq!(percentil_ordenado(&d, 50.0), 2.5);
        assert!(cerca(percentil_ordenado(&d, 5.0), 1.15, 1e-12));
        assert_eq!(percentil_ordenado(&d, 100.0), 4.0);
        assert_eq!(percentil_ordenado(&[7.0], 30.0), 7.0);
    }

    #[test]
    fn entradas_invalidas() {
        let pesos = [1.0];
        assert!(simular(&entrada(&[0.01], 1, &pesos, Modelo::Historico)).is_err()); // 1 día
        assert!(simular(&entrada(&[0.01, f64::NAN], 1, &pesos, Modelo::Historico)).is_err());
        assert!(simular(&entrada(&[0.01, -1.0], 1, &pesos, Modelo::Historico)).is_err());
        assert!(simular(&entrada(&[0.01, 0.02], 1, &[0.0], Modelo::Historico)).is_err());
        assert!(
            simular(&entrada(
                &[0.01, 0.02, 0.0],
                2,
                &[1.0, 1.0],
                Modelo::Historico
            ))
            .is_err()
        );
    }

    #[test]
    fn interfaz_c() {
        let rend = [0.01, -0.005, 0.002, 0.0];
        let pesos = [1.0, 2.0];
        unsafe {
            let p = simular_portafolio(
                rend.as_ptr(),
                2,
                2,
                pesos.as_ptr(),
                500.0,
                42,
                21,
                100,
                0,
                3.0,
            );
            assert!(!p.is_null());
            let n = *p as usize;
            let datos = std::slice::from_raw_parts(p, n);
            // [longitud, n_puntos=3, …]; 1 + 1 + 3·6 + 11 + 3 + 40 = 74
            assert_eq!(n, 74);
            assert_eq!(datos[1], 3.0);
            liberar(p, n);
            let nulo = simular_portafolio(
                rend.as_ptr(),
                2,
                2,
                pesos.as_ptr(),
                -1.0,
                42,
                21,
                100,
                0,
                3.0,
            );
            assert!(nulo.is_null());
        }
    }
}
