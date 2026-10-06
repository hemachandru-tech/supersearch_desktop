"""
modules/paths.py — single source of truth for WHERE files live.

Two kinds of paths:

1. READ-ONLY bundled resources (webui/, models/, tools/, .env.template) — these ship
   inside the app and are resolved relative to the project/app directory.

2. WRITABLE state (tags.db, caches, logs, app_state.json, .env, the Chrome .appwindow
   profile, temp/scratch dirs) — these must live in a writable location.

Why this matters for packaging
------------------------------
In a signed macOS `.app`, `Contents/Resources` is READ-ONLY. Writing tags.db / logs /
the browser profile next to the code (as the dev build does) fails there. So when the
app is "packaged", all writable state is redirected to:

    ~/Library/Application Support/SuperSearch/

Detection
---------
The app is considered "packaged" when ANY of these is true:
  - env  SUPERSEARCH_PACKAGED=1   (set by the .app launcher)
  - the code lives inside a  *.app/Contents/  bundle
  - PyInstaller's  sys.frozen  is set
You can also force the writable dir anywhere (e.g. for testing in dev) with:
  - env  SUPERSEARCH_DATA_DIR=/some/path

In a plain dev checkout none of these apply, so writable state stays in the project
root exactly as before — preserving the existing tags.db and dev workflow.
"""

import os
import sys
import shutil

APP_NAME = "SuperSearch"

# Project/app root = the directory that contains this `modules/` package.
_RESOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_root():
    """Absolute path to read-only bundled resources (webui/, models/, tools/, …)."""
    # PyInstaller onefile would unpack to sys._MEIPASS; harmless to honour it if present.
    return getattr(sys, "_MEIPASS", None) or _RESOURCE_ROOT


def resource_path(*parts):
    return os.path.join(resource_root(), *parts)


def is_packaged():
    if os.environ.get("SUPERSEARCH_PACKAGED") == "1":
        return True
    if getattr(sys, "frozen", False):
        return True
    if ".app/Contents/" in _RESOURCE_ROOT:
        return True
    return False


def data_dir():
    """Writable base directory for all runtime state. Created if missing."""
    override = os.environ.get("SUPERSEARCH_DATA_DIR")
    if override:
        base = override
    elif is_packaged():
        base = os.path.join(os.path.expanduser("~/Library/Application Support"), APP_NAME)
    else:
        base = _RESOURCE_ROOT  # dev: keep state in the project root (no behaviour change)
    os.makedirs(base, exist_ok=True)
    return base


def cache_dir():
    """Writable dir for disposable scratch/temp output (frames, previews)."""
    d = os.path.join(data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def data_path(*parts):
    return os.path.join(data_dir(), *parts)


def env_file():
    """Path to the runtime .env (in the writable data dir)."""
    return os.path.join(data_dir(), ".env")


def env_path():
    """READ-ONLY .env to load at startup.

    The app never writes .env anymore (the Settings UI / write_env were removed in the
    freeze), so config + the bundled API key are read directly from the app's resources:
      - dev checkout : <project>/.env
      - packaged .app: Contents/Resources/app/.env   (key bundled at build time)
    Falls back to .env.template only if no real .env shipped.
    """
    p = resource_path(".env")
    return p if os.path.exists(p) else resource_path(".env.template")


def appwindow_profile():
    """Chrome/Edge user-data-dir — MUST be writable."""
    return os.path.join(data_dir(), ".appwindow")


def insightface_root():
    """Root passed to InsightFace FaceAnalysis(root=…).

    InsightFace expects  <root>/models/<name>  (e.g. .../models/buffalo_l).
    Prefer a bundled copy under resources (models/insightface) so a packaged app
    needs no network download; otherwise fall back to the default ~/.insightface.
    """
    bundled = resource_path("models", "insightface")
    if os.path.isdir(os.path.join(bundled, "models", "buffalo_l")):
        return bundled
    return os.path.expanduser("~/.insightface")


def seed_env_if_missing():
    """Ensure a writable .env exists. On first run of a packaged app, copy it from
    the bundled .env.template (or a legacy project .env). Idempotent / safe in dev."""
    target = env_file()
    if os.path.exists(target):
        return target
    for src in (resource_path(".env"), resource_path(".env.template")):
        if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(target):
            try:
                shutil.copyfile(src, target)
            except Exception:
                pass
            break
    return target
