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

# Camelot wheel (harmonic mixing notation used by rekordbox/Serato/Mixed In Key):
# same code = perfect match, +-1 on the same letter = adjacent key, same number
# different letter = relative major/minor. Numbers follow the circle of fifths.
_CAMELOT_MAJOR = {"C": 8, "G": 9, "D": 10, "A": 11, "E": 12, "B": 1,
                  "F#": 2, "C#": 3, "G#": 4, "D#": 5, "A#": 6, "F": 7}
_CAMELOT_MINOR = {"A": 8, "E": 9, "B": 10, "F#": 11, "C#": 12, "G#": 1,
                  "D#": 2, "A#": 3, "F": 4, "C": 5, "G": 6, "D": 7}


def _key_to_camelot(key: str) -> str | None:
    parts = key.split()
    if len(parts) != 2:
        return None
    note, mode = parts
    table = _CAMELOT_MAJOR if mode == "major" else _CAMELOT_MINOR if mode == "minor" else None
    if table is None or note not in table:
        return None
    return f"{table[note]}{'B' if mode == 'major' else 'A'}"


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
            return {"duration": duration, "native_sr": info.samplerate, "bpm": None, "key": "?", "peaks": []}

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
            "camelot": _key_to_camelot(key) if key != "?" else None,
            "peaks": peaks,
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, must not crash a scan
        return {"error": str(exc)}
