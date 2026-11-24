"""Test-signal generators. Every function returns float32 arrays shaped (2, n)."""
import numpy as np


def db2lin(db):
    return 10.0 ** (np.asarray(db, dtype=np.float64) / 20.0)


def _stereo(x):
    x = np.asarray(x, dtype=np.float32)
    return np.stack([x, x]) if x.ndim == 1 else x


def sine(freq_hz, dbfs, seconds, sr, phase=0.0):
    t = np.arange(int(round(seconds * sr))) / sr
    return _stereo(db2lin(dbfs) * np.sin(2 * np.pi * freq_hz * t + phase))


def ess(f0, f1, seconds, sr, dbfs=-12.0, fade_s=0.02):
    """Farina exponential sine sweep and its inverse filter (mono 1-D)."""
    n = int(round(seconds * sr))
    t = np.arange(n) / sr
    rate = np.log(f1 / f0)
    x = np.sin(2 * np.pi * f0 * seconds / rate * (np.exp(t * rate / seconds) - 1))
    nf = int(fade_s * sr)
    win = np.ones(n)
    win[:nf] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, nf))
    win[-nf:] = win[:nf][::-1]
    x = x * win
    inv = x[::-1] * np.exp(-t * rate / seconds)
    # normalise so that x * inv has unit peak in the frequency band
    spec = np.abs(np.fft.rfft(x, 2 * n) * np.fft.rfft(inv, 2 * n))
    f = np.fft.rfftfreq(2 * n, 1 / sr)
    band = (f > f0 * 2) & (f < f1 / 2)
    inv = inv / np.median(spec[band])
    return _stereo(db2lin(dbfs) * x), inv.astype(np.float64)


def ess_harmonic_offset(k, f0, f1, seconds):
    """Seconds by which harmonic k's impulse precedes the linear one after deconvolution."""
    return seconds * np.log(k) / np.log(f1 / f0)


def level_steps(freq_hz, levels_dbfs, step_s, sr):
    n = int(round(step_s * sr))
    t = np.arange(n * len(levels_dbfs)) / sr
    amp = np.repeat(db2lin(levels_dbfs), n)
    return _stereo(amp * np.sin(2 * np.pi * freq_hz * t))


def burst(freq_hz, low_dbfs, high_dbfs, low_s, high_s, sr):
    """low -> high -> low envelope tone, for attack/release timing."""
    return np.concatenate(
        [sine(freq_hz, low_dbfs, low_s, sr),
         _phase_cont(freq_hz, high_dbfs, high_s, sr, low_s),
         _phase_cont(freq_hz, low_dbfs, low_s, sr, low_s + high_s)], axis=1)


def _phase_cont(freq_hz, dbfs, seconds, sr, t0):
    return sine(freq_hz, dbfs, seconds, sr, phase=2 * np.pi * freq_hz * t0)


def impulse(seconds, sr, dbfs=-6.0):
    x = np.zeros(int(round(seconds * sr)))
    x[sr // 100] = db2lin(dbfs)
    return _stereo(x)


def two_tone(f_a, f_b, dbfs, ratio_db, seconds, sr):
    """f_a at `dbfs`, f_b `ratio_db` below it (SMPTE: 60/7000, 12 dB; CCIF: 19k/20k, 0 dB)."""
    t = np.arange(int(round(seconds * sr))) / sr
    a = db2lin(dbfs)
    x = a * np.sin(2 * np.pi * f_a * t) + a * db2lin(-ratio_db) * np.sin(2 * np.pi * f_b * t)
    return _stereo(x / (1 + db2lin(-ratio_db)))


def smpte(seconds, sr, dbfs=-12.0):
    return two_tone(60, 7000, dbfs, 12.04, seconds, sr)


def ccif(seconds, sr, dbfs=-12.0):
    return two_tone(19000, 20000, dbfs, 0.0, seconds, sr)


def stereo_cases(freq_hz, dbfs, seconds, sr):
    s = sine(freq_hz, dbfs, seconds, sr)[0]
    z = np.zeros_like(s)
    return {
        "left_only": np.stack([s, z]),
        "mono": np.stack([s, s]),
        "anti_phase": np.stack([s, -s]),
    }


def asym_pulse(freq_hz, dbfs, duty, seconds, sr):
    """Rectangular wave with given duty cycle, DC removed -> asymmetric peaks."""
    t = np.arange(int(round(seconds * sr))) / sr
    x = ((t * freq_hz) % 1.0 < duty).astype(np.float64)
    x -= x.mean()
    return _stereo(db2lin(dbfs) * x / np.abs(x).max())


def dc_offset(offset, freq_hz, dbfs, seconds, sr):
    return _stereo(sine(freq_hz, dbfs, seconds, sr)[0] + offset)
