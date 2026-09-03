"""Project persistence: one JSON file per saved mix under data/projects/."""
from __future__ import annotations

import re
import json
from pathlib import Path

from models import Project


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _\-\.]", "", name).strip() or "Untitled Mix"
    return cleaned[:120]


def list_projects(projects_dir: Path) -> list:
    projects_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(projects_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "name": data.get("name", f.stem),
                "file": f.name,
                "master_bpm": data.get("master_bpm"),
                "deck_count": len(data.get("decks", [])),
                "modified": f.stat().st_mtime,
            })
        except Exception:
            continue
    out.sort(key=lambda p: p["modified"], reverse=True)
    return out


def save_project(project: Project, projects_dir: Path) -> str:
    projects_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(project.name) + ".json"
    path = projects_dir / filename
    path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    return filename


def load_project(filename: str, projects_dir: Path) -> Project:
    safe = Path(filename).name  # strip any path components
    path = projects_dir / safe
    data = json.loads(path.read_text(encoding="utf-8"))
    return Project.model_validate(data)


def delete_project(filename: str, projects_dir: Path) -> None:
    safe = Path(filename).name
    path = projects_dir / safe
    if path.exists():
        path.unlink()
