"""Camelot wheel notation and a small local (offline, no-network) heuristic
recommendation engine for harmonic/BPM-compatible track matching.

This is the "AI Match" feature: a rule-based scorer, not a neural model --
same spirit as running a tiny local model (a la Gemini Nano) for on-device
suggestions, but deterministic and instant since the underlying signal
(BPM + musical key) is already extracted by analysis.py.
"""
from __future__ import annotations

from typing import Optional

# key label (as produced by analysis._estimate_key, e.g. "C major") -> Camelot code.
# Built from the standard Camelot wheel: each number pairs a major (B) key with
# its relative minor (A); adjacent numbers are a fifth apart.
_CAMELOT_MAJOR = {
    "C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B", "F": "7B",
    "F#": "2B", "G": "9B", "G#": "4B", "A": "11B", "A#": "6B", "B": "1B",
}
_CAMELOT_MINOR = {
    "A": "8A", "A#": "3A", "B": "10A", "C": "5A", "C#": "12A", "D": "7A",
    "D#": "2A", "E": "9A", "F": "4A", "F#": "11A", "G": "6A", "G#": "1A",
}


def camelot_of(key_label: Optional[str]) -> Optional[str]:
    """'C major' -> '8B', 'A minor' -> '8A'. Unknown/'?' -> None."""
    if not key_label or key_label == "?":
        return None
    parts = key_label.split()
    if len(parts) != 2:
        return None
    pitch, mode = parts
    table = _CAMELOT_MAJOR if mode == "major" else _CAMELOT_MINOR if mode == "minor" else None
    if table is None:
        return None
    return table.get(pitch)


def _camelot_parts(code: str):
    num = int(code[:-1])
    letter = code[-1]
    return num, letter


def key_score(camelot_a: Optional[str], camelot_b: Optional[str]) -> float:
    """0..100 harmonic-mixing compatibility between two Camelot codes."""
    if not camelot_a or not camelot_b:
        return 50.0  # unknown key: neutral, don't penalize or favor
    if camelot_a == camelot_b:
        return 100.0
    na, la = _camelot_parts(camelot_a)
    nb, lb = _camelot_parts(camelot_b)
    if la == lb:
        # same mode: adjacent on the wheel (a fifth away) mixes cleanly
        diff = min((na - nb) % 12, (nb - na) % 12)
        if diff == 1:
            return 90.0
        if diff == 2:
            return 55.0
        return 25.0
    if na == nb:
        return 85.0  # relative major/minor
    # energy-boost mix: same-letter-would-be number +2, but different letters -> weak
    return 20.0


def bpm_score(bpm_a: Optional[float], bpm_b: Optional[float]) -> float:
    """0..100 tempo compatibility, tolerant of half/double-time relationships."""
    if not bpm_a or not bpm_b or bpm_a <= 0 or bpm_b <= 0:
        return 50.0
    best_pct = min(
        abs(bpm_a - bpm_b * ratio) / bpm_a
        for ratio in (1.0, 0.5, 2.0)
    )
    # 0% off -> 100, 8%+ off -> 0, linear in between
    return max(0.0, 100.0 * (1.0 - best_pct / 0.08))


def match_score(bpm_a: Optional[float], camelot_a: Optional[str],
                 bpm_b: Optional[float], camelot_b: Optional[str]) -> float:
    ks = key_score(camelot_a, camelot_b)
    bs = bpm_score(bpm_a, bpm_b)
    return round(0.55 * ks + 0.45 * bs, 1)
