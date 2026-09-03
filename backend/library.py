"""Recursive folder scan + on-disk JSON cache of per-file analysis, plus a
small sidecar store of user-authored track metadata (rekordbox-style hot
cues) that survives re-analysis and cache invalidation."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from analysis import analyze_file

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".aiff", ".aif", ".ogg", ".m4a"}
# Bump when analyze_file()'s output shape changes in a way that should force
# one re-analysis of already-cached files (new fields like camelot/energy).
_ANALYSIS_VERSION = 2
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


def _user_meta_path(cache_path: Path) -> Path:
    return cache_path.parent / "library_user.json"


def _load_user_meta(cache_path: Path) -> dict:
    p = _user_meta_path(cache_path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_user_meta(cache_path: Path, meta: dict) -> None:
    p = _user_meta_path(cache_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_fresh(cached: dict | None, mtime) -> bool:
    return bool(
        cached
        and cached.get("mtime") == mtime
        and "error" not in cached
        and cached.get("_v") == _ANALYSIS_VERSION
    )


def _entry_for(path: str, cache: dict, user_meta: dict) -> dict:
    rec = dict(cache[path])
    rec["path"] = path
    rec["filename"] = os.path.basename(path)
    rec["cue_points"] = list(user_meta.get(path, {}).get("cue_points", []))
    return rec


def scan_folder(root: str, cache_path: Path) -> list:
    root = str(Path(root).expanduser())
    with _lock:
        cache = _load_cache(cache_path)
        user_meta = _load_user_meta(cache_path)

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
            if _is_fresh(cache.get(path), mtime):
                continue
            result = analyze_file(path)
            result["mtime"] = mtime
            result["_v"] = _ANALYSIS_VERSION
            cache[path] = result

        # drop entries that lived under this root but vanished from disk
        found_set = set(found)
        meta_changed = False
        for path in list(cache.keys()):
            if path.startswith(root) and path not in found_set:
                del cache[path]
                if path in user_meta:
                    del user_meta[path]
                    meta_changed = True

        _save_cache(cache_path, cache)
        if meta_changed:
            _save_user_meta(cache_path, user_meta)
        entries = [_entry_for(p, cache, user_meta) for p in cache.keys()]
        entries.sort(key=lambda e: e["filename"].lower())
        return entries


def get_library(cache_path: Path) -> list:
    with _lock:
        cache = _load_cache(cache_path)
        user_meta = _load_user_meta(cache_path)
        entries = [_entry_for(p, cache, user_meta) for p in cache.keys()]
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
        user_meta = _load_user_meta(cache_path)
        cached = cache.get(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if _is_fresh(cached, mtime):
            return _entry_for(path, cache, user_meta)
        result = analyze_file(path)
        result["mtime"] = mtime
        result["_v"] = _ANALYSIS_VERSION
        cache[path] = result
        _save_cache(cache_path, cache)
        return _entry_for(path, cache, user_meta)


def set_cues(path: str, cues: list, cache_path: Path) -> dict:
    """Replace the full hot-cue list for one library track (rekordbox-style
    memory cues live on the track, not on any particular timeline clip)."""
    with _lock:
        cache = _load_cache(cache_path)
        if path not in cache:
            raise KeyError(path)
        user_meta = _load_user_meta(cache_path)
        cleaned = []
        for c in cues:
            cleaned.append({
                "id": str(c.get("id") or ""),
                "time": max(0.0, float(c.get("time", 0.0))),
                "label": str(c.get("label", ""))[:60],
                "color": str(c.get("color", "#B8C4FF")),
            })
        cleaned.sort(key=lambda c: c["time"])
        user_meta[path] = {"cue_points": cleaned}
        _save_user_meta(cache_path, user_meta)
        return _entry_for(path, cache, user_meta)
