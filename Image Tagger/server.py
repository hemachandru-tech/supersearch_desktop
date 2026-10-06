"""
server.py
=========
The local web backend (FastAPI) for Super Search Desktop.

It runs ONLY on your own computer (http://127.0.0.1:8765) and powers:
    - Start Tagging   (POST /api/start)      -> runs the local tagging pipeline
    - Live progress   (GET  /api/progress)
    - Search          (GET  /api/search)     -> queries the local SQLite index
    - Filters/stats   (GET  /api/filters, /api/stats)
    - Thumbnails      (GET  /api/thumb)
    - Open full image (GET  /api/file)
    - Verify metadata (GET  /api/metadata)   -> shows what's embedded in the file
    - Edit tags       (POST /api/edit/{id})  -> updates DB + re-embeds metadata

Nothing here talks to the internet except the Gemini tagging calls.
"""

import ssl  # noqa: F401  - load OpenSSL first (see note in local_pipeline.py)
import os
import io
import sys
import subprocess
import threading

from fastapi import FastAPI, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

import local_db
import metadata_writer
from local_pipeline import LocalTaggingPipeline
from modules import frozen_config as FROZEN
from modules import paths

HERE = os.path.dirname(os.path.abspath(__file__))
# Load .env read-only from the app resources (bundled key in a packaged .app;
# project-root .env in dev). The app never writes .env, so no App Support copy is needed.
load_dotenv(paths.env_path())

app = FastAPI(title="Super Search Desktop")


@app.middleware("http")
async def _revalidate_ui_assets(request, call_next):
    """Force the web UI (HTML/JS/JSX/CSS) to revalidate on every load.

    Static assets were previously served with only ETag/Last-Modified and no
    Cache-Control. In a long-lived chromeless app window, Chrome applies
    *heuristic* caching and can serve a stale .jsx/.css without revalidating —
    which made edited UI (e.g. the Detail-panel dropdowns) keep rendering the
    old version. 'no-cache' still allows caching but requires revalidation, so
    unchanged files return a fast 304 and changed files are re-fetched.
    API responses are dynamic and left untouched.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


import time
LAST_HEARTBEAT = time.time()
START_TIME = time.time()

def monitor_heartbeat():
    global LAST_HEARTBEAT
    while True:
        time.sleep(5)
        # If tagging is currently running, keep server alive by updating heartbeat
        try:
            if STATE.pipeline and STATE.pipeline.get_progress().get("running"):
                LAST_HEARTBEAT = time.time()
        except Exception:
            pass
            
        # Give the server at least 45 seconds of grace period on startup
        if time.time() - START_TIME > 45.0:
            inactive_duration = time.time() - LAST_HEARTBEAT
            if inactive_duration > 90.0:
                print(f"[SERVER] No heartbeat received for {int(inactive_duration)} seconds. Shutting down server process...")
                # os._exit(0) # Disabled to prevent unexpected shutdown

threading.Thread(target=monitor_heartbeat, daemon=True).start()


# -------------------------------------------------------------------------
# shared application state
# -------------------------------------------------------------------------
class AppState:
    def __init__(self):
        self.db = local_db.LocalDB(paths.data_path("tags.db"))
        self.pipeline = None          # built lazily (loads ML models on first tag run)
        self.loading_models = False
        self._state_file = paths.data_path("app_state.json")
        self.last_folder = self._load_last_folder()   # remembered across restarts

    def _load_last_folder(self):
        try:
            import json
            with open(self._state_file, encoding="utf-8") as f:
                return (json.load(f) or {}).get("last_folder", "") or ""
        except Exception:
            return ""

    def set_last_folder(self, folder):
        """Remember the most recently tagged folder so it becomes the default next time."""
        self.last_folder = folder or ""
        try:
            import json
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump({"last_folder": self.last_folder}, f)
        except Exception:
            pass

    def api_keys(self):
        try:
            import json
            with open(self._state_file, encoding="utf-8") as f:
                state_keys = (json.load(f) or {}).get("api_keys")
                if state_keys:
                    return [k.strip() for k in state_keys.split(",") if k.strip()]
        except Exception:
            pass
        raw = os.getenv("GEMINI_API_KEYS", "")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def set_api_keys(self, keys_str):
        try:
            import json
            state = {}
            if os.path.exists(self._state_file):
                with open(self._state_file, encoding="utf-8") as f:
                    state = json.load(f) or {}
            state["api_keys"] = keys_str
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception as e:
            print("[SERVER] Failed to save api_keys:", e)

    def ensure_pipeline(self, ignore_api_key=False):
        """Build the pipeline (loads models) once, on first use."""
        if self.pipeline is not None:
            return self.pipeline
        keys = self.api_keys()
        if not keys and not ignore_api_key:
            raise RuntimeError("No Gemini API key found. Add your key first.")
        self.loading_models = True
        try:
            from modules import frozen_config as FROZEN
            self.pipeline = LocalTaggingPipeline(
                api_keys=keys,
                db=self.db,
                tournament_name=os.getenv("TOURNAMENT_NAME", ""),  # deployment label (kept in env)
                max_workers=FROZEN.MAX_WORKERS,                    # FROZEN
                jersey_model_path=os.getenv("JERSEY_MODEL_PATH", os.path.join(HERE, "models", "jersey.pth")),
                write_metadata_enabled=FROZEN.WRITE_METADATA,      # FROZEN (kept ON)
            )
        finally:
            self.loading_models = False
        return self.pipeline


STATE = AppState()


# -------------------------------------------------------------------------
# pages + static files
# -------------------------------------------------------------------------
WEBUI = os.path.join(HERE, "webui")
app.mount("/static", StaticFiles(directory=WEBUI), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(WEBUI, "index.html"), encoding="utf-8") as f:
        return f.read()


# -------------------------------------------------------------------------
# status
# -------------------------------------------------------------------------
@app.get("/api/status")
def status():
    model = "gemini-2.5-flash"
    try:
        import json
        with open(STATE._state_file, encoding="utf-8") as f:
            state = json.load(f) or {}
            if "gemini_model" in state:
                model = state["gemini_model"]
    except Exception:
        pass
    return {
        "api_keys": len(STATE.api_keys()),
        "gemini_model": model,
        "metadata_backend": metadata_writer.backend_name(),
        "windows_visible_note": "Tags show in Windows Properties for JPEG/TIFF. "
                                "PNG/HEIC/RAW are searchable but Windows won't display their tags.",
        "loading_models": STATE.loading_models,
        "tournament": os.getenv("TOURNAMENT_NAME", ""),
        "stats": STATE.db.stats(),
        "last_folder": STATE.last_folder,
    }


@app.post("/api/settings")
def save_settings(payload: dict = Body(...)):
    keys = payload.get("api_keys", "")
    if keys:
        STATE.set_api_keys(keys)
    model = payload.get("gemini_model")
    if model:
        # Save model to state
        try:
            import json
            state = {}
            if os.path.exists(STATE._state_file):
                with open(STATE._state_file, encoding="utf-8") as f:
                    state = json.load(f) or {}
            state["gemini_model"] = model
            with open(STATE._state_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception:
            pass
    
    # Force the pipeline to rebuild next time it's used so it picks up the new key/model
    STATE.pipeline = None
    
    return {"ok": True}

# -------------------------------------------------------------------------
# start tagging (runs in the background)
# -------------------------------------------------------------------------
@app.post("/api/start")
def start(payload: dict = Body(...)):
    folder = (payload.get("folder") or "").strip()
    recursive = bool(payload.get("recursive", True))
    force = bool(payload.get("force", False))
    disable_ai_tags = bool(payload.get("disable_ai_tags", False))

    if not folder or not os.path.isdir(folder):
        return JSONResponse({"ok": False, "error": f"Folder not found: {folder}"}, status_code=400)

    if STATE.pipeline and STATE.pipeline.get_progress().get("running"):
        return JSONResponse({"ok": False, "error": "Tagging already running."}, status_code=409)

    if not STATE.api_keys() and not disable_ai_tags:
        return JSONResponse(
            {"ok": False, "error": "No Gemini API Key provided. Please add it first."},
            status_code=400,
        )

    STATE.set_last_folder(folder)

    tournament = (payload.get("tournament") or "").strip()
    team = (payload.get("team") or "").strip()

    def job():
        try:
            pipe = STATE.ensure_pipeline(ignore_api_key=disable_ai_tags)
            pipe.tag_folder(folder, recursive=recursive, force=force, disable_ai_tags=disable_ai_tags, tournament_context=tournament, team_context=team)
        except Exception as e:
            print(f"[SERVER] Tagging job failed: {e}")

    threading.Thread(target=job, daemon=True).start()
    return {"ok": True, "folder": folder}


@app.post("/api/pick-folder")
def pick_folder():
    """
    Open a native 'choose folder' dialog. We run it in a SEPARATE process so it
    can never freeze the desktop window or the web server (that was the old bug).
    """
    code = (
        "import tkinter as tk;"
        "from tkinter import filedialog;"
        "r=tk.Tk();r.withdraw();r.attributes('-topmost',True);"
        "p=filedialog.askdirectory(title='Choose a folder of images');"
        "print(p or '')"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=300,
        )
        folder = (out.stdout or "").strip().splitlines()[-1] if out.stdout.strip() else ""
        return {"folder": folder}
    except Exception as e:
        return {"folder": "", "error": str(e)}


@app.post("/api/stop")
def stop_tagging():
    if STATE.pipeline:
        STATE.pipeline.stop()
        return {"ok": True, "message": "Tagging stop requested."}
    return {"ok": True, "message": "Pipeline not running."}


@app.get("/api/heartbeat")
def heartbeat():
    global LAST_HEARTBEAT
    LAST_HEARTBEAT = time.time()
    return {"ok": True}


@app.get("/api/progress")
def progress():
    if STATE.loading_models:
        return {"running": True, "loading_models": True, "log": ["Loading AI models (first run can take a minute)..."],
                "total": 0, "done": 0, "ok": 0, "errors": 0, "skipped": 0, "current": "", "finished": False}
    if STATE.pipeline is None:
        return {"running": False, "loading_models": False, "log": [], "total": 0, "done": 0,
                "ok": 0, "errors": 0, "skipped": 0, "current": "", "finished": False}
    p = STATE.pipeline.get_progress()
    p["loading_models"] = False
    return p


# -------------------------------------------------------------------------
# search + filters + stats
# -------------------------------------------------------------------------
@app.get("/api/search")
def search(
    q: str = Query("", description="free text"),
    player: str = "", event: str = "", mood: str = "", action: str = "",
    jersey_color: str = "", crowd_present: str = "",
    limit: int = 200, offset: int = 0,
):
    filters = {
        "player_names": player, "event_type": event, "mood": mood, "action": action,
        "jersey_color": jersey_color, "crowd_present": crowd_present,
    }
    rows = STATE.db.search(query=q, filters=filters, limit=limit, offset=offset)
    return {"count": len(rows), "results": rows}


@app.get("/api/filters")
def filters():
    """LIBRARY filter options.

    Top-level lists are DISTINCT values that actually exist in currently-tagged content
    (so the Library dropdowns only show what's really there, and refresh as content
    changes). The `master` block carries the COMPLETE controlled vocabulary for the
    Edit-Tags scene dropdowns. NOTE: this endpoint loads NO ML models — it must stay
    fast so the UI is usable immediately at startup. The master PLAYER roster is served
    separately and lazily by /api/roster.
    """
    from modules import taxonomy as TAX
    return {
        # Library filters — only values present in tagged content (auto-refreshing).
        "players": STATE.db.distinct_values("player_names"),
        "events": STATE.db.distinct_values("event_type"),
        "moods": STATE.db.distinct_values("mood"),
        "actions": STATE.db.distinct_values("action"),
        "jersey_types": STATE.db.distinct_values("apparel"),   # images.apparel (jersey TYPE)
        "locations": STATE.db.distinct_values("location"),
        # Edit-Tags master taxonomy — complete lists (no model needed).
        "master": {
            "events": TAX.EVENT_TYPES,
            "moods": TAX.MOODS,
            "actions": TAX.ACTIONS,
            "locations": TAX.LOCATIONS,
            "jersey_types": TAX.APPAREL_TYPES,
        },
    }


@app.get("/api/roster")
def roster():
    """Master player roster for the Edit-Tags player picker (the trained model's known
    players). Lazy-loads ONLY the light sklearn classifier (NOT InsightFace/Torch/ONNX),
    so it never blocks startup and never spins up the heavy face pipeline."""
    players = []
    try:
        from modules.config import get_label_encoder
        le = get_label_encoder()
        if le is not None and hasattr(le, "classes_"):
            players = list(le.classes_)
    except Exception as e:
        print(f"[SERVER] roster load failed: {e}")
    if not players:
        players = STATE.db.distinct_values("player_names")  # fallback to what's tagged
    return {"players": players}


@app.get("/api/stats")
def stats():
    return STATE.db.stats()


# -------------------------------------------------------------------------
# images: thumbnails + full file + embedded-metadata read-back
# -------------------------------------------------------------------------
_THUMB_CACHE = {}


def _get_raw_preview(path):
    if not metadata_writer.EXIFTOOL_PATH:
        return None
    for tag in ["-PreviewImage", "-JpgFromRaw", "-ThumbnailImage"]:
        try:
            proc = subprocess.run(
                [metadata_writer.EXIFTOOL_PATH, "-b", tag, path],
                capture_output=True, timeout=5
            )
            if proc.returncode == 0 and proc.stdout and proc.stdout.startswith(b'\xff\xd8'):
                return proc.stdout
        except Exception as e:
            print(f"[SERVER] Failed to extract {tag} from {path}: {e}")
    return None


@app.get("/api/thumb")
def thumb(id: int = Query(...), size: int = 320):
    row = STATE.db.get_image(id)
    if not row:
        return Response(status_code=404)
    path = row["file_path"]
    key = (path, size)
    if key in _THUMB_CACHE:
        return Response(content=_THUMB_CACHE[key], media_type="image/jpeg")
    
    ext = os.path.splitext(path)[1].lower()
    im = None
    
    # 1. If it's a video format, extract the first frame
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        try:
            import cv2
            cap = cv2.VideoCapture(path)
            success, frame = cap.read()
            if success:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                im = Image.fromarray(frame_rgb)
            cap.release()
        except Exception as e:
            print(f"[SERVER] Failed to extract video frame for {path}: {e}")
            
    # 2. If it's a RAW image format, extract the preview using ExifTool
    elif ext in {".arw", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2"}:
        raw_bytes = _get_raw_preview(path)
        if raw_bytes:
            try:
                im = Image.open(io.BytesIO(raw_bytes))
                # Rotate based on original RAW orientation
                orientation = metadata_writer.get_original_orientation(path)
                im = metadata_writer.rotate_image_by_orientation(im, orientation)
            except Exception as e:
                print(f"[SERVER] Failed to load RAW preview bytes: {e}")
                
    # 3. Fallback: try opening with PIL directly (handles JPEG/PNG/WebP/HEIC)
    if im is None:
        try:
            im = Image.open(path)
        except Exception as e:
            print(f"[SERVER] Failed to open image directly: {e}")
            
    if im is not None:
        try:
            # Auto-rotate based on EXIF orientation
            im = ImageOps.exif_transpose(im)
            
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
            data = buf.getvalue()
            if len(_THUMB_CACHE) < 2000:
                _THUMB_CACHE[key] = data
            return Response(content=data, media_type="image/jpeg")
        except Exception as e:
            print(f"[SERVER] Error processing thumbnail for {path}: {e}")
            
    # Fallback to transparent placeholder
    return Response(
        content=bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb0043000302020202020302"
            "0202030303030406040404040408060605060a080a0a0a0a0a0a0a0a0a0a0a0a0a"
        ),
        media_type="image/jpeg",
    )


@app.get("/api/file")
def file(id: int = Query(...)):
    row = STATE.db.get_image(id)
    if not row or not os.path.exists(row["file_path"]):
        return Response(status_code=404)
        
    path = row["file_path"]
    ext = os.path.splitext(path)[1].lower()
    if ext in {".arw", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2"}:
        raw_bytes = _get_raw_preview(path)
        if raw_bytes:
            try:
                im = Image.open(io.BytesIO(raw_bytes))
                orientation = metadata_writer.get_original_orientation(path)
                im = metadata_writer.rotate_image_by_orientation(im, orientation)
                
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=90)
                return Response(content=buf.getvalue(), media_type="image/jpeg")
            except Exception as e:
                print(f"[SERVER] Failed to generate preview for raw file {path}: {e}")

    return FileResponse(path)


@app.get("/api/metadata")
def metadata(id: int = Query(...)):
    """Read back what is actually embedded in the image file (for verification)."""
    row = STATE.db.get_image(id)
    if not row:
        return Response(status_code=404)
    return {"file": row["file_path"], "embedded": metadata_writer.read_metadata(row["file_path"])}


# -------------------------------------------------------------------------
# edit tags (Quality Control): update DB + re-embed into the file
# -------------------------------------------------------------------------
EDITABLE = ["player_names", "event_type", "mood", "action", "location",
            "jersey_color", "apparel", "crowd_present", "caption", "tournament"]


@app.post("/api/edit/{image_id}")
def edit(image_id: int, payload: dict = Body(...)):
    fields = {k: v for k, v in payload.items() if k in EDITABLE}
    if not fields:
        return JSONResponse({"ok": False, "error": "No editable fields provided."}, status_code=400)

    # Sync faces_json with final player_names edit
    if "player_names" in fields:
        new_names = [p.strip() for p in fields["player_names"].split(",") if p.strip() and p.strip().lower() != "unknown"]
        cur = STATE.db.get_image(image_id)
        if cur:
            faces_list = []
            if cur.get("faces_json"):
                try:
                    import json
                    faces_list = json.loads(cur["faces_json"])
                except Exception:
                    pass
            
            # Update face status matching new player names
            for face in faces_list:
                if face["name"] in new_names:
                    face["status"] = "confirmed"
                elif face["status"] == "confirmed":
                    face["name"] = "Unknown"
                    face["status"] = "review"
            
            # Add missing names
            face_names = {f["name"] for f in faces_list if f["name"] != "Unknown"}
            for p in new_names:
                if p not in face_names:
                    faces_list.append({
                        "name": p,
                        "conf": 1.0,
                        "status": "confirmed",
                        "bbox": [0, 0, 0, 0]
                    })
            import json
            fields["faces_json"] = json.dumps(faces_list)

    updated = STATE.db.update_tags(image_id, fields)
    if not updated:
        return JSONResponse({"ok": False, "error": "Image not found."}, status_code=404)

    # Re-embed the new tags into the image file.
    note = ""
    if FROZEN.WRITE_METADATA:
        res = metadata_writer.write_metadata(updated["file_path"], updated)
        STATE.db.update_tags(image_id, {"metadata_written": 1 if res["ok"] else 0})
        note = res["note"]

    # Read-only inference (Phase 1 freeze): editing a name updates THIS image's tags
    # only. It never teaches/updates the recognition model.
    return {"ok": True, "image": updated, "metadata_note": note, "learn_note": ""}


# -------------------------------------------------------------------------
# New Endpoints added for live UI integration
# -------------------------------------------------------------------------
@app.get("/api/verify")
def verify(id: int = Query(...)):
    row = STATE.db.get_image(id)
    if not row or not os.path.exists(row["file_path"]):
        return JSONResponse({"ok": False, "error": "Image not found or file missing."}, status_code=404)
    embedded = metadata_writer.read_metadata(row["file_path"])
    return {"ok": True, "embedded": embedded}


@app.post("/api/face/resolve")
def resolve_face(payload: dict = Body(...)):
    image_id = payload.get("image_id")
    face_index = payload.get("face_index")
    action = payload.get("action")
    name = (payload.get("name") or "").strip()

    row = STATE.db.get_image(image_id)
    if not row:
        return JSONResponse({"ok": False, "error": "Image not found."}, status_code=404)

    file_path = row["file_path"]
    
    faces_list = []
    if row.get("faces_json"):
        try:
            import json
            faces_list = json.loads(row["faces_json"])
        except Exception:
            pass

    if face_index is not None and 0 <= face_index < len(faces_list):
        face = faces_list[face_index]
        if action == "reject":
            face["name"] = "Unknown"
            face["status"] = "rejected"
        else:
            face["name"] = name
            face["status"] = "confirmed"
            face["conf"] = 1.0
    
    confirmed_players = []
    for f in faces_list:
        if f["status"] == "confirmed" and f["name"] != "Unknown":
            confirmed_players.append(f["name"])
    
    new_players_str = ", ".join(dict.fromkeys(confirmed_players)) if confirmed_players else "Unknown"
    
    import json
    updated_fields = {
        "player_names": new_players_str,
        "faces_json": json.dumps(faces_list)
    }
    
    updated = STATE.db.update_tags(image_id, updated_fields)

    # Read-only inference (Phase 1 freeze): resolving a face updates THIS image's tags
    # only. It never teaches/updates the recognition model.
    learn_note = ""

    metadata_note = ""
    if updated and FROZEN.WRITE_METADATA:
        res = metadata_writer.write_metadata(file_path, updated)
        STATE.db.update_tags(image_id, {"metadata_written": 1 if res["ok"] else 0})
        metadata_note = res["note"]

    return {
        "ok": True,
        "image": updated,
        "learn_note": learn_note,
        "metadata_note": metadata_note
    }


# -------------------------------------------------------------------------
# Refresh Library: reconcile the search index (tags.db) with what's on disk.
# -------------------------------------------------------------------------
def _index_existing_file(path, md):
    """Add an already-tagged file to the search index from its OWN embedded metadata.
    No AI, no models, no cost — this is how Refresh re-discovers files that were tagged
    before (e.g. on another machine, or after the database was reset). Insert-only:
    callers must have already confirmed the file is not in the database."""
    import local_pipeline
    rec = {
        "file_path": path,
        "file_name": os.path.basename(path),
        "folder": os.path.dirname(path),
        "tournament": os.getenv("TOURNAMENT_NAME", ""),
        "status": "completed",
        "metadata_written": 1,
        "embedded_tags": str(md.get("Tags") or ""),
        "caption": str(md.get("Title") or md.get("Subject") or ""),
        "photographer": str(md.get("Authors") or ""),
    }
    try:
        rec["file_hash"] = local_pipeline.file_md5(path)
    except Exception:
        rec["file_hash"] = None
    try:
        from PIL import Image as _Image
        with _Image.open(path) as im:
            rec["width"], rec["height"] = im.size
    except Exception:
        pass
    STATE.db.upsert_image(rec)


@app.post("/api/refresh")
def refresh_library():
    """Synchronise the library with the source folders on disk:
      1. PRUNE  — remove index rows whose image file no longer exists (deleted photos
                  stop appearing in search).
      2. RE-INDEX — for new files found in already-known folders that ALREADY carry
                  embedded tags, add them to the index for free (no AI / no models).
      3. REPORT — count brand-new, UNTAGGED files; these need the Tag Photos workflow
                  (Refresh never runs Gemini and never touches any model).
    """
    import local_pipeline
    rows = STATE.db.all_image_paths()
    known = {os.path.abspath(p) for _, p in rows}

    # 1) prune deleted files
    missing_ids = [rid for rid, p in rows if not os.path.exists(p)]
    removed = STATE.db.delete_images(missing_ids)

    # 2) rescan known folders for newly added files
    added, new_untagged = 0, 0
    for folder in STATE.db.distinct_folders():
        if not folder or not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except Exception:
            continue
        for name in names:
            if os.path.splitext(name)[1].lower() not in local_pipeline.ALL_SUPPORTED:
                continue
            ap = os.path.abspath(os.path.join(folder, name))
            if not os.path.isfile(ap) or ap in known:
                continue
            try:
                complete, md = metadata_writer.tag_completeness(ap)
            except Exception:
                complete, md = False, {}
            if complete:
                _index_existing_file(ap, md)
                known.add(ap)
                added += 1
            else:
                new_untagged += 1

    return {
        "ok": True,
        "removed": removed,
        "added": added,
        "new_untagged": new_untagged,
        "total": STATE.db.stats().get("total", 0),
    }


# NOTE (Phase 1 freeze): the developer Settings page and its admin gate were removed for
# the client-facing prototype. The endpoints /api/settings (read/write .env) and
# /api/admin/login, plus the read_env/write_env helpers and the hard-coded admin
# password, are intentionally gone. All configuration is now backend-only: secrets and
# deployment values live in .env (see ENVIRONMENT.md); recognition/pipeline parameters
# are frozen in modules/frozen_config.py. The app never rewrites .env at runtime.


# Mount the root static files route last, so API paths take precedence but relative assets (ss/*) are served


# ==============================================================================
# PLAYER MANAGEMENT APIS
# ==============================================================================


@app.get("/api/face_crop")
def face_crop(file: str = Query(...), bbox: str = Query(...)):
    import json
    from PIL import Image
    import io
    
    # Security: Validate path is within allowed roots
    # For this prototype, we'll allow the user's home directory (which covers Desktop/Dataset)
    allowed_roots = [os.path.abspath(os.path.expanduser("~"))]
    abs_file = os.path.abspath(file)
    is_allowed = any(abs_file.startswith(root) for root in allowed_roots)
    
    if not is_allowed or not os.path.exists(abs_file):
        return Response(status_code=404)
        
    try:
        box = json.loads(bbox) # [x1, y1, x2, y2]
        
        from modules.image_processing import safe_load_image
        im = safe_load_image(abs_file)
        
        # Add 15% padding
        width = box[2] - box[0]
        height = box[3] - box[1]
        pad_x = width * 0.15
        pad_y = height * 0.15
        
        crop_box = (
            max(0, box[0] - pad_x),
            max(0, box[1] - pad_y),
            min(im.width, box[2] + pad_x),
            min(im.height, box[3] + pad_y)
        )
        
        cropped = im.crop(crop_box)
        buf = io.BytesIO()
        cropped.save(buf, "JPEG", quality=90)
        return Response(content=buf.getvalue(), media_type="image/jpeg")
    except Exception as e:
        print(f"[SERVER] Failed to generate face crop for {file}: {e}")
        return Response(status_code=500)

@app.get("/api/players")
def api_get_players():
    return JSONResponse(STATE.db.get_players())

@app.post("/api/players")
def api_add_player(payload: dict = Body(...)):
    name = payload.get("name", "").strip()
    team = payload.get("team", "").strip()
    aliases = payload.get("aliases", "").strip()
    if not name:
        return JSONResponse({"error": "Name required"}, status_code=400)
    try:
        pid = STATE.db.add_player(name, team, aliases)
        return JSONResponse({"id": pid, "status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.put("/api/players/{player_id}")
def api_update_player(player_id: int, payload: dict = Body(...)):
    name = payload.get("name", "").strip()
    team = payload.get("team", "").strip()
    status = payload.get("status", "Active").strip()
    aliases = payload.get("aliases", "").strip()
    STATE.db.update_player(player_id, name, team, status, aliases)
    return JSONResponse({"status": "ok"})

@app.get("/api/samples/{player_id}")
def api_get_samples(player_id: int):
    return JSONResponse(STATE.db.get_training_samples(player_id))

@app.delete("/api/samples/{sample_id}")
def api_delete_sample(sample_id: int):
    STATE.db.delete_training_sample(sample_id)
    return JSONResponse({"status": "ok"})

@app.get("/api/models")
def api_get_models():
    return JSONResponse(STATE.db.get_models())

@app.get("/api/models/active")
def api_get_active_model():
    db_models = STATE.db.get_models()
    active_db = next((m for m in db_models if m["status"] == "ACTIVE"), None)
    if active_db:
        return JSONResponse(active_db)
        
    # Legacy Model
    from modules.config import FACE_MODEL_PATH
    import os, joblib, datetime
    if os.path.exists(FACE_MODEL_PATH):
        try:
            data = joblib.load(FACE_MODEL_PATH)
            clf = data.get("model")
            label_encoder = data.get("label_encoder")
            players = len(label_encoder.classes_) if label_encoder else 0
            
            # Legacy uses support vectors as reference templates
            samples = sum(clf.n_support_) if hasattr(clf, "n_support_") else 0
            
            mtime = os.path.getmtime(FACE_MODEL_PATH)
            return JSONResponse({
                "id": "legacy",
                "version_name": "Existing / Legacy Model",
                "players_count": players,
                "samples_count": samples,
                "created_at": datetime.datetime.fromtimestamp(mtime).isoformat(),
                "status": "LEGACY"
            })
        except Exception as e:
            print(e)
            
    return JSONResponse(None)


@app.post("/api/models/activate/{model_id}")
def api_activate_model(model_id: int):
    # 1. Candidate Validation
    with STATE.db._lock, STATE.db._connect() as conn:
        row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
    
    if not row:
        return JSONResponse({"error": "Model not found in DB"}, status_code=404)
        
    status = row["status"]
    model_path = row["model_path"]
    
    if not os.path.exists(model_path):
        return JSONResponse({"error": "Model file missing on disk"}, status_code=400)
        
    try:
        import joblib
        import numpy as np
        data = joblib.load(model_path)
        
        # Verify keys
        required_keys = {"model", "label_encoder", "embeddings", "labels"}
        if not required_keys.issubset(data.keys()):
            return JSONResponse({"error": "Model joblib missing required keys"}, status_code=400)
            
        clf = data["model"]
        le = data["label_encoder"]
        embs = data["embeddings"]
        lbls = data["labels"]
        
        # Verify shapes
        if len(embs.shape) != 2 or embs.shape[1] != 512:
            return JSONResponse({"error": "Embeddings must be shape (N, 512)"}, status_code=400)
            
        if len(embs) != len(lbls):
            return JSONResponse({"error": "Embeddings and labels length mismatch"}, status_code=400)
            
        # Verify prediction capability
        if len(embs) > 0:
            pred = clf.predict([embs[0]])
            if len(pred) == 0:
                return JSONResponse({"error": "Classifier failed prediction test"}, status_code=400)
                
    except Exception as e:
        return JSONResponse({"error": f"Model validation failed: {str(e)}"}, status_code=400)
        
    # 2. Safe Activation (DB)
    if STATE.db.activate_model(model_id):
        # 3. Cache Reload
        from modules import config
        try:
            config.reload_classifier()
            return JSONResponse({"status": "ok"})
        except Exception as e:
            # If cache reload fails, we should ideally rollback, but DB is updated.
            # At minimum, report error.
            return JSONResponse({"error": f"Activated in DB but cache reload failed: {e}"}, status_code=500)
            
    return JSONResponse({"error": "Failed to update DB"}, status_code=500)



@app.post("/api/samples/extract")
def api_extract_samples(payload: dict = Body(...)):
    files = payload.get("files", [])
    if not files:
        return JSONResponse({"error": "No files provided"}, status_code=400)
        
    import cv2
    import numpy as np
    from modules.image_processing import safe_load_image, detect_orientation, detect_faces_with_rotation
    from modules.config import get_face_app
    
    app = get_face_app()
    results = []
    
    for f in files:
        try:
            pil_img = safe_load_image(f)
            if pil_img is None:
                results.append({"file": f, "status": "ERROR", "error": "Could not load image"})
                continue
                
            image_np = np.array(pil_img)
            image_rgb = image_np.copy()
            orientation = detect_orientation(image_rgb.shape)
            faces, rotation_angle = detect_faces_with_rotation(app, image_rgb, orientation)
            
            if not faces:
                results.append({"file": f, "status": "NO_FACE", "faces": []})
                continue
                
            face_data = []
            for face in faces:
                bbox = [float(x) for x in face.bbox]
                # Send back a lightweight representation (base64 or just indices)
                # We can store embeddings temporarily in server state or send back as list
                emb_list = [float(x) for x in face.embedding]
                face_data.append({
                    "bbox": bbox,
                    "embedding": emb_list, # Will be sent back in confirm
                })
                
            status = "SINGLE_FACE" if len(faces) == 1 else "MULTIPLE_FACES"
            results.append({"file": f, "status": status, "faces": face_data, "rotation": rotation_angle})
            
        except Exception as e:
            results.append({"file": f, "status": "ERROR", "error": str(e)})
            
    return JSONResponse({"results": results})

@app.post("/api/samples/confirm")
def api_confirm_samples(payload: dict = Body(...)):
    player_id = payload.get("player_id")
    league = payload.get("league", "")
    season = payload.get("season", "")
    team = payload.get("team", "")
    source_type = payload.get("source_type", "")
    samples = payload.get("samples", [])
    
    import numpy as np
    import json
    
    inserted = 0
    skipped = 0
    
    for s in samples:
        source_file = s.get("file")
        bbox = s.get("bbox")
        emb_list = s.get("embedding")
        
        if not source_file or not bbox or not emb_list:
            continue
            
        bbox_json = json.dumps(bbox)
        embedding_bytes = np.array(emb_list, dtype=np.float32).tobytes()
        
        # Check duplicate
        with STATE.db._lock, STATE.db._connect() as conn:
            existing = conn.execute("SELECT id FROM training_samples WHERE player_id=? AND source_file=? AND face_bbox=?", (player_id, source_file, bbox_json)).fetchone()
            if existing:
                skipped += 1
                continue
        
        STATE.db.add_training_sample(
            player_id=player_id,
            source_file=source_file,
            face_bbox=bbox_json,
            embedding=embedding_bytes,
            league=league,
            season=season,
            team=team,
            source_type=source_type if source_type else "MANUAL",
            embedding_model="buffalo_l" # InsightFace default in this app
        )
        inserted += 1
        
    return JSONResponse({"status": "ok", "inserted": inserted, "skipped": skipped})



@app.post("/api/list-files")
def api_list_files(payload: dict = Body(...)):
    folder = payload.get("folder", "")
    if not os.path.isdir(folder):
        return JSONResponse({"files": []})
    
    files = []
    valid_ext = {".jpg", ".jpeg", ".png", ".webp"}
    for f in os.listdir(folder):
        if os.path.splitext(f)[1].lower() in valid_ext:
            files.append(os.path.join(folder, f))
    return JSONResponse({"files": sorted(files)})



@app.post("/api/models/train")
def api_train_model():
    samples = STATE.db.get_all_training_samples()
    if not samples:
        return JSONResponse({"error": "No training samples found"}, status_code=400)
    
    import numpy as np
    from sklearn.svm import SVC
    from sklearn.preprocessing import LabelEncoder
    from sklearn.metrics import accuracy_score
    import joblib
    import os
    import datetime
    import json

    # Prepare data
    embeddings = []
    labels = []
    for s in samples:
        # L2 Normalization (CRITICAL STEP)
        emb = np.frombuffer(s["embedding"], dtype=np.float32)
        emb_norm = emb / (np.linalg.norm(emb) + 1e-8)
        embeddings.append(emb_norm)
        labels.append(s["player_name"])

    X = np.array(embeddings)
    y = np.array(labels)
    
    le = LabelEncoder()
    y_enc = le.fit_transform(y)
    
    player_count = int(len(le.classes_))
    sample_count = int(len(y_enc))
    
    if player_count < 1:
        return JSONResponse({"error": "Need at least 1 player with samples"}, status_code=400)
        
    # Evaluation (Stratified Split where possible)
    classes, counts = np.unique(y_enc, return_counts=True)
    mask = np.isin(y_enc, classes[counts >= 2])
    metrics = {}
    
    if sum(mask) > 1 and len(np.unique(y_enc[mask])) >= 2:
        from sklearn.model_selection import train_test_split
        X_eval = X[mask]
        y_eval = y_enc[mask]
        try:
            X_train, X_test, y_train, y_test = train_test_split(X_eval, y_eval, test_size=0.2, stratify=y_eval, random_state=42)
            eval_clf = SVC(kernel='linear', C=1, probability=True, class_weight=None)
            eval_clf.fit(X_train, y_train)
            preds = eval_clf.predict(X_test)
            acc = float(accuracy_score(y_test, preds))
            metrics = {"accuracy": float(acc), "test_samples": int(len(y_test))}
        except Exception as e:
            metrics = {"error_eval": str(e)}
    else:
        metrics = {"note": "Insufficient samples for stratified split per player"}
            
    # Final Training on ALL data
    clf = SVC(kernel='linear', C=1, probability=True, class_weight=None)
    clf.fit(X, y_enc)
    
    # Save Model
    version_name = f"Player Recognition Model V{len(STATE.db.get_models()) + 1}"
    models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, f"{version_name}.joblib")
    
    model_data = {
        "model": clf,
        "label_encoder": le,
        "embeddings": X,
        "labels": y
    }
    
    joblib.dump(model_data, model_path)
    
    # Save to DB as CANDIDATE
    model_id = STATE.db.add_model(
        version_name=version_name,
        players_count=player_count,
        samples_count=sample_count,
        model_path=model_path,
        metrics=json.dumps(metrics),
        status="CANDIDATE"
    )
    
    return JSONResponse({
        "status": "ok",
        "model_id": int(model_id),
        "version_name": str(version_name),
        "metrics": metrics
    })


app.mount("/", StaticFiles(directory=WEBUI, html=True), name="webui")

