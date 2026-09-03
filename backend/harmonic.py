"""Camelot wheel (harmonic mixing) support and cross-track compatibility scoring.

rekordbox displays detected key as a Camelot code (e.g. "8B") so DJs can judge
at a glance whether two tracks will mix harmonically. This module derives a
Camelot code from the "<Note> major"/"<Note> minor" strings analysis.py
already produces, and implements a small local (fully offline, no network/model
download) scoring heuristic used by the AI Mix Assistant to rank "what should
play next" -- the fusion of rekordbox's harmonic mixing wheel with an
Ableton-style arranger that has no such built-in guidance.
"""
from __future__ import annotations

from typing import Optional

# Standard Camelot wheel. Keys are spelled with sharps to match the pitch
# classes analysis.py's key estimator emits (it never emits flats).
_MAJOR_CAMELOT = {
    "C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B", "F": "7B",
    "F#": "2B", "G": "9B", "G#": "4B", "A": "11B", "A#": "6B", "B": "1B",
}
_MINOR_CAMELOT = {
    "C": "5A", "C#": "12A", "D": "7A", "D#": "2A", "E": "9A", "F": "4A",
    "F#": "11A", "G": "6A", "G#": "1A", "A": "8A", "A#": "3A", "B": "10A",
}


def camelot_for_key(key: Optional[str]) -> Optional[str]:
    """"C# minor" -> "12A". Returns None for unknown/unparseable keys."""
    if not key or key == "?":
        return None
    parts = key.split()
    if len(parts) != 2:
        return None
    note, mode = parts
    table = _MAJOR_CAMELOT if mode == "major" else _MINOR_CAMELOT if mode == "minor" else None
    if table is None:
        return None
    return table.get(note)


def _camelot_parts(code: Optional[str]):
    if not code or len(code) < 2:
        return None
    letter = code[-1]
    try:
        number = int(code[:-1])
    except ValueError:
        return None
    if letter not in ("A", "B") or not (1 <= number <= 12):
        return None
    return number, letter


def camelot_distance(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Steps around the wheel between two Camelot codes: 0 = identical,
    1 = adjacent number (same letter) or relative major/minor (same number),
    higher = less compatible. None if either code is unknown."""
    pa, pb = _camelot_parts(a), _camelot_parts(b)
    if pa is None or pb is None:
        return None
    (na, la), (nb, lb) = pa, pb
    if na == nb and la == lb:
        return 0
    if la == lb:
        ring_dist = min((na - nb) % 12, (nb - na) % 12)
        return ring_dist
    if na == nb:
        return 1  # relative major/minor
    ring_dist = min((na - nb) % 12, (nb - na) % 12)
    return ring_dist + 1


def bpm_match_ratio(bpm_a: Optional[float], bpm_b: Optional[float]) -> Optional[float]:
    """Smallest relative BPM difference once half/double-time is considered
    (DJs routinely mix a 174 track against an 87 halftime track). 0 = identical
    tempo, larger = further apart. None if either BPM is unknown."""
    if not bpm_a or not bpm_b or bpm_a <= 0 or bpm_b <= 0:
        return None
    best = None
    for factor in (0.5, 1.0, 2.0):
        rel = abs(bpm_a * factor - bpm_b) / bpm_b
        if best is None or rel < best:
            best = rel
    return best


def score_pair(ref: dict, other: dict) -> dict:
    """Local (on-device) mix-compatibility score between two library entries.

    Combines BPM proximity, Camelot harmonic distance and energy proximity
    into a single 0-100 score plus a short human-readable reason -- this is
    the "AI Mix Assistant"'s whole model: no cloud calls, no downloaded
    weights, just a transparent rule-based heuristic that runs instantly on
    a library of any size.
    """
    reasons = []

    bpm_ratio = bpm_match_ratio(ref.get("bpm"), other.get("bpm"))
    if bpm_ratio is None:
        bpm_score = 20.0
    else:
        bpm_score = max(0.0, 1.0 - bpm_ratio / 0.08) * 40.0
        if bpm_ratio < 0.01:
            reasons.append("BPM match")
        elif bpm_ratio < 0.04:
            reasons.append("BPM close")

    dist = camelot_distance(ref.get("camelot"), other.get("camelot"))
    if dist is None:
        key_score = 15.0
    elif dist == 0:
        key_score = 40.0
        reasons.append("same key")
    elif dist == 1:
        key_score = 34.0
        reasons.append("harmonic")
    elif dist == 2:
        key_score = 18.0
    else:
        key_score = 6.0

    energy_a, energy_b = ref.get("energy"), other.get("energy")
    if energy_a is None or energy_b is None:
        energy_score = 10.0
    else:
        diff = abs(energy_a - energy_b)
        energy_score = max(0.0, 1.0 - diff / 5.0) * 20.0
        if diff <= 1:
            reasons.append("energy match")

    total = round(min(100.0, bpm_score + key_score + energy_score), 1)
    return {
        "score": total,
        "bpm_score": round(bpm_score, 1),
        "key_score": round(key_score, 1),
        "energy_score": round(energy_score, 1),
        "camelot_distance": dist,
        "reasons": reasons,
    }
