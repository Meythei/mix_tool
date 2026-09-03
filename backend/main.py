"""DJ Mix Studio backend: a local FastAPI app serving the frontend + the
library/analysis/render API. State (the project currently being edited) lives
in a single in-process variable -- this is a single-user local tool, not a
multi-tenant service."""
from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import library
import storage
from models import Project, Deck, RenderRequest
from engine.render import render_to_wav

# desktop_app.py (the frozen .exe entry point) sets this to the bundle's
# root dir, which PyInstaller extracts read-only bytes into -- so it is NOT
# where user data (cache/projects/exports) should be written. Plain `python
# run.py` leaves it unset and everything resolves under backend/data/, same
# as always.
_env_root = os.environ.get("DJ_MIX_STUDIO_APP_ROOT")
_is_packaged = bool(_env_root) or getattr(sys, "frozen", False)
APP_ROOT = Path(_env_root) if _env_root else Path(__file__).resolve().parent.parent

BASE_DIR = APP_ROOT / "backend"
FRONTEND_DIR = APP_ROOT / "frontend"
SAMPLE_LIBRARY_DIR = BASE_DIR / "data" / "sample_library"  # bundled demo content, read-only when packaged

if _is_packaged:
    DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "DJMixStudio"
else:
    DATA_DIR = BASE_DIR / "data"
PROJECTS_DIR = DATA_DIR / "projects"
EXPORTS_DIR = DATA_DIR / "exports"
CACHE_PATH = DATA_DIR / "library_cache.json"

# StaticFiles(...) below checks the directory exists at construction time
# (module import), which runs before `lifespan` -- so these must be created
# here, not there. On a packaged app's first run, %APPDATA%\DJMixStudio\ does
# not exist yet, so this can't wait.
SAMPLE_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def default_project() -> Project:
    return Project(
        name="Untitled Mix",
        master_bpm=128.0,
        decks=[
            Deck(id=str(uuid.uuid4()), name="Deck A", type="track", bus="A", color="#B8C4FF"),
            Deck(id=str(uuid.uuid4()), name="Deck B", type="track", bus="B", color="#FFB2BE"),
            Deck(id=str(uuid.uuid4()), name="Shots", type="shot", sync=False, bus="M", color="#F0C05A"),
        ],
    )


state = {"project": default_project()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    def _scan_demo_library():
        # librosa's first call JIT-warms numba and can take ~30s; do this off
        # the startup path so the server is immediately reachable.
        try:
            library.scan_folder(str(SAMPLE_LIBRARY_DIR), CACHE_PATH)
        except Exception:
            pass

    threading.Thread(target=_scan_demo_library, daemon=True).start()
    yield


app = FastAPI(title="DJ Mix Studio", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/exports", StaticFiles(directory=EXPORTS_DIR), name="exports")


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"ok": True}


# ---------------------------------------------------------------- library --

class ScanRequest(BaseModel):
    folder: str


@app.get("/api/library")
async def api_library_get():
    return library.get_library(CACHE_PATH)


@app.post("/api/library/scan")
async def api_library_scan(req: ScanRequest):
    folder = Path(req.folder).expanduser()
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder not found: {req.folder}")
    entries = await run_in_threadpool(library.scan_folder, str(folder), CACHE_PATH)
    return entries


@app.post("/api/library/reanalyze")
async def api_library_reanalyze(req: dict):
    path = req.get("path")
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    library.invalidate(path, CACHE_PATH)
    entry = await run_in_threadpool(library.get_or_analyze, path, CACHE_PATH)
    return entry


# ---------------------------------------------------------------- project --

@app.get("/api/project")
async def api_project_get():
    return state["project"]


@app.put("/api/project")
async def api_project_put(project: Project):
    state["project"] = project
    return state["project"]


@app.post("/api/project/new")
async def api_project_new():
    state["project"] = default_project()
    return state["project"]


@app.get("/api/projects")
async def api_projects_list():
    return storage.list_projects(PROJECTS_DIR)


class SaveRequest(BaseModel):
    project: Project | None = None


@app.post("/api/projects/save")
async def api_projects_save(req: SaveRequest | None = None):
    project = (req.project if req and req.project else None) or state["project"]
    state["project"] = project
    filename = storage.save_project(project, PROJECTS_DIR)
    return {"filename": filename}


@app.post("/api/projects/{filename}/load")
async def api_projects_load(filename: str):
    try:
        project = storage.load_project(filename, PROJECTS_DIR)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    state["project"] = project
    return project


@app.delete("/api/projects/{filename}")
async def api_projects_delete(filename: str):
    storage.delete_project(filename, PROJECTS_DIR)
    return {"ok": True}


# ----------------------------------------------------------- render/export --

@app.post("/api/preview")
async def api_preview(req: RenderRequest):
    project = req.project or state["project"]
    if req.project:
        state["project"] = project
    out_path = EXPORTS_DIR / "preview.wav"
    max_dur = req.max_duration if req.max_duration is not None else 180.0
    try:
        result = await run_in_threadpool(
            render_to_wav, project, str(out_path),
            t_start=req.start, t_end=req.end, max_duration=max_dur,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Render failed: {exc}")
    return {
        "url": f"/exports/preview.wav?t={int(time.time() * 1000)}",
        "duration": result["duration"],
        "sample_rate": result["sample_rate"],
        "warnings": result["warnings"],
    }


@app.post("/api/export")
async def api_export(req: RenderRequest):
    project = req.project or state["project"]
    if req.project:
        state["project"] = project
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{storage.safe_filename(project.name)}_{ts}.wav"
    out_path = EXPORTS_DIR / filename
    max_dur = req.max_duration if req.max_duration is not None else 10800.0
    try:
        result = await run_in_threadpool(
            render_to_wav, project, str(out_path),
            t_start=req.start, t_end=req.end, max_duration=max_dur,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Render failed: {exc}")
    return {
        "url": f"/exports/{filename}",
        "filename": filename,
        "duration": result["duration"],
        "sample_rate": result["sample_rate"],
        "warnings": result["warnings"],
    }
