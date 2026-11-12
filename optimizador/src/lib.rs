//! Frontera eficiente de Markowitz para el proceso diario del dashboard.
//!
//! Entrada: rendimientos diarios (simples) de N activos durante T días.
//! Salida: la frontera eficiente con pesos solo positivos (sin ventas en corto), que
//! suman 1 y con un peso máximo por activo, más dos carteras destacadas: la de mínima
//! volatilidad y la de máximo Sharpe.
//!
//! - Rendimiento esperado: media histórica anualizada (× 252).
//! - Covarianza: muestral con contracción de Ledoit-Wolf (2004) hacia una matriz
//!   identidad escalada, para que con muchos activos y pocos datos no sea tan ruidosa.
//! - Cada punto de la frontera resuelve  min  w'Σw − λ·μ'w  sobre el conjunto
//!   {Σw = 1, 0 ≤ w ≤ peso_maximo} con FISTA (gradiente proyectado acelerado) y la
//!   proyección exacta al símplex acotado. Recorrer λ de 0 hacia arriba traza la frontera
//!   desde la mínima volatilidad hasta el máximo rendimiento.
//! - Máximo Sharpe: el mejor punto de la frontera, refinado con búsqueda de sección dorada.
//!
//! Sin dependencias externas; `main.rs` solo lee la entrada y escribe el JSON.

use std::fmt::Write as _;

pub const DIAS_ANIO: f64 = 252.0;

#[derive(Debug)]
pub struct Opciones {
    /// Tasa libre de riesgo anual (0.04 = 4 %).
    pub tasa_libre: f64,
    /// Peso máximo de un activo (0.2 = 20 %).
    pub peso_maximo: f64,
    /// Puntos de la frontera a devolver.
    pub puntos: usize,
}

#[derive(Debug)]
pub struct Entrada {
    pub tickers: Vec<String>,
    /// Matriz de `n_dias × tickers.len()` por filas (un día por fila).
    pub rendimientos: Vec<f64>,
    pub opciones: Opciones,
}

#[derive(Clone, Debug)]
pub struct Cartera {
    pub pesos: Vec<f64>,
    pub rendimiento: f64,
    pub volatilidad: f64,
    pub sharpe: f64,
}

pub struct Resultado {
    pub tickers: Vec<String>,
    pub n_dias: usize,
    pub rendimientos: Vec<f64>,
    pub volatilidades: Vec<f64>,
    /// Intensidad de la contracción de Ledoit-Wolf (0 = covarianza muestral, 1 = identidad).
    pub contraccion: f64,
    pub frontera: Vec<Cartera>,
    pub min_volatilidad: Cartera,
    pub max_sharpe: Cartera,
}

// ---------------------------------------------------------------------------
// Estadística
// ---------------------------------------------------------------------------

/// Media y covarianza anualizadas; la covarianza con contracción de Ledoit-Wolf.
/// Devuelve (μ, Σ, intensidad).
pub fn estimar(rend: &[f64], n: usize) -> (Vec<f64>, Vec<f64>, f64) {
    let t = rend.len() / n;
    let tf = t as f64;
    let mut media = vec![0.0; n];
    for fila in rend.chunks_exact(n) {
        for (m, r) in media.iter_mut().zip(fila) {
            *m += r;
        }
    }
    media.iter_mut().for_each(|m| *m /= tf);

    // Datos centrados y covarianza muestral S = X'X / T (la de Ledoit-Wolf).
    let x: Vec<f64> = rend
        .chunks_exact(n)
        .flat_map(|f| f.iter().zip(&media).map(|(r, m)| r - m))
        .collect();
    let mut s = vec![0.0; n * n];
    for fila in x.chunks_exact(n) {
        for i in 0..n {
            let xi = fila[i];
            for j in 0..=i {
                s[i * n + j] += xi * fila[j];
            }
        }
    }
    for i in 0..n {
        for j in 0..=i {
            s[i * n + j] /= tf;
            s[j * n + i] = s[i * n + j];
        }
    }

    // Ledoit y Wolf (2004), "A well-conditioned estimator for large-dimensional covariance
    // matrices": objetivo m·I con m = traza(S)/N.
    let m = (0..n).map(|i| s[i * n + i]).sum::<f64>() / n as f64;
    let norma2 = |a: &[f64]| a.iter().map(|v| v * v).sum::<f64>();
    let s_norma2 = norma2(&s);
    let d2 = (s_norma2 - 2.0 * m * (0..n).map(|i| s[i * n + i]).sum::<f64>() + m * m * n as f64)
        / n as f64;
    // Σ_t ||x_t x_t' − S||² = Σ_t (||x_t||⁴ − 2·x_t'S x_t + ||S||²)
    let mut suma = 0.0;
    let mut sx = vec![0.0; n];
    for fila in x.chunks_exact(n) {
        let nx2 = norma2(fila);
        for i in 0..n {
            sx[i] = s[i * n..(i + 1) * n]
                .iter()
                .zip(fila)
                .map(|(a, b)| a * b)
                .sum();
        }
        let xsx: f64 = fila.iter().zip(&sx).map(|(a, b)| a * b).sum();
        suma += nx2 * nx2 - 2.0 * xsx + s_norma2;
    }
    let b2_barra = suma / (tf * tf) / n as f64;
    let intensidad = if d2 > 0.0 {
        (b2_barra.min(d2) / d2).clamp(0.0, 1.0)
    } else {
        1.0
    };

    let mut sigma = s;
    for i in 0..n {
        for j in 0..n {
            let objetivo = if i == j { m } else { 0.0 };
            sigma[i * n + j] =
                (intensidad * objetivo + (1.0 - intensidad) * sigma[i * n + j]) * DIAS_ANIO;
        }
    }
    (
        media.iter().map(|v| v * DIAS_ANIO).collect(),
        sigma,
        intensidad,
    )
}

fn producto(sigma: &[f64], w: &[f64], salida: &mut [f64]) {
    let n = w.len();
    for (i, s) in salida.iter_mut().enumerate() {
        *s = sigma[i * n..(i + 1) * n]
            .iter()
            .zip(w)
            .map(|(a, b)| a * b)
            .sum();
    }
}

fn punto(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

/// Mayor valor propio de Σ (iteración de potencias): fija el tamaño de paso de FISTA.
fn valor_propio_max(sigma: &[f64], n: usize) -> f64 {
    let mut v = vec![1.0 / (n as f64).sqrt(); n];
    let mut sv = vec![0.0; n];
    let mut lambda = 0.0;
    for _ in 0..500 {
        producto(sigma, &v, &mut sv);
        let norma = punto(&sv, &sv).sqrt();
        if norma == 0.0 {
            return 0.0;
        }
        let nuevo = punto(&v, &sv);
        v.iter_mut().zip(&sv).for_each(|(a, b)| *a = b / norma);
        if (nuevo - lambda).abs() <= 1e-12 * nuevo.abs() {
            return nuevo;
        }
        lambda = nuevo;
    }
    lambda
}

// ---------------------------------------------------------------------------
// Optimización
// ---------------------------------------------------------------------------

/// Proyección euclidiana de `v` sobre {Σw = 1, 0 ≤ w ≤ u}: w_i = clamp(v_i − τ, 0, u) con
/// τ tal que la suma sea 1 (bisección; la suma es decreciente en τ).
pub fn proyectar(v: &[f64], u: f64, w: &mut [f64]) {
    let suma = |tau: f64| v.iter().map(|x| (x - tau).clamp(0.0, u)).sum::<f64>();
    let mut lo = v.iter().cloned().fold(f64::INFINITY, f64::min) - u; // suma = N·u ≥ 1
    let mut hi = v.iter().cloned().fold(f64::NEG_INFINITY, f64::max); // suma = 0
    for _ in 0..200 {
        let medio = 0.5 * (lo + hi);
        if medio <= lo || medio >= hi {
            break;
        }
        if suma(medio) > 1.0 {
            lo = medio;
        } else {
            hi = medio;
        }
    }
    let tau = 0.5 * (lo + hi);
    for (wi, x) in w.iter_mut().zip(v) {
        *wi = (x - tau).clamp(0.0, u);
    }
}

struct Problema<'a> {
    mu: &'a [f64],
    sigma: &'a [f64],
    u: f64,
    paso: f64,
}

impl Problema<'_> {
    /// min w'Σw − λ·μ'w con FISTA y reinicio adaptativo, empezando en `w`.
    fn resolver(&self, lambda: f64, w: &mut [f64]) {
        let n = w.len();
        let mut y = w.to_vec();
        let mut sy = vec![0.0; n];
        let mut v = vec![0.0; n];
        let mut nuevo = vec![0.0; n];
        let mut t = 1.0f64;
        for _ in 0..100_000 {
            producto(self.sigma, &y, &mut sy);
            for i in 0..n {
                v[i] = y[i] - self.paso * (2.0 * sy[i] - lambda * self.mu[i]);
            }
            proyectar(&v, self.u, &mut nuevo);
            let cambio = nuevo
                .iter()
                .zip(w.iter())
                .map(|(a, b)| (a - b).abs())
                .fold(0.0, f64::max);
            let t_nuevo = 0.5 * (1.0 + (1.0 + 4.0 * t * t).sqrt());
            // Reinicio (O'Donoghue y Candès): si el impulso apunta cuesta arriba, se reinicia.
            let cuesta_arriba: f64 = (0..n).map(|i| (y[i] - nuevo[i]) * (nuevo[i] - w[i])).sum();
            if cuesta_arriba > 0.0 {
                t = 1.0;
                y.copy_from_slice(&nuevo);
            } else {
                let beta = (t - 1.0) / t_nuevo;
                for i in 0..n {
                    y[i] = nuevo[i] + beta * (nuevo[i] - w[i]);
                }
                t = t_nuevo;
            }
            w.copy_from_slice(&nuevo);
            if cambio < 1e-12 {
                break;
            }
        }
    }

    fn cartera(&self, w: &[f64], tasa_libre: f64) -> Cartera {
        let mut sw = vec![0.0; w.len()];
        producto(self.sigma, w, &mut sw);
        let rendimiento = punto(self.mu, w);
        let volatilidad = punto(w, &sw).max(0.0).sqrt();
        // Pesos menores a 1e-6 son ruido numérico del resolvedor.
        let mut pesos: Vec<f64> = w.iter().map(|p| if *p < 1e-6 { 0.0 } else { *p }).collect();
        let total: f64 = pesos.iter().sum();
        pesos.iter_mut().for_each(|p| *p /= total);
        Cartera {
            pesos,
            rendimiento,
            volatilidad,
            sharpe: if volatilidad > 0.0 {
                (rendimiento - tasa_libre) / volatilidad
            } else {
                0.0
            },
        }
    }
}

/// Cartera de máximo rendimiento: llena hasta `u` los activos de mayor μ.
fn max_rendimiento(mu: &[f64], u: f64) -> Vec<f64> {
    let mut orden: Vec<usize> = (0..mu.len()).collect();
    orden.sort_by(|a, b| mu[*b].total_cmp(&mu[*a]));
    let mut w = vec![0.0; mu.len()];
    let mut resta: f64 = 1.0;
    for i in orden {
        let p = resta.min(u);
        w[i] = p;
        resta -= p;
        if resta <= 0.0 {
            break;
        }
    }
    w
}

pub fn calcular(e: &Entrada) -> Result<Resultado, String> {
    let n = e.tickers.len();
    let o = &e.opciones;
    if n < 2 {
        return Err("se necesitan al menos 2 activos".into());
    }
    if !e.rendimientos.len().is_multiple_of(n) || e.rendimientos.len() / n < 30 {
        return Err("se necesitan al menos 30 días de rendimientos para todos los activos".into());
    }
    if e.rendimientos.iter().any(|r| !r.is_finite()) {
        return Err("hay rendimientos no numéricos".into());
    }
    if !(o.peso_maximo > 0.0 && o.peso_maximo <= 1.0) || o.peso_maximo * (n as f64) < 1.0 - 1e-12 {
        return Err(format!(
            "con {n} activos el peso máximo debe estar entre {:.4} y 1",
            1.0 / n as f64
        ));
    }
    if !o.tasa_libre.is_finite() || o.puntos < 2 {
        return Err("opciones inválidas".into());
    }

    let (mu, sigma, contraccion) = estimar(&e.rendimientos, n);
    let l = valor_propio_max(&sigma, n);
    let p = Problema {
        mu: &mu,
        sigma: &sigma,
        u: o.peso_maximo,
        paso: 1.0 / (2.0 * l.max(1e-12)),
    };

    // Escala natural de λ: varianza típica / rendimiento típico.
    let var_tipica = (0..n).map(|i| sigma[i * n + i]).sum::<f64>() / n as f64;
    let mu_tipico = (mu.iter().map(|m| m.abs()).sum::<f64>() / n as f64).max(1e-6);
    let escala = var_tipica / mu_tipico;
    let w_max = max_rendimiento(&mu, o.peso_maximo);
    let r_max = punto(&mu, &w_max);

    // Recorrido de λ (geométrico) con arranque en caliente: cada punto parte del anterior.
    let mut w = vec![1.0 / n as f64; n];
    let tmp = w.clone();
    proyectar(&tmp, o.peso_maximo, &mut w);
    p.resolver(0.0, &mut w);
    let mut camino: Vec<(f64, Vec<f64>)> = vec![(0.0, w.clone())];
    let mut lambda = escala * 1e-3;
    while lambda < escala * 1e6 {
        p.resolver(lambda, &mut w);
        camino.push((lambda, w.clone()));
        if punto(&mu, &w) >= r_max - 1e-9 * r_max.abs().max(1.0) {
            break;
        }
        lambda *= 1.04;
    }
    camino.push((f64::INFINITY, w_max.clone()));

    let carteras: Vec<Cartera> = camino
        .iter()
        .map(|(_, w)| p.cartera(w, o.tasa_libre))
        .collect();

    // Máximo Sharpe: mejor punto del recorrido y sección dorada en log λ alrededor de él.
    let mejor = (0..carteras.len())
        .max_by(|a, b| carteras[*a].sharpe.total_cmp(&carteras[*b].sharpe))
        .unwrap();
    let mut max_sharpe = carteras[mejor].clone();
    if mejor > 0 && mejor + 1 < camino.len() - 1 {
        let (mut a, mut b) = (
            camino[mejor - 1].0.max(escala * 1e-6).ln(),
            camino[mejor + 1].0.ln(),
        );
        let phi = 0.5 * (5f64.sqrt() - 1.0);
        let mut wc = camino[mejor].1.clone();
        let sharpe_en = |x: f64, w: &mut [f64]| {
            p.resolver(x.exp(), w);
            p.cartera(w, o.tasa_libre)
        };
        for _ in 0..40 {
            let c = b - phi * (b - a);
            let d = a + phi * (b - a);
            let cc = sharpe_en(c, &mut wc);
            let cd = sharpe_en(d, &mut wc);
            if cc.sharpe >= cd.sharpe {
                b = d
            } else {
                a = c
            }
            for cand in [cc, cd] {
                if cand.sharpe > max_sharpe.sharpe {
                    max_sharpe = cand;
                }
            }
        }
    }

    // Puntos repartidos por igual en rendimiento entre la mínima volatilidad y el máximo.
    let r_min = carteras[0].rendimiento;
    let mut frontera: Vec<Cartera> = Vec::new();
    let mut usados = vec![false; carteras.len()];
    for k in 0..o.puntos {
        let objetivo = r_min + (r_max - r_min) * k as f64 / (o.puntos - 1) as f64;
        let i = (0..carteras.len())
            .min_by(|a, b| {
                (carteras[*a].rendimiento - objetivo)
                    .abs()
                    .total_cmp(&(carteras[*b].rendimiento - objetivo).abs())
            })
            .unwrap();
        if !usados[i] {
            usados[i] = true;
            frontera.push(carteras[i].clone());
        }
    }
    frontera.sort_by(|a, b| a.rendimiento.total_cmp(&b.rendimiento));

    Ok(Resultado {
        tickers: e.tickers.clone(),
        n_dias: e.rendimientos.len() / n,
        volatilidades: (0..n).map(|i| sigma[i * n + i].sqrt()).collect(),
        rendimientos: mu,
        contraccion,
        min_volatilidad: carteras[0].clone(),
        max_sharpe,
        frontera,
    })
}

// ---------------------------------------------------------------------------
// Entrada en texto y salida JSON
// ---------------------------------------------------------------------------

/// Formato de entrada (lo arma finanzas/frontera.py):
/// ```text
/// tasa_libre 0.04
/// peso_maximo 0.2
/// puntos 40
/// tickers VOO QQQ SCHD
/// datos
/// 0.0012 -0.0031 0.0004      <- un día por línea, en el orden de `tickers`
/// ```
/// Las líneas vacías y las que empiezan con `#` se ignoran.
pub fn leer_entrada(texto: &str) -> Result<Entrada, String> {
    let mut opciones = Opciones {
        tasa_libre: 0.04,
        peso_maximo: 1.0,
        puntos: 40,
    };
    let mut tickers: Vec<String> = Vec::new();
    let mut rendimientos = Vec::new();
    let mut en_datos = false;
    for (num, linea) in texto.lines().enumerate() {
        let linea = linea.trim();
        if linea.is_empty() || linea.starts_with('#') {
            continue;
        }
        let error = |msg: &str| format!("línea {}: {msg}", num + 1);
        if en_datos {
            let fila: Result<Vec<f64>, _> =
                linea.split_whitespace().map(str::parse::<f64>).collect();
            let fila = fila.map_err(|_| error("número inválido"))?;
            if fila.len() != tickers.len() {
                return Err(error(&format!(
                    "se esperaban {} valores y hay {}",
                    tickers.len(),
                    fila.len()
                )));
            }
            rendimientos.extend(fila);
            continue;
        }
        let (clave, valor) = linea.split_once(char::is_whitespace).unwrap_or((linea, ""));
        let numero = || {
            valor
                .trim()
                .parse::<f64>()
                .map_err(|_| error(&format!("valor inválido para {clave}")))
        };
        match clave {
            "tasa_libre" => opciones.tasa_libre = numero()?,
            "peso_maximo" => opciones.peso_maximo = numero()?,
            "puntos" => opciones.puntos = numero()? as usize,
            "tickers" => tickers = valor.split_whitespace().map(String::from).collect(),
            "datos" => en_datos = true,
            _ => return Err(error(&format!("clave desconocida: {clave}"))),
        }
    }
    if tickers.is_empty() {
        return Err("falta la línea de tickers".into());
    }
    Ok(Entrada {
        tickers,
        rendimientos,
        opciones,
    })
}

fn texto_json(s: &str) -> String {
    let mut res = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => res.push_str("\\\""),
            '\\' => res.push_str("\\\\"),
            c if (c as u32) < 0x20 => {
                let _ = write!(res, "\\u{:04x}", c as u32);
            }
            c => res.push(c),
        }
    }
    res.push('"');
    res
}

fn numero_json(v: f64) -> String {
    if v.is_finite() {
        format!("{v:.6}")
    } else {
        "null".into()
    }
}

fn cartera_json(c: &Cartera, tickers: &[String]) -> String {
    // Solo los pesos distintos de cero, de mayor a menor.
    let mut pesos: Vec<(usize, f64)> = c
        .pesos
        .iter()
        .copied()
        .enumerate()
        .filter(|(_, p)| *p > 0.0)
        .collect();
    pesos.sort_by(|a, b| b.1.total_cmp(&a.1));
    let pesos: Vec<String> = pesos
        .iter()
        .map(|(i, p)| format!("{}:{}", texto_json(&tickers[*i]), numero_json(*p)))
        .collect();
    format!(
        "{{\"rendimiento\":{},\"volatilidad\":{},\"sharpe\":{},\"pesos\":{{{}}}}}",
        numero_json(c.rendimiento),
        numero_json(c.volatilidad),
        numero_json(c.sharpe),
        pesos.join(",")
    )
}

pub fn a_json(r: &Resultado, o: &Opciones) -> String {
    let activos: Vec<String> = (0..r.tickers.len())
        .map(|i| {
            format!(
                "{{\"ticker\":{},\"rendimiento\":{},\"volatilidad\":{}}}",
                texto_json(&r.tickers[i]),
                numero_json(r.rendimientos[i]),
                numero_json(r.volatilidades[i])
            )
        })
        .collect();
    let frontera: Vec<String> = r
        .frontera
        .iter()
        .map(|c| cartera_json(c, &r.tickers))
        .collect();
    format!(
        "{{\"n_dias\":{},\"tasa_libre\":{},\"peso_maximo\":{},\"contraccion\":{},\"activos\":[{}],\
         \"frontera\":[{}],\"min_volatilidad\":{},\"max_sharpe\":{}}}",
        r.n_dias,
        numero_json(o.tasa_libre),
        numero_json(o.peso_maximo),
        numero_json(r.contraccion),
        activos.join(","),
        frontera.join(","),
        cartera_json(&r.min_volatilidad, &r.tickers),
        cartera_json(&r.max_sharpe, &r.tickers)
    )
}

// ---------------------------------------------------------------------------
// Pruebas: cargo test
// ---------------------------------------------------------------------------
#[cfg(test)]
mod pruebas {
    use super::*;

    /// Generador simple y determinista para datos de prueba (xorshift + Box-Muller).
    struct Azar(u64);
    impl Azar {
        fn uniforme(&mut self) -> f64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            (self.0 >> 11) as f64 / (1u64 << 53) as f64
        }
        fn normal(&mut self) -> f64 {
            let u1 = 1.0 - self.uniforme();
            let u2 = self.uniforme();
            (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
        }
    }

    /// T días de N activos con medias y volatilidades diarias dadas y un factor común.
    fn simular(t: usize, medias: &[f64], vols: &[f64], correlacion: f64, semilla: u64) -> Vec<f64> {
        let mut azar = Azar(semilla);
        let mut res = Vec::with_capacity(t * medias.len());
        for _ in 0..t {
            let comun = azar.normal();
            for (m, s) in medias.iter().zip(vols) {
                let z = correlacion.sqrt() * comun + (1.0 - correlacion).sqrt() * azar.normal();
                res.push(m + s * z);
            }
        }
        res
    }

    fn entrada(rend: Vec<f64>, n: usize, peso_maximo: f64) -> Entrada {
        Entrada {
            tickers: (0..n).map(|i| format!("A{i}")).collect(),
            rendimientos: rend,
            opciones: Opciones {
                tasa_libre: 0.04,
                peso_maximo,
                puntos: 25,
            },
        }
    }

    fn valida(c: &Cartera, u: f64) {
        let suma: f64 = c.pesos.iter().sum();
        assert!((suma - 1.0).abs() < 1e-9, "suma {suma}");
        assert!(
            c.pesos.iter().all(|p| *p >= 0.0 && *p <= u + 1e-9),
            "{:?}",
            c.pesos
        );
    }

    #[test]
    fn proyeccion_al_simplex_acotado() {
        let mut w = vec![0.0; 4];
        proyectar(&[0.9, 0.5, 0.1, -3.0], 0.4, &mut w);
        assert!((w.iter().sum::<f64>() - 1.0).abs() < 1e-12);
        assert!((w[0] - 0.4).abs() < 1e-12 && (w[1] - 0.4).abs() < 1e-12);
        assert!((w[2] - 0.2).abs() < 1e-9 && w[3] == 0.0);
        // Un punto ya factible no se mueve.
        proyectar(&[0.25, 0.25, 0.25, 0.25], 0.4, &mut w);
        assert!(w.iter().all(|p| (p - 0.25).abs() < 1e-12));
    }

    #[test]
    fn minima_volatilidad_de_dos_activos_independientes() {
        // Sin correlación: w1 = σ2² / (σ1² + σ2²). Con σ = 1 % y 2 %: w1 = 0.8.
        let rend = simular(20_000, &[0.0, 0.0], &[0.01, 0.02], 0.0, 7);
        let r = calcular(&entrada(rend, 2, 1.0)).unwrap();
        let w = &r.min_volatilidad.pesos;
        assert!((w[0] - 0.8).abs() < 0.02, "{w:?}");
        valida(&r.min_volatilidad, 1.0);
    }

    #[test]
    fn frontera_creciente_y_con_restricciones() {
        let medias = [0.0002, 0.0004, 0.0006, 0.0003, 0.0008, 0.0001];
        let vols = [0.008, 0.012, 0.016, 0.010, 0.022, 0.006];
        let rend = simular(1500, &medias, &vols, 0.3, 11);
        let r = calcular(&entrada(rend, 6, 0.3)).unwrap();
        assert!(r.frontera.len() >= 10);
        for c in r.frontera.iter().chain([&r.min_volatilidad, &r.max_sharpe]) {
            valida(c, 0.3);
        }
        for par in r.frontera.windows(2) {
            assert!(par[1].rendimiento >= par[0].rendimiento - 1e-12);
            assert!(
                par[1].volatilidad >= par[0].volatilidad - 1e-6,
                "{} {}",
                par[0].volatilidad,
                par[1].volatilidad
            );
        }
        // Ningún punto de la frontera tiene menos volatilidad que la mínima.
        assert!(
            r.frontera
                .iter()
                .all(|c| c.volatilidad >= r.min_volatilidad.volatilidad - 1e-9)
        );
        assert!(
            r.frontera
                .iter()
                .all(|c| c.sharpe <= r.max_sharpe.sharpe + 1e-9)
        );
    }

    #[test]
    fn max_sharpe_supera_a_carteras_al_azar() {
        let medias = [0.0003, 0.0006, 0.0004, 0.0009];
        let vols = [0.009, 0.015, 0.011, 0.025];
        let rend = simular(2000, &medias, &vols, 0.4, 3);
        let r = calcular(&entrada(rend.clone(), 4, 0.5)).unwrap();
        let (mu, sigma, _) = estimar(&rend, 4);
        let mut azar = Azar(99);
        let mut mejor_azar = f64::NEG_INFINITY;
        for _ in 0..50_000 {
            let v: Vec<f64> = (0..4).map(|_| azar.uniforme()).collect();
            let mut w = vec![0.0; 4];
            proyectar(&v, 0.5, &mut w);
            let mut sw = vec![0.0; 4];
            producto(&sigma, &w, &mut sw);
            let s = (punto(&mu, &w) - 0.04) / punto(&w, &sw).sqrt();
            mejor_azar = mejor_azar.max(s);
        }
        assert!(
            r.max_sharpe.sharpe >= mejor_azar - 1e-6,
            "{} < {mejor_azar}",
            r.max_sharpe.sharpe
        );
        assert!(
            r.max_sharpe.sharpe - mejor_azar < 0.02,
            "el azar debería acercarse al óptimo"
        );
    }

    #[test]
    fn contraccion_entre_cero_y_uno() {
        // Pocos datos para muchos activos: la contracción debe ser notable.
        let medias = vec![0.0; 40];
        let vols: Vec<f64> = (0..40).map(|i| 0.01 + 0.0005 * i as f64).collect();
        let (_, _, poca_info) = estimar(&simular(60, &medias, &vols, 0.2, 5), 40);
        let (_, _, mucha_info) = estimar(&simular(20_000, &medias, &vols, 0.2, 5), 40);
        assert!((0.0..=1.0).contains(&poca_info) && (0.0..=1.0).contains(&mucha_info));
        assert!(poca_info > mucha_info, "{poca_info} vs {mucha_info}");
    }

    #[test]
    fn peso_maximo_imposible() {
        let rend = simular(100, &[0.0; 3], &[0.01; 3], 0.0, 1);
        assert!(calcular(&entrada(rend, 3, 0.3)).is_err()); // 3 × 30 % < 100 %
    }

    #[test]
    fn lectura_y_json() {
        let texto = "# ejemplo\ntasa_libre 0.03\npeso_maximo 0.6\npuntos 5\ntickers AAA BBB\ndatos\n0.01 -0.02\n";
        let e = leer_entrada(texto).unwrap();
        assert_eq!(e.tickers, ["AAA", "BBB"]);
        assert_eq!(e.opciones.puntos, 5);
        assert_eq!(e.rendimientos, [0.01, -0.02]);
        assert!(
            leer_entrada("tickers A B\ndatos\n0.1\n")
                .unwrap_err()
                .contains("línea 3")
        );
        assert!(leer_entrada("otra 1\n").is_err());
        assert_eq!(texto_json("a\"b\\"), "\"a\\\"b\\\\\"");

        let rend = simular(300, &[0.0004, 0.0002], &[0.01, 0.012], 0.1, 2);
        let r = calcular(&entrada(rend, 2, 0.6)).unwrap();
        let json = a_json(
            &r,
            &Opciones {
                tasa_libre: 0.04,
                peso_maximo: 0.6,
                puntos: 25,
            },
        );
        assert!(json.starts_with("{\"n_dias\":300,") && json.ends_with("}}"));
        assert!(json.contains("\"max_sharpe\":{\"rendimiento\":"));
    }
}
