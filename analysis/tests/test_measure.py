"""Each measurement checked against a synthetic system with a known answer."""
import sys
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure as M  # noqa: E402
import signals as S  # noqa: E402

SR = 48000


def test_latency():
    x = np.random.default_rng(0).normal(0, 0.1, (2, SR // 2))
    y = np.pad(x, ((0, 0), (64, 0)))[:, : x.shape[1]]
    assert M.latency_samples(x, y) == 64


def test_static_curve_gain():
    levels = list(range(-48, 1, 6))
    x = S.level_steps(1000, levels, 0.25, SR)
    out = M.static_curve(levels, 0.5 * x, 0.25, SR)
    inp = M.static_curve(levels, x, 0.25, SR)
    assert np.allclose(np.array(out) - np.array(inp), -6.02, atol=0.05)


def test_harmonics_tanh_odd():
    f = M.bin_freq(1000, SR, SR)
    y = np.tanh(3 * S.sine(f, -6, 1.2, SR))
    _, h = M.harmonics_at(y, f, SR)
    assert h[1] > h[0] + 40  # H3 >> H2
    # analytic H3 of tanh(3*0.5 sin): Fourier coefficient by numeric integration
    th = np.linspace(0, 2 * np.pi, 1 << 16, endpoint=False)
    w = np.tanh(3 * 10 ** (-6 / 20) * np.sin(th))
    b1, b3 = (2 * np.mean(w * np.sin(k * th)) for k in (1, 3))
    assert abs(h[1] - 20 * np.log10(abs(b3) / abs(b1))) < 1.0


def test_harmonics_asym_even():
    f = M.bin_freq(1000, SR, SR)
    x = S.sine(f, -6, 1.2, SR)
    _, h = M.harmonics_at(x + 0.1 * x**2, f, SR)
    assert h[0] > -40


def test_ess_harmonics_match_steady():
    x, inv = S.ess(20, 20000, 6, SR, dbfs=-6)
    y = np.tanh(3 * x.astype(np.float64)) + 0.05 * x**2
    hs = M.ess_harmonics(y, inv, SR, 20, 20000, 6)
    f = M.bin_freq(1000, SR, SR)
    s = S.sine(f, -6, 1.2, SR).astype(np.float64)
    _, steady = M.harmonics_at(np.tanh(3 * s) + 0.05 * s**2, f, SR)
    for k in (2, 3):
        fund, dbc = hs[k]
        assert abs(np.interp(1000, fund, dbc) - steady[k - 2]) < 2.0


def test_freq_response_lowpass():
    x, inv = S.ess(20, 20000, 4, SR)
    b, a = [0.2], [1, -0.8]  # one-pole lowpass, DC gain 1
    y = lfilter(b, a, x[0].astype(np.float64))
    f, mag, _ = M.freq_response(x, y, inv, SR, 20, 20000, 4)
    w = 2 * np.pi * 5000 / SR
    expect = 20 * np.log10(abs(0.2 / (1 - 0.8 * np.exp(-1j * w))))
    assert abs(np.interp(5000, f, mag) - expect) < 0.3
    assert abs(np.interp(100, f, mag)) < 0.3


def test_envelope_times():
    dry = S.burst(1000, -30, -6, 0.5, 0.5, SR).astype(np.float64)
    # feed-forward compressor: gain follows a one-pole on the level, 10 ms att / 100 ms rel
    lvl = np.abs(dry[0])
    env = np.zeros_like(lvl)
    aa, ar = np.exp(-1 / (0.010 * SR)), np.exp(-1 / (0.100 * SR))
    e = 0.0
    peak = lvl.copy()
    # peak-hold the rectified sine over one cycle so the detector sees the envelope, not ripple
    from scipy.ndimage import maximum_filter1d
    peak = maximum_filter1d(lvl, 48)
    for i, v in enumerate(peak):
        c = aa if v > e else ar
        e = c * e + (1 - c) * v
        env[i] = e
    gain = 1 / (1 + 4 * env)
    t = M.envelope_times(dry, dry * gain, SR, 0.5, 0.5)
    assert t["gain_high_db"] < t["gain_low_db"] - 3
    # 63% of a gain change on a nonlinear gain curve is not exactly tau; allow 35%
    assert 5 < t["attack_ms"] < 16
    assert 50 < t["release_ms"] < 160


def test_envelope_times_memoryless():
    dry = S.burst(1000, -30, -6, 0.5, 0.5, SR)
    t = M.envelope_times(dry, np.tanh(2 * dry), SR, 0.5, 0.5)
    assert t["attack_ms"] < 3 and t["release_ms"] < 3


def test_stereo_independent():
    c = S.stereo_cases(1000, -12, 0.5, SR)
    wet = {k: np.tanh(2 * v) for k, v in c.items()}
    r = M.stereo_behavior(wet)
    assert r["crosstalk_db"] < -100
    assert abs(r["mono_db"] - r["left_only_db"]) < 0.01


def test_aliasing_clean_vs_hard_clip():
    f = M.bin_freq(9000, SR, SR)
    x = S.sine(f, -3, 1.2, SR)
    assert M.aliasing_db(x, f, SR) < -100
    assert M.aliasing_db(np.clip(3 * x, -1, 1), f, SR) > -60


def test_smpte_imd():
    x = S.smpte(1.2, SR)
    assert M.smpte_imd_db(x, SR) < -90
    assert M.smpte_imd_db(np.tanh(4 * x), SR) > -40
