"""Reference model of the measured behavior (see docs/spec/behavior.md). Pure numpy; the Rust DSP
must match this. Chain per sample, stereo-linked:
  bell(color) -> HPF ~30 Hz -> HPF ~20 Hz -> drive(fat, gain) -> peak limiter(fat) -> clip 0.989
"""
import numpy as np
from scipy.signal import lfilter

CEIL = 0.989
# two cascaded HPF biquads ((Hz, Q), (Hz, Q)); the original's corners differ per sample rate, fitted
# per rate on sub-heavy clips (time-domain null -55..-79 dB). Other rates use the 48 kHz set.
HPF_BY_SR = {
    44100: ((29.2692, 0.6541), (19.4823, 0.6519)),
    48000: ((29.9627, 0.6684), (20.1030, 0.6747)),
    88200: ((30.1388, 0.6642), (19.5884, 0.6699)),
    96000: ((29.9243, 0.6781), (19.7519, 0.6475)),
    176400: ((31.9135, 0.6936), (19.0952, 0.6680)),
    192000: ((30.8643, 0.6470), (19.5537, 0.7263)),
}
# limiter time constants are fixed in samples (tuned at 48 kHz), so they shrink at higher rates
LIM_SR = 48000
BELL_BW_OCT = 1.8928
BELL_DB_PER_COLOR = 8.0
# limiter: threshold dB = LIM_T0 + LIM_TF * fat; gain = min(1, (T/env)^LIM_K); env = one-pole on max|L|,|R|
LIM_T0, LIM_TF, LIM_ATT_MS, LIM_REL_MS, LIM_K = 0.458, 4.883, 2.539, 29.269, 0.926
# bell centre frequency (Hz) vs color, measured at 0.02 steps. Below 0.1 the bell is < 0.8 dB
# and the fit is noise, so it is clamped to the 0.1 value.
BELL_LUT = np.array([
    [0.10, 46.08], [0.12, 46.46], [0.14, 51.2], [0.16, 58.94], [0.18, 66.82], [0.2, 77.02],
    [0.22, 90.72], [0.24, 104.45], [0.26, 127.34], [0.28, 151.47], [0.3, 178.55], [0.32, 210.34],
    [0.34, 248.07], [0.36, 289.2], [0.38, 336.36], [0.4, 389.55], [0.42, 449.05], [0.44, 515.45],
    [0.46, 588.67], [0.48, 668.93], [0.5, 757.42], [0.52, 853.66], [0.54, 958.88], [0.56, 1072.84],
    [0.58, 1196.51], [0.6, 1329.73], [0.62, 1473.6], [0.64, 1627.95], [0.66, 1793.3], [0.68, 1970.27],
    [0.7, 2159.05], [0.72, 2360.25], [0.74, 2574.14], [0.76, 2801.09], [0.78, 3041.7], [0.8, 3296.52],
    [0.82, 3565.7], [0.84, 3849.93], [0.86, 4149.61], [0.88, 4465.27], [0.9, 4797.19], [0.92, 5145.87],
    [0.94, 5511.87], [0.96, 5895.85], [0.98, 6298.33], [1.0, 6720.03]])


def drive_db(fat, gain):
    return 39 * fat + 72 * gain - 35


def bell_hz(color):
    return float(np.exp(np.interp(color, BELL_LUT[:, 0], np.log(BELL_LUT[:, 1]))))


def peaking(f, db, sr, bw=BELL_BW_OCT):
    w = 2 * np.pi * f / sr
    cw, sw, A = np.cos(w), np.sin(w), 10 ** (db / 40)
    a = sw * np.sinh(np.log(2) / 2 * bw * w / sw)
    return np.array([1 + a * A, -2 * cw, 1 - a * A]), np.array([1 + a / A, -2 * cw, 1 - a / A])


def highpass(f, q, sr):
    w = 2 * np.pi * f / sr
    cw, a = np.cos(w), np.sin(w) / (2 * q)
    return np.array([(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]), np.array([1 + a, -2 * cw, 1 - a])


def hpf(sr):
    return HPF_BY_SR.get(int(sr), HPF_BY_SR[48000])


def follower(x, sr=LIM_SR, att_ms=LIM_ATT_MS, rel_ms=LIM_REL_MS):
    ca, cr = np.exp(-1000 / (att_ms * sr)), np.exp(-1000 / (rel_ms * sr))
    out, e = np.empty_like(x), 0.0
    for n, v in enumerate(x.tolist()):
        c = ca if v > e else cr
        e = c * e + (1 - c) * v
        out[n] = e
    return out


def process(x, sr, fat, color, gain):
    """x: (2, n) float. Static knobs (no smoothing)."""
    y = np.asarray(x, dtype=np.float64)
    for b, a in [peaking(bell_hz(color), BELL_DB_PER_COLOR * color, sr)] + [highpass(f, q, sr) for f, q in hpf(sr)]:
        y = lfilter(b, a, y, axis=1)
    y = y * 10 ** (drive_db(fat, gain) / 20)
    env = follower(np.abs(y).max(axis=0))
    t = 10 ** ((LIM_T0 + LIM_TF * fat) / 20)
    g = np.minimum(1.0, (t / np.maximum(env, 1e-30)) ** LIM_K)
    return np.clip(y * g, -CEIL, CEIL)
