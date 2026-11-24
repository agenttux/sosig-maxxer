"""Measurements extracted from (dry, wet) renders. Arrays are (2, n) or 1-D; channel 0 is used
unless a function says otherwise. Levels are dBFS RMS unless noted."""
import numpy as np
from scipy.signal import fftconvolve, hilbert
from scipy.signal.windows import blackmanharris

from signals import ess_harmonic_offset

EPS = 1e-12


def mono(x):
    x = np.asarray(x, dtype=np.float64)
    return x[0] if x.ndim == 2 else x


def rms_db(x):
    x = mono(x)
    return 20 * np.log10(np.sqrt(np.mean(x**2)) + EPS)


def bin_freq(f, n, sr):
    """Nearest frequency to f that lands exactly on an FFT bin of length n."""
    return round(f * n / sr) * sr / n


# ---------------------------------------------------------------- timing

def latency_samples(dry, wet, max_lag=4800):
    d, w = mono(dry), mono(wet)[: len(mono(dry))]
    c = fftconvolve(w, d[::-1])
    mid = len(d) - 1
    seg = np.abs(c[mid - max_lag: mid + max_lag + 1])
    return int(np.argmax(seg) - max_lag)


# ---------------------------------------------------------------- static

def static_curve(levels_dbfs, wet, step_s, sr):
    """Steady-state output RMS (dBFS) per input step, from the last 50% of each step."""
    w = mono(wet)
    n = int(round(step_s * sr))
    return [rms_db(w[i * n + n // 2: (i + 1) * n]) for i in range(len(levels_dbfs))]


# ---------------------------------------------------------------- spectra of steady tones

def harmonics_at(wet, f, sr, n_harm=9, n_fft=None, skip_s=0.1):
    """Levels of H1..Hn of a steady tone at f. Returns (h1_dbfs, [dBc for H2..Hn]).
    Harmonics above Nyquist are reported as nan."""
    w = mono(wet)[int(skip_s * sr):]
    n_fft = n_fft or min(len(w), sr)
    seg = w[:n_fft] * blackmanharris(n_fft)
    spec = np.abs(np.fft.rfft(seg)) / (np.sum(blackmanharris(n_fft)) / 2)

    def level(freq):
        if freq >= sr / 2:
            return np.nan
        k = int(round(freq * n_fft / sr))
        return 20 * np.log10(spec[max(k - 3, 0): k + 4].max() + EPS)

    h1 = level(f)
    return h1, [level(k * f) - h1 for k in range(2, n_harm + 1)]


def aliasing_db(wet, f, sr, n_fft=None, skip_s=0.1):
    """Power of everything that is not DC or a harmonic of f, relative to H1 (dB)."""
    w = mono(wet)[int(skip_s * sr):]
    n_fft = n_fft or min(len(w), sr)
    spec = np.abs(np.fft.rfft(w[:n_fft] * blackmanharris(n_fft))) ** 2
    mask = np.ones_like(spec, dtype=bool)
    mask[:10] = False
    k = 1
    while k * f < sr / 2:
        b = int(round(k * f * n_fft / sr))
        mask[max(b - 6, 0): b + 7] = False
        k += 1
    b1 = int(round(f * n_fft / sr))
    return 10 * np.log10(spec[mask].sum() / spec[b1 - 6: b1 + 7].sum() + EPS)


def smpte_imd_db(wet, sr, lo=60, hi=7000, orders=4, skip_s=0.1):
    """Sum of sidebands hi +- k*lo (k=1..orders) relative to the hi tone (dB)."""
    w = mono(wet)[int(skip_s * sr):]
    n = min(len(w), sr)
    spec = np.abs(np.fft.rfft(w[:n] * blackmanharris(n))) ** 2

    def p(freq):
        b = int(round(freq * n / sr))
        return spec[b - 4: b + 5].sum()

    side = sum(p(hi + s * k * lo) for k in range(1, orders + 1) for s in (-1, 1))
    return 10 * np.log10(side / p(hi) + EPS)


def ccif_imd_db(wet, sr, fa=19000, fb=20000, skip_s=0.1):
    """Difference tone (fb-fa) and 2fa-fb product relative to fa (dB)."""
    w = mono(wet)[int(skip_s * sr):]
    n = min(len(w), sr)
    spec = np.abs(np.fft.rfft(w[:n] * blackmanharris(n))) ** 2

    def p(freq):
        b = int(round(freq * n / sr))
        return spec[max(b - 4, 0): b + 5].sum()

    return {
        "d2_db": 10 * np.log10(p(fb - fa) / p(fa) + EPS),
        "d3_db": 10 * np.log10(p(2 * fa - fb) / p(fa) + EPS),
    }


# ---------------------------------------------------------------- swept sine (Farina)

def deconvolve(wet, inv):
    return fftconvolve(mono(wet), inv)


def _linear_spec(sig, inv, sr, f0, f1, seconds, n_fft, peak=None):
    ir = deconvolve(sig, inv)
    peak = int(np.argmax(np.abs(ir))) if peak is None else peak
    gap = int(ess_harmonic_offset(2, f0, f1, seconds) * sr)
    pre = min(gap // 2, 256)
    length = min(n_fft - pre, gap - pre)
    seg = ir[peak - pre: peak + length].copy()
    fade = min(256, length // 4)
    seg[-fade:] *= np.hanning(2 * fade)[fade:]
    return np.fft.rfft(np.roll(np.pad(seg, (0, n_fft - len(seg))), -pre)), peak


def freq_response(dry, wet, inv, sr, f0, f1, seconds, n_fft=16384):
    """Linear transfer function wet/dry from an ESS render, both deconvolved with the same
    window anchored on the dry peak (so plugin latency shows up as phase).
    Returns (freqs, mag_db, phase_rad)."""
    d, peak = _linear_spec(dry, inv, sr, f0, f1, seconds, n_fft)
    w, _ = _linear_spec(wet, inv, sr, f0, f1, seconds, n_fft, peak=peak)
    h = w / (d + EPS)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    return freqs, 20 * np.log10(np.abs(h) + EPS), np.unwrap(np.angle(h))


def ess_harmonics(wet, inv, sr, f0, f1, seconds, n_harm=7, n_fft=4096):
    """Farina harmonic separation. Returns {k: (fundamental_freqs, dBc)} for k=2..n_harm."""
    ir = deconvolve(wet, inv)
    peak = int(np.argmax(np.abs(ir)))

    def chunk(k):
        off = int(round(ess_harmonic_offset(k, f0, f1, seconds) * sr))
        nxt = int(round(ess_harmonic_offset(k + 1, f0, f1, seconds) * sr))
        half = max(min((nxt - off) // 2, n_fft // 2), 32)
        c = ir[peak - off - half: peak - off + half] * np.hanning(2 * half)
        return np.fft.rfft(c, n_fft)

    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    h1 = np.abs(chunk(1))
    out = {}
    for k in range(2, n_harm + 1):
        hk = np.abs(chunk(k))
        # bin f of hk is the k-th harmonic produced by fundamental f/k... Farina: hk(f) is the
        # response at output frequency f to an input at f/k. Re-index onto the fundamental axis.
        fund = freqs / k
        h1_at_fund = np.interp(fund, freqs, h1)
        out[k] = (fund, 20 * np.log10((hk + EPS) / (h1_at_fund + EPS)))
    return out


# ---------------------------------------------------------------- envelopes

def envelope(x, sr, smooth_ms=2.0):
    e = np.abs(hilbert(mono(x)))
    n = max(int(smooth_ms * sr / 1000), 1)
    return np.convolve(e, np.ones(n) / n, mode="same")


def envelope_times(dry, wet, sr, low_s, high_s):
    """Gain-change timing for a low->high->low burst. Returns attack/release ms (time to 63% of
    the gain change after each step) plus the steady gains (dB) in each segment."""
    g = 20 * np.log10((envelope(wet, sr) + EPS) / (envelope(dry, sr) + EPS))
    a, b = int(low_s * sr), int((low_s + high_s) * sr)
    guard = int(0.005 * sr)

    def settle(seg):
        return float(np.median(seg[-len(seg) // 4:]))

    def t63(seg, start, end):
        target = start + 0.63 * (end - start)
        if abs(end - start) < 0.1:
            return 0.0
        idx = np.nonzero((seg - target) * np.sign(end - start) >= 0)[0]
        return 1000 * idx[0] / sr if len(idx) else float("nan")

    g_low, g_high = settle(g[guard:a - guard]), settle(g[a + guard:b - guard])
    g_low2 = settle(g[b + guard:-guard])
    # gain right after each step (first few ms) shows the overshoot before the detector reacts
    return {
        "gain_low_db": g_low,
        "gain_high_db": g_high,
        "gain_low_after_db": g_low2,
        "attack_ms": t63(g[a + guard // 5:b], float(np.median(g[a + 2: a + guard])), g_high),
        "release_ms": t63(g[b + guard // 5:], float(np.median(g[b + 2: b + guard])), g_low2),
    }


def memory_db(wet_after_silence, wet_after_loud, sr, seconds=0.2):
    """RMS difference between the same probe tone rendered after silence vs after loud material."""
    n = int(seconds * sr)
    a, b = mono(wet_after_silence)[:n], mono(wet_after_loud)[:n]
    return 20 * np.log10(np.sqrt(np.mean((a - b) ** 2)) / (np.sqrt(np.mean(a**2)) + EPS) + EPS)


# ---------------------------------------------------------------- stereo

def stereo_behavior(wet_cases, skip_s=0.1, sr=48000):
    s = int(skip_s * sr)

    def ch_db(x, c):
        return 20 * np.log10(np.sqrt(np.mean(np.asarray(x, np.float64)[c, s:] ** 2)) + EPS)

    lo, mo, an = wet_cases["left_only"], wet_cases["mono"], wet_cases["anti_phase"]
    return {
        "crosstalk_db": ch_db(lo, 1) - ch_db(lo, 0),
        "left_only_db": ch_db(lo, 0),
        "mono_db": ch_db(mo, 0),
        "anti_phase_db": ch_db(an, 0),
        "anti_phase_sum_db": 20 * np.log10(
            np.sqrt(np.mean((np.asarray(an, np.float64)[0, s:] + an[1, s:]) ** 2)) + EPS),
    }
