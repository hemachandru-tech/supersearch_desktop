"""
frozen_config.py  —  FROZEN recognition & pipeline parameters (client prototype).

Phase 1 ("Freeze the Application") converted every user-adjustable recognition
knob into a fixed internal value. These are NO LONGER read from .env or the (now
removed) Settings UI — they are the single, authoritative source of truth so the
prototype cannot be misconfigured.

The frozen values below are exactly the values the app shipped with in .env at
freeze time. If a parameter ever needs to change, edit it HERE (one place) and
re-test; do not reintroduce an environment-variable or UI control for it.

    Parameter                     Old (env)   Frozen value   Meaning
    ----------------------------  ----------  -------------  -------------------------------
    FACE_COSINE_THRESHOLD         0.30        0.30           "Face match strictness" (open-set gate)
    FACE_KNN_THRESHOLD            0.40        0.40           KNN-consensus similarity floor
    FACE_REVIEW_CONFIDENCE        0.50        0.50           "Auto-confirm confidence" (<- send to Review)
    FACE_CONFIDENCE_THRESHOLD     75          75.0           legacy SVC-probability gate (video path)
    FACE_MARGIN                   0.05        0.05           legacy top1-top2 margin (video path)
    FACE_MIN_SIZE                 30          30             "Minimum face size" (px)
    FACE_MIN_SHARPNESS            25          25.0           "Blur (sharpness) limit"
    FACE_PRIMARY_ONLY             true        True           "Focus on primary subject only"
    FACE_PRIMARY_AREA_RATIO       0.45        0.45           primary-subject area ratio
    FACE_MAX_FACES                20          20             crowd cutoff
    MAX_WORKERS                   4           4              pipeline concurrency
    GEMINI_MODEL                  flash       gemini-2.5-flash  Gemini vision model
    ENABLE_JERSEY                 true        True           jersey/apparel classifier fallback
    WRITE_METADATA                true        True           embed tags into files (kept ON)
"""

# ---- Face recognition (image + video paths) ----
FACE_COSINE_THRESHOLD = 0.30
FACE_KNN_THRESHOLD = 0.40
FACE_REVIEW_CONFIDENCE = 0.50
FACE_CONFIDENCE_THRESHOLD = 75.0
FACE_MARGIN = 0.05
FACE_MIN_SIZE = 30
FACE_MIN_SHARPNESS = 25.0
FACE_PRIMARY_ONLY = True
FACE_PRIMARY_AREA_RATIO = 0.45
FACE_MAX_FACES = 20

# ---- Pipeline ----
MAX_WORKERS = 4
GEMINI_MODEL = "gemini-2.5-flash"
ENABLE_JERSEY = True
WRITE_METADATA = True

# ---- Video Temporal Consensus ----
VIDEO_PLAYER_MIN_FRAMES = 5          # Absolute minimum frames a player must be seen in
VIDEO_PLAYER_MIN_FRAMES_RATIO = 0.05 # Minimum percentage of total extracted frames a player must be seen in
