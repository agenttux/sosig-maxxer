import sys
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import signals as S  # noqa: E402

SR = 48000


def test_sine_level():
    x = S.sine(1000, -6, 1, SR)
    assert x.shape == (2, SR) and x.dtype == np.float32
    assert abs(np.abs(x).max() - 10 ** (-6 / 20)) < 1e-3


def test_ess_inverse():
    x, inv = S.ess(20, 20000, 5, SR)
    ir = fftconvolve(x[0].astype(np.float64), inv)
    peak = np.argmax(np.abs(ir))
    rest = np.abs(np.delete(ir, np.arange(peak - 50, peak + 50)))
    assert 20 * np.log10(np.abs(ir[peak]) / rest.max()) >= 30


def test_level_steps_length():
    assert S.level_steps(1000, [-24, -18, -12, -6, 0], 0.5, SR).shape == (2, 120000)


def test_burst_continuous_phase():
    x = S.burst(1000, -30, -6, 0.5, 0.5, SR)[0]
    assert x.shape == (int(1.5 * SR),)
    # no jump bigger than one sample step of a full-scale 1 kHz sine
    assert np.abs(np.diff(x)).max() < 2 * np.pi * 1000 / SR * 0.51


def test_stereo_cases():
    c = S.stereo_cases(1000, -12, 0.1, SR)
    assert np.all(c["left_only"][1] == 0)
    assert np.allclose(c["anti_phase"][0], -c["anti_phase"][1])
