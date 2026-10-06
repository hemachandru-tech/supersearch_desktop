import os

# ---------------------------- CONFIGURATION ----------------------------
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
BATCH_SIZE = 5
OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Model file locations. Anchored to the project root so they resolve regardless of the
# process working directory (important once packaged). The path can still be overridden
# via the environment for deployment flexibility, but the default points at the shipped
# frozen model. (The prototype is read-only inference — these models are never modified.)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACE_MODEL_PATH = os.getenv("FACE_MODEL_PATH", os.path.join(_PROJECT_ROOT, "models", "faces_custom.joblib"))
JERSEY_MODEL_PATH = os.getenv("JERSEY_MODEL_PATH", os.path.join(_PROJECT_ROOT, "models", "jersey.pth"))

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
        active_path = db.get_active_model_path()
        target_path = active_path if (active_path and os.path.exists(active_path)) else FACE_MODEL_PATH
        
        try:
            model_data = joblib.load(target_path)
            _clf = model_data["model"]
            _label_encoder = model_data["label_encoder"]
        except Exception as e:
            print(f"[config] Failed to load classifier from {target_path}: {e}")
            # If active model fails, fallback to default
            if target_path != FACE_MODEL_PATH:
                print(f"[config] Falling back to {FACE_MODEL_PATH}")
                model_data = joblib.load(FACE_MODEL_PATH)
                _clf = model_data["model"]
                _label_encoder = model_data["label_encoder"]
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
