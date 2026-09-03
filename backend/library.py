"""Recursive folder scan + on-disk JSON cache of per-file analysis."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from analysis import analyze_file, ANALYSIS_VERSION

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".ogg", ".m4a"}
MAX_CUES_PER_TRACK = 8
_lock = threading.Lock()


def _is_stale(cached: dict) -> bool:
    return "error" not in cached and cached.get("schema_version") != ANALYSIS_VERSION


def _load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _entry_for(path: str, cache: dict) -> dict:
    rec = dict(cache[path])
    rec["path"] = path
    rec["filename"] = os.path.basename(path)
    return rec


def _analyze_preserving_cues(path: str, mtime, cached: Optional[dict]) -> dict:
    result = analyze_file(path)
    result["mtime"] = mtime
    if cached and "cues" in cached:
        result["cues"] = cached["cues"]  # hot cues are user data, not derived from audio
    return result


def scan_folder(root: str, cache_path: Path) -> list:
    root = str(Path(root).expanduser())
    with _lock:
        cache = _load_cache(cache_path)

        found = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                if Path(fname).suffix.lower() in AUDIO_EXTENSIONS:
                    found.append(str(Path(dirpath) / fname))

        for path in found:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            cached = cache.get(path)
            if cached and cached.get("mtime") == mtime and not _is_stale(cached):
                continue
            cache[path] = _analyze_preserving_cues(path, mtime, cached)

        # drop entries that lived under this root but vanished from disk
        found_set = set(found)
        for path in list(cache.keys()):
            if path.startswith(root) and path not in found_set:
                del cache[path]

        _save_cache(cache_path, cache)
        entries = [_entry_for(p, cache) for p in cache.keys()]
        entries.sort(key=lambda e: e["filename"].lower())
        return entries


def get_library(cache_path: Path) -> list:
    with _lock:
        cache = _load_cache(cache_path)
        entries = [_entry_for(p, cache) for p in cache.keys()]
        entries.sort(key=lambda e: e["filename"].lower())
        return entries


def invalidate(path: str, cache_path: Path) -> None:
    with _lock:
        cache = _load_cache(cache_path)
        if path in cache:
            del cache[path]
            _save_cache(cache_path, cache)


def force_reanalyze(path: str, cache_path: Path) -> dict:
    """Like invalidate() + get_or_analyze(), but keeps hot cues -- a forced
    re-analysis (user fixed a bad BPM/key guess) shouldn't discard cue points
    the user placed by hand."""
    with _lock:
        cache = _load_cache(cache_path)
        cached = cache.get(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        cache[path] = _analyze_preserving_cues(path, mtime, cached)
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)


def get_or_analyze(path: str, cache_path: Path) -> dict:
    with _lock:
        cache = _load_cache(cache_path)
        cached = cache.get(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if cached and cached.get("mtime") == mtime and not _is_stale(cached):
            return _entry_for(path, cache)
        cache[path] = _analyze_preserving_cues(path, mtime, cached)
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)


# -------------------------------------------------------------- hot cues --

def add_cue(path: str, time: float, cache_path: Path) -> dict:
    """Rekordbox-style memory cue on a library track, independent of any
    clip placed on a timeline. Stored in the same on-disk cache as analysis
    results, keyed by an incrementing id so the frontend can address one
    cue for removal."""
    with _lock:
        cache = _load_cache(cache_path)
        entry = cache.get(path)
        if entry is None:
            raise KeyError(path)
        cues = entry.setdefault("cues", [])
        next_id = (max((c["id"] for c in cues), default=0)) + 1
        cues.append({"id": next_id, "time": round(max(0.0, time), 3)})
        cues.sort(key=lambda c: c["time"])
        del cues[MAX_CUES_PER_TRACK:]
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)


def remove_cue(path: str, cue_id: int, cache_path: Path) -> dict:
    with _lock:
        cache = _load_cache(cache_path)
        entry = cache.get(path)
        if entry is None:
            raise KeyError(path)
        entry["cues"] = [c for c in entry.get("cues", []) if c["id"] != cue_id]
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)
