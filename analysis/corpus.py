"""Instrument corpus: synthesized clips (committed generator) + local FL/user WAVs (gitignored)."""
import glob
import os
from math import gcd

import numpy as np
from pedalboard.io import AudioFile
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, "corpus", "local")


def read(path, sr=48000):
    with AudioFile(path) as f:
        x, fsr = f.read(f.frames), f.samplerate
    if x.shape[0] == 1:
        x = np.vstack([x, x])
    if fsr != sr:
        g = gcd(int(sr), int(fsr))
        x = resample_poly(x, sr // g, int(fsr) // g, axis=1)
    return x.astype(np.float32)


def local_clips(category=None):
    pat = os.path.join(LOCAL, category or "*", "*.wav")
    return sorted(glob.glob(pat))


def synth_clips(sr=48000, seconds=2.0):
    """Deterministic, license-free test material. Returns {name: (2, n) float32}."""
    rng = np.random.default_rng(1)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    beat = (t % 0.5) / 1.0  # time since last quarter note at 120 bpm (s)

    def saw(f):
        return 2 * ((t * f) % 1) - 1

    def norm(x, peak_db=-6):
        return x / np.abs(x).max() * 10 ** (peak_db / 20)

    kick = np.sin(2 * np.pi * np.cumsum(50 + 120 * np.exp(-((t % 0.5) / 0.03))) / sr) * np.exp(-beat / 0.15)
    sub808 = np.sin(2 * np.pi * np.cumsum(45 + 60 * np.exp(-t / 0.02)) / sr) * np.exp(-t / 1.2)
    snare = (rng.normal(size=n) * 0.6 + np.sin(2 * np.pi * 190 * t)) * np.exp(-beat / 0.08)
    hats = np.diff(rng.normal(size=n + 1)) * np.exp(-((t % 0.125) / 0.02))
    bass = saw(55) * np.exp(-beat / 0.3)
    lead = sum(saw(440 * 2 ** (d / 1200)) for d in (-12, -5, 0, 5, 12))
    pad = sum(np.sin(2 * np.pi * f * t) for f in (220, 277.18, 329.63, 440)) * np.minimum(t / 0.5, 1)
    sine = np.sin(2 * np.pi * 261.63 * t)
    clips = dict(kick=kick, sub808=sub808, snare=snare, hats=hats, bass=bass, lead=lead, pad=pad, sine261=sine)
    return {k: np.vstack([norm(v)] * 2).astype(np.float32) for k, v in clips.items()}
