"""Recursive folder scan + on-disk JSON cache of per-file analysis."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from analysis import analyze_file

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
            # cues are user-entered metadata, not an analysis artifact -- keep
            # them across re-analysis (file edited/re-exported) or a stale cache.
            if cached and cached.get("cues"):
                result["cues"] = cached["cues"]
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
        if cached and cached.get("cues"):
            result["cues"] = cached["cues"]
        cache[path] = result
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)


MAX_CUES = 8


def set_cue(path: str, cache_path: Path, index: int, time: float, label: str = "") -> dict:
    """Save (or overwrite) a rekordbox-style hot cue slot (0-7) on a library track."""
    if not 0 <= index < MAX_CUES:
        raise ValueError(f"cue index must be 0..{MAX_CUES - 1}")
    with _lock:
        cache = _load_cache(cache_path)
        if path not in cache:
            raise KeyError(path)
        cues = [c for c in cache[path].get("cues", []) if c.get("index") != index]
        cues.append({"index": index, "time": max(0.0, float(time)), "label": label or ""})
        cues.sort(key=lambda c: c["index"])
        cache[path]["cues"] = cues
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)


def clear_cue(path: str, cache_path: Path, index: int) -> dict:
    with _lock:
        cache = _load_cache(cache_path)
        if path not in cache:
            raise KeyError(path)
        cache[path]["cues"] = [c for c in cache[path].get("cues", []) if c.get("index") != index]
        _save_cache(cache_path, cache)
        return _entry_for(path, cache)
