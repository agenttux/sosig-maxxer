"""Blind A/B renders for ear tests. Writes data/listen/<clip>_<preset>_{A,B}.wav plus key.json.
Usage: python listen.py <original> <ours>"""
import json
import os
import random
import sys

import numpy as np
from pedalboard.io import AudioFile

import compare
import corpus

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "listen")


def main(orig, ours):
    os.makedirs(OUT, exist_ok=True)
    procs = {"original": compare.processor(orig), "ours": compare.processor(ours)}
    clips = {k: corpus.synth_clips(compare.SR)[k] for k in ("bass", "sub808", "lead")}
    for cat in ("loop", "vocal", "bass", "kick"):
        p = corpus.local_clips(cat)[0]
        clips[os.path.splitext(os.path.basename(p))[0]] = corpus.read(p)[:, : 6 * compare.SR]
    key, rng = {}, random.Random(7)
    for name, x in clips.items():
        for preset, knobs in compare.SPLICE.items():
            order = rng.sample(list(procs), 2)
            for label, who in zip("AB", order):
                y = np.asarray(procs[who](x, *knobs), dtype=np.float32)
                with AudioFile(os.path.join(OUT, f"{name}_{preset}_{label}.wav"), "w", compare.SR, 2) as f:
                    f.write(y)
            key[f"{name}_{preset}"] = dict(zip("AB", order))
    json.dump(key, open(os.path.join(OUT, "key.json"), "w"), indent=1)
    print(f"{len(key) * 2} files in {OUT}; answers in key.json (don't peek)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
