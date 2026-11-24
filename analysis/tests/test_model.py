"""Reference model obeys the measured laws in docs/spec/behavior.md (no plugin needed)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure as M  # noqa: E402
import model  # noqa: E402
import signals as S  # noqa: E402

SR = 48000
F = M.bin_freq(1000, SR, SR)


def gain_db(fat, color, gain, level=-60):
    x = S.sine(F, level, 0.5, SR)
    return M.rms_db(model.process(x, SR, fat, color, gain)[:, SR // 4:]) - M.rms_db(x[:, SR // 4:])


def test_drive_law_at_low_level():
    assert abs(gain_db(0, 0, 0.5) - 1.0) < 0.05
    assert abs(gain_db(0.5, 0, 0.5) - gain_db(0, 0, 0.5) - 19.5) < 0.05
    assert abs(gain_db(0, 0, 0.75) - gain_db(0, 0, 0.5) - 18.0) < 0.05


def test_ceiling_and_dc_block():
    y = model.process(S.dc_offset(0.3, 100, 0, 1.0, SR), SR, 1, 1, 1)
    assert np.abs(y).max() <= model.CEIL + 1e-12
    assert abs(y[:, SR // 2:].mean()) < 0.02


def test_limiter_slope():
    lo, hi = gain_db(1, 0, 0.5, -20), gain_db(1, 0, 0.5, -10)
    # 10 dB more input above threshold -> ~0.7 dB more RMS out (limited + clipped)
    assert 0 < (hi - 10) - (lo - 20) < 2
