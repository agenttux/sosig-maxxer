//! Signal path, written from docs/spec/behavior.md (reference: analysis/model.py).
//! bell(color) -> 2x HPF -> drive(fat, gain) -> stereo-linked peak limiter -> hard clip.
//! No host-framework types here so it can be tested on its own.

use std::f64::consts::{LN_2, PI};

pub const CEIL: f64 = 0.989;
/// Two cascaded HPF biquads ((Hz, Q), (Hz, Q)). The measured corners differ per sample rate;
/// rates not listed use the 48 kHz set.
const HPF_BY_SR: [(f64, [(f64, f64); 2]); 6] = [
    (44100.0, [(29.2692, 0.6541), (19.4823, 0.6519)]),
    (48000.0, [(29.9627, 0.6684), (20.1030, 0.6747)]),
    (88200.0, [(30.1388, 0.6642), (19.5884, 0.6699)]),
    (96000.0, [(29.9243, 0.6781), (19.7519, 0.6475)]),
    (176400.0, [(31.9135, 0.6936), (19.0952, 0.6680)]),
    (192000.0, [(30.8643, 0.6470), (19.5537, 0.7263)]),
];
/// Limiter time constants are fixed in samples (tuned at 48 kHz), so they shrink at higher rates.
const LIM_SR: f64 = 48000.0;
/// Knob values the smoother ramps from after a reset (the parameter defaults).
const RESET_KNOBS: [f64; 3] = [0.0, 0.0, 0.5];
const BELL_BW_OCT: f64 = 1.8928;
const BELL_DB_PER_COLOR: f64 = 8.0;
const LIM_T0: f64 = 0.458;
const LIM_TF: f64 = 4.883;
const LIM_ATT_MS: f64 = 2.539;
const LIM_REL_MS: f64 = 29.269;
const LIM_K: f64 = 0.926;
const SMOOTH_MS: f64 = 10.0;
/// (color, bell centre Hz), measured. Interpolated in log-frequency, clamped at both ends.
const BELL_LUT: [(f64, f64); 46] = [
    (0.10, 46.08),
    (0.12, 46.46),
    (0.14, 51.2),
    (0.16, 58.94),
    (0.18, 66.82),
    (0.2, 77.02),
    (0.22, 90.72),
    (0.24, 104.45),
    (0.26, 127.34),
    (0.28, 151.47),
    (0.3, 178.55),
    (0.32, 210.34),
    (0.34, 248.07),
    (0.36, 289.2),
    (0.38, 336.36),
    (0.4, 389.55),
    (0.42, 449.05),
    (0.44, 515.45),
    (0.46, 588.67),
    (0.48, 668.93),
    (0.5, 757.42),
    (0.52, 853.66),
    (0.54, 958.88),
    (0.56, 1072.84),
    (0.58, 1196.51),
    (0.6, 1329.73),
    (0.62, 1473.6),
    (0.64, 1627.95),
    (0.66, 1793.3),
    (0.68, 1970.27),
    (0.7, 2159.05),
    (0.72, 2360.25),
    (0.74, 2574.14),
    (0.76, 2801.09),
    (0.78, 3041.7),
    (0.8, 3296.52),
    (0.82, 3565.7),
    (0.84, 3849.93),
    (0.86, 4149.61),
    (0.88, 4465.27),
    (0.9, 4797.19),
    (0.92, 5145.87),
    (0.94, 5511.87),
    (0.96, 5895.85),
    (0.98, 6298.33),
    (1.0, 6720.03),
];

pub fn bell_hz(color: f64) -> f64 {
    let i = BELL_LUT
        .partition_point(|&(c, _)| c <= color)
        .clamp(1, BELL_LUT.len() - 1);
    let ((c0, f0), (c1, f1)) = (BELL_LUT[i - 1], BELL_LUT[i]);
    let t = ((color - c0) / (c1 - c0)).clamp(0.0, 1.0);
    (f0.ln() + t * (f1.ln() - f0.ln())).exp()
}

#[derive(Clone, Copy, Default)]
struct Biquad {
    b: [f64; 3],
    a: [f64; 2],
    s: [f64; 2],
}

impl Biquad {
    fn set(&mut self, b: [f64; 3], a: [f64; 3]) {
        self.b = [b[0] / a[0], b[1] / a[0], b[2] / a[0]];
        self.a = [a[1] / a[0], a[2] / a[0]];
    }

    fn peaking(&mut self, f: f64, db: f64, sr: f64) {
        let w = 2.0 * PI * f / sr;
        let (sw, cw, a) = (w.sin(), w.cos(), 10f64.powf(db / 40.0));
        let al = sw * (LN_2 / 2.0 * BELL_BW_OCT * w / sw).sinh();
        self.set(
            [1.0 + al * a, -2.0 * cw, 1.0 - al * a],
            [1.0 + al / a, -2.0 * cw, 1.0 - al / a],
        );
    }

    fn highpass(&mut self, f: f64, q: f64, sr: f64) {
        let w = 2.0 * PI * f / sr;
        let (cw, al) = (w.cos(), w.sin() / (2.0 * q));
        let h = (1.0 + cw) / 2.0;
        self.set([h, -2.0 * h, h], [1.0 + al, -2.0 * cw, 1.0 - al]);
    }

    #[inline]
    fn tick(&mut self, x: f64) -> f64 {
        let y = self.b[0] * x + self.s[0];
        self.s[0] = self.b[1] * x - self.a[0] * y + self.s[1];
        self.s[1] = self.b[2] * x - self.a[1] * y;
        // flush decaying tails so silence in gives exact zeros out (and no denormals)
        if self.s[0].abs() < 1e-25 && self.s[1].abs() < 1e-25 {
            self.s = [0.0; 2];
        }
        y
    }
}

pub struct Fattener {
    sr: f64,
    bell: [Biquad; 2],
    hpf: [[Biquad; 2]; 2],
    bell_color: f64,
    env: f64,
    att: f64,
    rel: f64,
    smooth: f64,
    knobs: [f64; 3],
}

impl Fattener {
    pub fn new(sr: f32) -> Self {
        let mut f = Fattener {
            sr: 0.0,
            bell: Default::default(),
            hpf: Default::default(),
            bell_color: -1.0,
            env: 0.0,
            att: 0.0,
            rel: 0.0,
            smooth: 0.0,
            knobs: RESET_KNOBS,
        };
        f.reset(sr);
        f
    }

    pub fn reset(&mut self, sr: f32) {
        self.sr = sr as f64;
        let pole = |ms: f64, sr: f64| (-1000.0 / (ms * sr)).exp();
        self.att = pole(LIM_ATT_MS, LIM_SR);
        self.rel = pole(LIM_REL_MS, LIM_SR);
        self.smooth = pole(SMOOTH_MS, self.sr);
        let hpf = HPF_BY_SR
            .iter()
            .find(|(r, _)| *r == self.sr)
            .unwrap_or(&HPF_BY_SR[1])
            .1;
        for ch in &mut self.hpf {
            for (bq, &(f, q)) in ch.iter_mut().zip(&hpf) {
                *bq = Biquad::default();
                bq.highpass(f, q, self.sr);
            }
        }
        self.bell = Default::default();
        self.bell_color = -1.0;
        self.env = 0.0;
        self.knobs = RESET_KNOBS; // like the original: knobs ramp in from their defaults
    }

    pub fn sample_rate(&self) -> f32 {
        self.sr as f32
    }

    pub fn latency_samples(&self) -> u32 {
        0
    }

    /// One stereo frame. Knob targets are 0..1; they are smoothed here (one-pole, 10 ms).
    pub fn process_frame(&mut self, l: f32, r: f32, fat: f32, color: f32, gain: f32) -> (f32, f32) {
        let target = [fat as f64, color as f64, gain as f64];
        for (v, t) in self.knobs.iter_mut().zip(target) {
            *v = t + self.smooth * (*v - t);
        }
        let [fat, color, gain] = self.knobs;

        if (color - self.bell_color).abs() > 1e-6 {
            self.bell_color = color;
            let (f, db) = (bell_hz(color), BELL_DB_PER_COLOR * color);
            for bq in &mut self.bell {
                bq.peaking(f, db, self.sr);
            }
        }

        let drive = 10f64.powf((39.0 * fat + 72.0 * gain - 35.0) / 20.0);
        let mut y = [l as f64, r as f64];
        for (c, y) in y.iter_mut().enumerate() {
            let v = self.bell[c].tick(*y);
            let v = self.hpf[c][0].tick(v);
            *y = self.hpf[c][1].tick(v) * drive;
        }

        let peak = y[0].abs().max(y[1].abs());
        let c = if peak > self.env { self.att } else { self.rel };
        self.env = c * self.env + (1.0 - c) * peak;
        let t = 10f64.powf((LIM_T0 + LIM_TF * fat) / 20.0);
        let g = if self.env > t {
            (t / self.env).powf(LIM_K)
        } else {
            1.0
        };

        let out = |v: f64| (v * g).clamp(-CEIL, CEIL) as f32;
        (out(y[0]), out(y[1]))
    }
}
