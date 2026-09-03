"""Recursive folder scan + on-disk JSON cache of per-file analysis."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from analysis import analyze_file
from harmonic import match_score

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".ogg", ".m4a"}
_lock = threading.Lock()


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
            if cached and cached.get("mtime") == mtime and "error" not in cached:
                continue
            result = analyze_file(path)
            result["mtime"] = mtime
            cache[path] = result

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


def suggest_matches(
    cache_path: Path,
    ref_bpm: float | None,
    ref_camelot: str | None,
    exclude_path: str | None = None,
    limit: int = 20,
) -> list:
    """Local ("AI Match") recommendation: rank library entries by BPM/key
    compatibility with a reference track, without any network call."""
    entries = get_library(cache_path)
    scored = []
    for e in entries:
        if e.get("error") or e["path"] == exclude_path:
            continue
        score = match_score(ref_bpm, ref_camelot, e.get("bpm"), e.get("camelot"))
        scored.append({**e, "score": score})
    scored.sort(key=lambda e: e["score"], reverse=True)
    return scored[: max(0, limit)]


def get_or_analyze(path: str, cache_path: Path) -> dict:
    with _lock:
        cache = _load_cache(cache_path)
        cached = cache.get(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if cached and cached.get("mtime") == mtime and "error" not in cached:
            return _entry_for(path, cache)
        result = analyze_file(path)
        result["mtime"] = mtime
        cache[path] = result
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)
