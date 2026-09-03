"""DSP effects: a time-varying DJ-style filter and a Freeverb-derived reverb.

Both are implemented as plain IIR difference equations run through
scipy.signal.lfilter, so everything is pure numpy/scipy -- no external
binaries, no impulse-response assets.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter

FILTER_BLOCK = 512


def _safe_cutoff(freq: float, sr: int) -> float:
    return float(min(max(freq, 10.0), sr * 0.45))


def apply_dj_filter(signal: np.ndarray, filter_env: np.ndarray, sr: int) -> np.ndarray:
    """A one-knob DJ filter: -1 = low-pass (dark) .. 0 = bypass .. +1 = high-pass (thin).

    Processed in small blocks so the cutoff can track the automation lane.
    Low-pass and high-pass paths both run continuously and are crossfaded by
    weight, which avoids a click when the knob crosses zero and swaps topology.
    """
    n_ch, n = signal.shape
    out = np.zeros_like(signal)
    zi_lp = np.zeros((n_ch, 2))
    zi_hp = np.zeros((n_ch, 2))

    pos = 0
    while pos < n:
        end = min(pos + FILTER_BLOCK, n)
        block = signal[:, pos:end]
        f = float(np.clip(np.mean(filter_env[pos:end]), -1.0, 1.0))
        w_hp = max(f, 0.0)
        w_lp = max(-f, 0.0)
        w_dry = 1.0 - w_hp - w_lp

        lp_cut = _safe_cutoff(20000.0 * (80.0 / 20000.0) ** w_lp, sr)
        hp_cut = _safe_cutoff(20.0 * (6000.0 / 20.0) ** w_hp, sr)
        b_lp, a_lp = butter(2, lp_cut, btype="low", fs=sr)
        b_hp, a_hp = butter(2, hp_cut, btype="high", fs=sr)

        lp_out = np.empty_like(block)
        hp_out = np.empty_like(block)
        for ch in range(n_ch):
            lp_out[ch], zi_lp[ch] = lfilter(b_lp, a_lp, block[ch], zi=zi_lp[ch])
            hp_out[ch], zi_hp[ch] = lfilter(b_hp, a_hp, block[ch], zi=zi_hp[ch])

        out[:, pos:end] = block * w_dry + lp_out * w_lp + hp_out * w_hp
        pos = end

    return out


_COMB_DELAYS_MS = [25.31, 26.94, 28.96, 30.75, 32.24, 33.81, 35.31, 36.67]
_ALLPASS_DELAYS_MS = [12.61, 10.0, 7.73, 5.10]


def _comb_filter(x: np.ndarray, delay: int, feedback: float) -> np.ndarray:
    a = np.zeros(delay + 1)
    a[0] = 1.0
    a[delay] = -feedback
    return lfilter([1.0], a, x)


def _allpass_filter(x: np.ndarray, delay: int, g: float = 0.5) -> np.ndarray:
    a = np.zeros(delay + 1)
    a[0] = 1.0
    a[delay] = -g
    b = np.zeros(delay + 1)
    b[0] = -g
    b[delay] = 1.0
    return lfilter(b, a, x)


def process_reverb(
    bus: np.ndarray,
    sr: int,
    room_size: float,
    damping: float,
    width: float,
    pre_delay_ms: float,
    return_gain: float,
) -> np.ndarray:
    """bus: (2, N) float64 send signal -> returns (2, N) wet signal."""
    n_ch, n = bus.shape
    if n == 0 or not np.any(bus):
        return np.zeros_like(bus)

    pre_delay_samples = int(sr * max(pre_delay_ms, 0.0) / 1000.0)
    if pre_delay_samples > 0:
        delayed = np.zeros_like(bus)
        delayed[:, pre_delay_samples:] = bus[:, : n - pre_delay_samples]
    else:
        delayed = bus

    feedback = float(np.clip(0.28 + 0.7 * room_size, 0.28, 0.98))
    damp = float(np.clip(damping, 0.0, 0.97))
    width = float(np.clip(width, 0.0, 1.0))
    stereo_offset = int(23 * width * sr / 44100)

    wet = np.zeros_like(bus)
    for ch in range(n_ch):
        offset = stereo_offset if ch == 1 else 0
        src = delayed[ch]
        summed = np.zeros(n)
        for ms in _COMB_DELAYS_MS:
            d = max(int(sr * ms / 1000.0) + offset, 4)
            summed += _comb_filter(src, d, feedback)
        summed /= np.sqrt(len(_COMB_DELAYS_MS))
        # one-pole damping lowpass in the return path
        damped = lfilter([1.0 - damp], [1.0, -damp], summed)
        ap_out = damped
        for ms in _ALLPASS_DELAYS_MS:
            d = max(int(sr * ms / 1000.0) + offset, 4)
            ap_out = _allpass_filter(ap_out, d)
        wet[ch] = ap_out

    return wet * return_gain
