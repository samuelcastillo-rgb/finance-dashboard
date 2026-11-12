//! `frontera`: lee los rendimientos por la entrada estándar y escribe el JSON del resultado.
//!
//!     frontera < entrada.txt > resultado.json
//!
//! El formato de entrada está documentado en `leer_entrada` (src/lib.rs). Lo usa
//! scripts/actualizar_datos.py a través de finanzas/frontera.py.

use std::io::Read;
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut texto = String::new();
    if let Err(e) = std::io::stdin().read_to_string(&mut texto) {
        eprintln!("frontera: no se pudo leer la entrada: {e}");
        return ExitCode::FAILURE;
    }
    let resultado = optimizador::leer_entrada(&texto)
        .and_then(|e| optimizador::calcular(&e).map(|r| optimizador::a_json(&r, &e.opciones)));
    match resultado {
        Ok(json) => {
            println!("{json}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("frontera: {e}");
            ExitCode::FAILURE
        }
    }
}
