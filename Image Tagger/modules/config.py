import os
import re

# ---------------------------- CONFIGURATION ----------------------------
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
BATCH_SIZE = 5
OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Model file locations. Anchored to the project root so they resolve regardless of the
# process working directory (important once packaged). Paths can still be overridden via
# the environment for deployment flexibility.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODELS_DIR = os.path.join(_PROJECT_ROOT, "models")

# The 42-player model the prototype originally shipped with. Kept as the last-resort
# fallback only: it stores no embeddings, so Player Management can neither evaluate nor
# retrain from it.
LEGACY_FACE_MODEL_PATH = os.path.join(_MODELS_DIR, "faces_custom.joblib")

_PLAYER_MODEL_RE = re.compile(r"^Player Recognition Model V(\d+)\.joblib$")


def latest_player_model_path():
    """Path to the highest-numbered 'Player Recognition Model V<n>.joblib' in models/.

    Retraining writes each new model as V1, V2, V3 … and the app normally picks one up
    from the ACTIVE row in the models table. On a fresh checkout that table is empty, so
    without this the app would silently fall back to the legacy 42-player model and
    ignore the newer ones sitting right next to it. Returns None if none are present.
    """
    try:
        entries = os.listdir(_MODELS_DIR)
    except OSError:
        return None
    best_version, best_path = -1, None
    for name in entries:
        m = _PLAYER_MODEL_RE.match(name)
        if m and int(m.group(1)) > best_version:
            best_version, best_path = int(m.group(1)), os.path.join(_MODELS_DIR, name)
    return best_path


def resolve_model_path(path):
    """Return `path` if it is usable, otherwise the same filename inside models/.

    Model paths are recorded in the database as absolute paths, so a database copied
    between machines (or an app folder that moved) points at files that no longer exist.
    The models themselves ship with the app, so look them up by name before giving up.
    """
    if not path:
        return None
    if os.path.exists(path):
        return path
    relocated = os.path.join(_MODELS_DIR, os.path.basename(path))
    return relocated if os.path.exists(relocated) else None


# Default player-recognition model: an explicit override wins, then the newest shipped
# "Player Recognition Model V<n>", then the legacy model.
FACE_MODEL_PATH = (
    os.getenv("FACE_MODEL_PATH")
    or latest_player_model_path()
    or LEGACY_FACE_MODEL_PATH
)
JERSEY_MODEL_PATH = os.getenv("JERSEY_MODEL_PATH", os.path.join(_MODELS_DIR, "jersey.pth"))

# ----------------------------------------------------------------------------
# LAZY MODEL LOADING
# ----------------------------------------------------------------------------
# Heavy ML components (InsightFace/ArcFace ONNX ~325MB, Torch jersey ResNet ~90MB,
# the sklearn classifier) are NOT loaded at import time. They initialize on first
# actual use so the app can start, browse, search and filter instantly. Once loaded,
# each component is cached for the rest of the process (no repeated reloads).
#
# Backward compatibility: module-level names `app`, `clf`, `label_encoder`,
# `jersey_model` still work via __getattr__ — they simply trigger the lazy loader on
# first access. Existing consumers (image_processing / video_processor / local_pipeline)
# import these only inside the tagging code path, so the heavy load happens at tagging.
_clf = None
_label_encoder = None
_face_app = None
_jersey_model = None


def get_classifier():
    """Load the sklearn face classifier + label encoder (light: ~10MB joblib). Cached."""
    global _clf, _label_encoder
    if _clf is None:
        import joblib
        from local_db import LocalDB
        db = LocalDB()

        # Try the model the user activated, then the shipped default, then the legacy
        # model — so a missing or corrupt file degrades instead of breaking tagging.
        candidates = [resolve_model_path(db.get_active_model_path()),
                      FACE_MODEL_PATH,
                      LEGACY_FACE_MODEL_PATH]
        seen, last_error = set(), None
        for target_path in candidates:
            if not target_path or target_path in seen:
                continue
            seen.add(target_path)
            try:
                model_data = joblib.load(target_path)
                _clf = model_data["model"]
                _label_encoder = model_data["label_encoder"]
                print(f"[config] Player recognition model: {os.path.basename(target_path)} "
                      f"({len(_label_encoder.classes_)} players)")
                break
            except Exception as e:
                last_error = e
                print(f"[config] Failed to load classifier from {target_path}: {e}")
        else:
            raise RuntimeError(
                f"No usable player recognition model found in {_MODELS_DIR}"
            ) from last_error
    return _clf




def reload_classifier():
    global _clf, _label_encoder
    _clf = None
    _label_encoder = None
    
    # Invalidate embedding caches in image_processing
    try:
        from modules import image_processing
        image_processing.clear_embedding_caches()
    except Exception as e:
        print(f"[config] Failed to clear embedding caches: {e}")
        
    return get_classifier()


def get_label_encoder():
    """The trained-roster label encoder (its .classes_ is the master player list)."""
    if _label_encoder is None:
        get_classifier()
    return _label_encoder


def get_face_app():
    """Initialize InsightFace/ArcFace (heavy: ~325MB ONNX + session prepare). Cached."""
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis
        from modules import paths
        a = FaceAnalysis(name="buffalo_l", root=paths.insightface_root(),
                         providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        a.prepare(ctx_id=0, det_size=(640, 640))
        _face_app = a
    return _face_app


def get_jersey_model():
    """Load the Torch ResNet jersey classifier (heavy: ~90MB). Cached."""
    global _jersey_model
    if _jersey_model is None:
        from modules.jersey_classifier import load_model
        _jersey_model = load_model(JERSEY_MODEL_PATH)
    return _jersey_model


def __getattr__(name):
    # PEP 562: resolve the legacy module-level names lazily on first access.
    if name == "clf":
        return get_classifier()
    if name == "label_encoder":
        return get_label_encoder()
    if name == "app":
        return get_face_app()
    if name == "jersey_model":
        return get_jersey_model()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
