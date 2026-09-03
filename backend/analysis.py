"""Offline audio analysis for the library: BPM, rough key, duration, waveform peaks."""
from __future__ import annotations

from typing import Optional

import numpy as np
import librosa
import soundfile as sf

from harmonic import camelot_for_key

ANALYSIS_SR = 22050
PEAK_POINTS = 800

# Bumped whenever analyze_file's output shape changes so library.py knows to
# transparently re-analyze cache entries written by an older version instead
# of silently serving them without the new fields.
ANALYSIS_VERSION = 2

# Empirical RMS band for "typical" DJ material at ANALYSIS_SR, used to map
# raw loudness into a 1-10 energy rating. Not a perceptual loudness model --
# just a stable, cheap signal the AI Mix Assistant uses to avoid pairing a
# warm-up ambient track against a peak-time banger.
_ENERGY_RMS_FLOOR = 0.02
_ENERGY_RMS_CEIL = 0.25


def _estimate_energy(y: np.ndarray) -> Optional[int]:
    if y.size == 0:
        return None
    rms = float(np.mean(librosa.feature.rms(y=y)))
    frac = (rms - _ENERGY_RMS_FLOOR) / (_ENERGY_RMS_CEIL - _ENERGY_RMS_FLOOR)
    frac = min(max(frac, 0.0), 1.0)
    return int(round(1 + frac * 9))

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _estimate_key(y: np.ndarray, sr: int) -> str:
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    profile = chroma.mean(axis=1)
    if not np.any(profile):
        return "?"
    best_label, best_score = "?", -2.0
    for i in range(12):
        for label_suffix, base in (("major", _MAJOR_PROFILE), ("minor", _MINOR_PROFILE)):
            template = np.roll(base, i)
            score = float(np.corrcoef(profile, template)[0, 1])
            if score > best_score:
                best_score = score
                best_label = f"{_PITCH_CLASSES[i]} {label_suffix}"
    return best_label


def _compute_peaks(y: np.ndarray, n_points: int = PEAK_POINTS) -> list:
    n = len(y)
    if n == 0:
        return []
    chunk = max(1, n // n_points)
    peaks = []
    for i in range(0, n, chunk):
        seg = y[i : i + chunk]
        if seg.size == 0:
            continue
        peaks.append([round(float(seg.min()), 4), round(float(seg.max()), 4)])
    return peaks


def analyze_file(path: str) -> dict:
    try:
        info = sf.info(path)
        duration = float(info.frames) / float(info.samplerate) if info.samplerate else 0.0

        y, sr = librosa.load(path, sr=ANALYSIS_SR, mono=True)
        if y.size == 0:
            return {
                "duration": duration, "native_sr": info.samplerate, "bpm": None, "key": "?",
                "camelot": None, "energy": None, "peaks": [], "schema_version": ANALYSIS_VERSION,
            }

        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0]) if tempo is not None else None
        if bpm is not None and bpm > 0:
            # fold obviously-halved/doubled estimates into a sane DJ range
            while bpm < 80:
                bpm *= 2
            while bpm > 175:
                bpm /= 2
            bpm = round(bpm, 2)
        else:
            bpm = None

        key = _estimate_key(y, sr)
        camelot = camelot_for_key(key)
        energy = _estimate_energy(y)
        peaks = _compute_peaks(y)

        return {
            "duration": round(duration, 3),
            "native_sr": info.samplerate,
            "bpm": bpm,
            "key": key,
            "camelot": camelot,
            "energy": energy,
            "peaks": peaks,
            "schema_version": ANALYSIS_VERSION,
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, must not crash a scan
        return {"error": str(exc)}
