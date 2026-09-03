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

# Camelot wheel position (1..12) for each pitch class, major ("B" ring) and
# minor ("A" ring) separately -- used for rekordbox-style harmonic mixing.
_CAMELOT_MAJOR = {0: 8, 7: 9, 2: 10, 9: 11, 4: 12, 11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7}
_CAMELOT_MINOR = {9: 8, 4: 9, 11: 10, 6: 11, 1: 12, 8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7}


def key_to_camelot(key: str) -> str | None:
    """'C major' / 'A minor' -> Camelot notation ('8B' / '8A'), or None if unknown."""
    if not key or key == "?":
        return None
    parts = key.split()
    if len(parts) != 2:
        return None
    pitch, mode = parts
    if pitch not in _PITCH_CLASSES:
        return None
    idx = _PITCH_CLASSES.index(pitch)
    if mode == "major":
        num = _CAMELOT_MAJOR.get(idx)
        return f"{num}B" if num else None
    if mode == "minor":
        num = _CAMELOT_MINOR.get(idx)
        return f"{num}A" if num else None
    return None


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


def _estimate_energy(y: np.ndarray) -> float:
    """Coarse 0..1 loudness/intensity proxy from RMS, used for the Mix Assistant's
    energy-flow ranking. Not a perceptual loudness model -- just a cheap, stable
    ordering signal (quiet ambient intro vs. a slamming peak-time track)."""
    if y.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(y))))
    return round(float(np.clip(rms / 0.35, 0.0, 1.0)), 3)


def analyze_file(path: str) -> dict:
    try:
        info = sf.info(path)
        duration = float(info.frames) / float(info.samplerate) if info.samplerate else 0.0

        y, sr = librosa.load(path, sr=ANALYSIS_SR, mono=True)
        if y.size == 0:
            return {
                "duration": duration, "native_sr": info.samplerate, "bpm": None,
                "key": "?", "camelot": None, "energy": 0.0, "peaks": [],
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
        peaks = _compute_peaks(y)

        return {
            "duration": round(duration, 3),
            "native_sr": info.samplerate,
            "bpm": bpm,
            "key": key,
            "camelot": key_to_camelot(key),
            "energy": _estimate_energy(y),
            "peaks": peaks,
        }
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, must not crash a scan
        return {"error": str(exc)}
