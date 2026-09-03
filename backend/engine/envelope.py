"""Breakpoint automation envelopes.

An automation lane is a sparse list of (time, value) points. With zero points
the parameter is just a constant (the deck/master's base scalar). With points
written, the value is linearly interpolated between them and held flat before
the first / after the last point -- exactly like an Ableton automation lane.
"""
from __future__ import annotations

import numpy as np


def sample_envelope(points, base_value: float, t_array: np.ndarray) -> np.ndarray:
    if not points:
        return np.full(t_array.shape, float(base_value), dtype=np.float64)

    pairs = sorted(((p.time, p.value) for p in points), key=lambda p: p[0])
    xp = np.array([p[0] for p in pairs], dtype=np.float64)
    fp = np.array([p[1] for p in pairs], dtype=np.float64)
    # np.interp needs strictly increasing x; collapse exact duplicate times by
    # nudging, so a "hard cut" (two points at the same time) still behaves.
    for i in range(1, len(xp)):
        if xp[i] <= xp[i - 1]:
            xp[i] = xp[i - 1] + 1e-6
    return np.interp(t_array, xp, fp)


def times_for_range(t_start: float, n_samples: int, sr: int) -> np.ndarray:
    return t_start + np.arange(n_samples, dtype=np.float64) / sr
