//! Tiny Rust fixture so ref-resolve has a real .rs file to resolve symbols against.
//! Not wired to anything - it only exists to exercise the Rust definition patterns.

pub enum DefectKind {
    Clean,
    StaticBias(f64),
    Alias(u32),
}

pub struct DefectHooks {
    pub bias: f64,
}

impl DefectHooks {
    pub fn warp_draw(&self, u: f64) -> f64 {
        u + self.bias
    }
}

pub fn keyed_uniform(seed: u64, step: u64) -> f64 {
    let _ = (seed, step);
    0.0
}
