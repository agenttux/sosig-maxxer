"""Null + loudness + spectrum comparison of two processors over the corpus and named presets.
Usage: python compare.py <ref.vst3|.component|model> <test.vst3|model> [rate,...]   (exit 1 on failure)
Null = phase cancellation: residual of ref - test, relative to ref, in dB."""
import hashlib
import os
import sys
from multiprocessing import Pool

import numpy as np
import pyloudnorm

import corpus
import model
import render

RATES = (44100, 48000, 88200, 96000, 192000)
SPLICE = {"F55C20": (0.55, 0.2, 0.5), "F90C35": (0.9, 0.35, 0.5), "F8C10": (0.08, 0.1, 0.5)}
EXTREME = {"F1C1G1": (1, 1, 1), "F0C0G1": (0, 0, 1), "F1C0G0": (1, 0, 0), "F30C70G75": (0.3, 0.7, 0.75)}
NULL_MAX = {**{k: -25 for k in SPLICE}, **{k: -20 for k in EXTREME}}
LUFS_TOL, THIRD_OCT_TOL = 0.3, 1.0


CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache")


def bundle_stamp(path):
    """Newest mtime inside a plugin bundle, so a rebuilt plugin never hits a stale cache entry."""
    path = os.path.expanduser(path)
    return max((os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs),
               default=os.path.getmtime(path))


def processor(spec, sr):
    if spec == "model":
        return lambda x, f, c, g: model.process(x, sr, f, c, g)
    plug, stamp = None, f"{os.path.abspath(os.path.expanduser(spec))}|{bundle_stamp(spec)}"
    pad = sr // 4  # let the plugin's 10 ms param smoother settle from its defaults after reset

    def run(x, f, c, g):
        nonlocal plug
        key = hashlib.sha1(f"{stamp}|{sr}|{f}|{c}|{g}".encode() + x.tobytes()).hexdigest()
        path = os.path.join(CACHE, key + ".npy")
        if os.path.exists(path):
            return np.load(path)
        plug = plug or render.load(spec)  # load lazily: a fully cached run never opens the plugin
        y = render.render(plug, np.pad(x, ((0, 0), (pad, 0))), sr, f, c, g, tail_s=0)[:, pad:]
        os.makedirs(CACHE, exist_ok=True)
        np.save(path, y)
        return y
    return run


def third_octave_db(x, sr):
    spec = np.abs(np.fft.rfft(x[0] * np.hanning(x.shape[1]))) ** 2
    freqs = np.fft.rfftfreq(x.shape[1], 1 / sr)
    centres = 1000 * 2.0 ** (np.arange(-17, 14) / 3)  # 20 Hz .. 16 kHz
    return np.array([10 * np.log10(spec[(freqs >= c * 2 ** -(1 / 6)) & (freqs < c * 2 ** (1 / 6))].sum() + 1e-20)
                     for c in centres])


def k_loudness(x, sr):
    """Ungated K-weighted loudness (LUFS without BS.1770 gating). Gating flips whole 400 ms blocks
    in or out on short clips, which read as 0.4 LU 'errors' on clips that null at -37 dB."""
    m = pyloudnorm.Meter(sr)
    for f in m._filters.values():
        x = np.stack([f.apply_filter(ch) for ch in x])
    return -0.691 + 10 * np.log10(np.sum(np.mean(x ** 2, axis=1)) + 1e-20)


def compare(a, b, sr):
    # skip onset: the model starts with an empty limiter envelope. At 44.1 kHz the original also
    # bursts for up to ~0.6 s after reset/silence (host/AU state, not copied; see behavior.md)
    skip = int(0.6 * sr) if sr == 44100 else sr // 5
    a, b = a[:, skip:], b[:, skip:]
    null = 20 * np.log10(np.sqrt(np.mean((a - b) ** 2)) / (np.sqrt(np.mean(a ** 2)) + 1e-12) + 1e-12)
    lufs = k_loudness(b, sr) - k_loudness(a, sr)
    ta, tb = third_octave_db(a, sr), third_octave_db(b, sr)
    loud = ta > ta.max() - 20  # bands carrying the sound; a -30 dB residual swamps quieter ones
    return null, lufs, np.abs(tb - ta)[loud].max()


def main(ref_spec, test_spec, rates=RATES):
    # clips are fed as-is at every rate (same samples, so pitch shifts); fine for a null test
    clips = corpus.synth_clips(48000)
    clips.update({p.split("/")[-1]: corpus.read(p)[:, : 3 * 48000] for p in corpus.local_clips()
                  if corpus.read(p).shape[1] > 48000})
    # one process per rate; renders are cached in data/cache/ keyed by bundle mtime, rate, knobs, audio
    with Pool(min(len(rates), os.cpu_count() or 1)) as pool:
        results = pool.starmap(run_rate, [(ref_spec, test_spec, clips, sr) for sr in rates])
    for lines, _ in results:
        print("\n".join(lines))
    return 1 if sum(f for _, f in results) else 0


def run_rate(ref_spec, test_spec, clips, sr):
    ref, test = processor(ref_spec, sr), processor(test_spec, sr)
    fails, lines = 0, []
    for name, (f, c, g) in {**SPLICE, **EXTREME}.items():
        rows = [compare(ref(x, f, c, g), test(x, f, c, g), sr) for x in clips.values()]
        null, lufs, oct3 = (np.array(v) for v in zip(*rows))
        bad = (np.nanmax(null) > NULL_MAX[name]) or (name in SPLICE and (
            np.nanmax(np.abs(lufs)) > LUFS_TOL or np.nanmax(oct3) > THIRD_OCT_TOL))
        fails += bad
        worst = list(clips)[int(np.nanargmax(null))]
        lines.append(f"{'FAIL' if bad else 'ok  '} {sr:6d} {name:10s} null worst {np.nanmax(null):6.1f} ({worst}) median {np.nanmedian(null):6.1f} dB"
              f" | LUFS worst {np.nanmax(np.abs(lufs)):.2f} | 1/3-oct worst {np.nanmax(oct3):.2f} dB  ({len(rows)} clips)")
        print(lines[-1], flush=True)  # progress; the ordered table prints at the end
    return lines, fails


if __name__ == "__main__":
    rates = tuple(int(r) for r in sys.argv[3].split(",")) if len(sys.argv) > 3 else RATES
    sys.exit(main(sys.argv[1], sys.argv[2], rates))
