"""Offline audio analysis for the library: BPM, rough key, duration, waveform peaks."""
from __future__ import annotations

import numpy as np
import librosa
import soundfile as sf

ANALYSIS_SR = 22050
PEAK_POINTS = 800

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Camelot wheel (rekordbox/Mixed In Key harmonic-mixing notation), indexed by
# pitch class (same order as _PITCH_CLASSES). Major keys carry the "B" suffix,
# minor keys the "A" suffix; a relative major/minor pair always shares a number.
_CAMELOT_MAJOR = [8, 3, 10, 5, 12, 7, 2, 9, 4, 11, 6, 1]
_CAMELOT_MINOR = [5, 12, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10]


def key_to_camelot(key: str) -> str | None:
    """Map an "X major"/"X minor" label to its Camelot code, e.g. "C major" -> "8B"."""
    if not key or " " not in key:
        return None
    note, _, mode = key.partition(" ")
    if note not in _PITCH_CLASSES:
        return None
    idx = _PITCH_CLASSES.index(note)
    if mode == "major":
        return f"{_CAMELOT_MAJOR[idx]}B"
    if mode == "minor":
        return f"{_CAMELOT_MINOR[idx]}A"
    return None


def _estimate_energy(y: np.ndarray, bpm: float | None) -> int:
    """Rough 1-10 "energy" rating from loudness + tempo, in the spirit of
    rekordbox's track energy column. A heuristic, not a perceptual model."""
    if y.size == 0:
        return 1
    rms = float(np.sqrt(np.mean(np.square(y))))
    loudness_norm = min(1.0, rms / 0.25)
    tempo_norm = min(1.0, max(0.0, ((bpm or 120.0) - 80.0) / 120.0))
    score = 0.65 * loudness_norm + 0.35 * tempo_norm
    return int(round(1 + 9 * min(1.0, max(0.0, score))))


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
            return {"duration": duration, "native_sr": info.samplerate, "bpm": None, "key": "?", "camelot": None, "energy": 1, "peaks": []}

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
        peaks = _compute_peaks(y)

        return {
            "duration": round(duration, 3),
            "native_sr": info.samplerate,
            "bpm": bpm,
            "key": key,
            "camelot": key_to_camelot(key),
            "energy": _estimate_energy(y, bpm),
            "peaks": peaks,
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, must not crash a scan
        return {"error": str(exc)}
