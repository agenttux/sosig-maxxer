use sosig_maxxer::dsp::{bell_hz, Fattener, CEIL};
use std::f64::consts::PI;

fn run(f: &mut Fattener, x: &[f32], knobs: (f32, f32, f32)) -> Vec<f32> {
    x.iter()
        .map(|&s| f.process_frame(s, s, knobs.0, knobs.1, knobs.2).0)
        .collect()
}

fn sine(freq: f64, amp: f64, n: usize, sr: f64) -> Vec<f32> {
    (0..n)
        .map(|i| (amp * (2.0 * PI * freq * i as f64 / sr).sin()) as f32)
        .collect()
}

/// magnitude of the DFT bin at `freq` over whole periods
fn tone(x: &[f32], freq: f64, sr: f64) -> f64 {
    let (mut re, mut im) = (0.0, 0.0);
    for (i, &v) in x.iter().enumerate() {
        let p = 2.0 * PI * freq * i as f64 / sr;
        re += v as f64 * p.cos();
        im += v as f64 * p.sin();
    }
    2.0 * (re * re + im * im).sqrt() / x.len() as f64
}

#[test]
fn defaults_are_plus_one_db_at_low_level() {
    let mut f = Fattener::new(48000.0);
    let y = run(
        &mut f,
        &sine(1000.0, 0.001, 48000, 48000.0),
        (0.0, 0.0, 0.5),
    );
    let g = 20.0 * (tone(&y[24000..], 1000.0, 48000.0) / 0.001).log10();
    assert!((g - 1.0).abs() < 0.05, "{g}");
}

#[test]
fn hot_square_stays_finite_and_under_ceiling() {
    let mut f = Fattener::new(48000.0);
    let x: Vec<f32> = (0..48000)
        .map(|i| if (i / 50) % 2 == 0 { 4.0 } else { -4.0 })
        .collect();
    let y = run(&mut f, &x, (1.0, 1.0, 1.0));
    assert!(y
        .iter()
        .all(|v| v.is_finite() && (v.abs() as f64) <= CEIL + 1e-6));
}

#[test]
fn dc_is_blocked_and_silence_goes_exactly_zero() {
    let mut f = Fattener::new(48000.0);
    let y = run(&mut f, &vec![0.5; 48000], (0.0, 0.0, 0.5));
    assert!(y[47999].abs() < 1e-3);
    let y = run(&mut f, &vec![0.0; 48000 * 4], (0.0, 0.0, 0.5));
    assert_eq!(*y.last().unwrap(), 0.0);
}

#[test]
fn knob_jump_does_not_click() {
    let mut f = Fattener::new(48000.0);
    // linear range (no limiting): unsmoothed, a +7 dB gain jump would step the waveform
    let x = sine(100.0, 0.01, 24000, 48000.0);
    let mut y = run(&mut f, &x[..4920], (0.0, 0.0, 0.5)); // jump at a wave peak
    y.extend(run(&mut f, &x[4920..], (0.0, 0.0, 0.6)));
    let step = |s: &[f32]| {
        s.windows(2)
            .map(|w| (w[1] - w[0]).abs())
            .fold(0.0, f32::max)
    };
    // while the knobs ramp, no sample jump may exceed what the settled sound itself does
    assert!(step(&y[4700..7200]) <= step(&y[14400..]) * 1.05);
}

#[test]
fn harmonics_match_across_sample_rates() {
    let h3 = |sr: f64| {
        let mut f = Fattener::new(sr as f32);
        let y = run(&mut f, &sine(1000.0, 0.1, sr as usize, sr), (1.0, 0.5, 0.5));
        let y = &y[sr as usize / 2..];
        20.0 * (tone(y, 3000.0, sr) / tone(y, 1000.0, sr)).log10()
    };
    assert!((h3(48000.0) - h3(96000.0)).abs() < 0.5);
}

#[test]
fn bell_lut_endpoints() {
    assert!((bell_hz(0.5) - 757.42).abs() < 0.01);
    assert!((bell_hz(0.0) - 46.08).abs() < 0.01);
    assert!((bell_hz(1.0) - 6720.03).abs() < 0.01);
}

#[test]
fn face_goes_from_smile_to_gritted() {
    use sosig_maxxer::editor::face_shape;
    let (calm, mad) = (face_shape(0.0), face_shape(1.0));
    assert!(calm.smile > 0.0 && mad.smile < 0.0);
    assert_eq!((calm.teeth, mad.teeth), (0.0, 1.0));
    assert!(face_shape(0.59).teeth == 0.0 && calm.lid < mad.lid && calm.brow == 0.0);
}

#[test]
fn knobs_ramp_in_from_defaults_after_reset() {
    // like the original: gain starts at its 0.5 default (+1 dB) and settles to 0 (-35 dB) in ~10 ms
    let mut f = Fattener::new(48000.0);
    let y = run(&mut f, &sine(1000.0, 0.1, 4800, 48000.0), (0.0, 0.0, 0.0));
    let first = y[..480].iter().fold(0f32, |m, v| m.max(v.abs()));
    let last = y[4320..].iter().fold(0f32, |m, v| m.max(v.abs()));
    assert!(first > 0.05 && last < 0.003, "{first} {last}");
}

#[test]
fn gain_displays_db_relative_to_default() {
    use nih_plug::prelude::Param;
    let p = sosig_maxxer::SosigParams::default();
    assert_eq!(p.gain.normalized_value_to_string(0.5, true), "+0.0 dB");
    assert_eq!(p.gain.normalized_value_to_string(1.0, true), "+36.0 dB");
    assert_eq!(p.gain.normalized_value_to_string(0.0, true), "-36.0 dB");
    assert_eq!(p.gain.normalized_value_to_string(0.504, true), "+0.3 dB"); // 0.288 dB
    assert_eq!(p.gain.normalized_value_to_string(0.4995, true), "+0.0 dB"); // no "-0.0"
    assert!((p.gain.string_to_normalized_value("+3.6 dB").unwrap() - 0.55).abs() < 1e-6);
}
