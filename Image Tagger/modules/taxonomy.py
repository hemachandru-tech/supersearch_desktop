"""
Canonical, UI-facing controlled vocabularies for the editable SCENE metadata fields.

WHY THIS FILE EXISTS
--------------------
The authoritative taxonomy is the `CricketImageAnalysis` Pydantic schema in
`modules/ai_tags.py` (the structured response contract sent to Gemini). Those
values, however, live inside Field description strings and inside an *instance*
attribute (`CricketImageAnalyzer.cricket_vocabulary`) that can only be built by
constructing the analyzer — which requires Gemini API keys. The web UI must be
able to render dropdowns WITHOUT instantiating the analyzer.

So these lists are a small, importable, module-level MIRROR of the allowed
values defined in `ai_tags.py`. They are the single source the backend serves
to the UI for controlled-vocabulary dropdowns and filters.

KEEPING IN SYNC
---------------
If the allowed values in `ai_tags.py::CricketImageAnalysis` ever change, update
the matching list here. (Future improvement: have ai_tags.py build its Field
descriptions from these constants so there is exactly one source of truth.)

These map to DB columns as follows (see local_db.py):
    EVENT_TYPES   -> images.event_type
    MOODS         -> images.mood
    ACTIONS       -> images.action
    LOCATIONS     -> images.location
    APPAREL_TYPES -> images.apparel   (jersey *type*, NOT colour)
"""

# images.event_type  (mirrors ai_tags.py CricketImageAnalysis.event_type)
EVENT_TYPES = [
    "match", "practice", "training", "press conference", "promotional event",
    "fan engagement", "community engagement", "award ceremony", "team meeting",
    "team travel", "post-match interview", "Others",
]

# images.mood  (mirrors ai_tags.py CricketImageAnalysis.mood)
MOODS = [
    "focused", "relaxed", "determined", "confident", "energetic", "happy",
    "surprised", "calm", "proud", "tense", "disappointed", "intense", "anxious",
    "relieved", "joyful", "Neutral",
]

# images.action  (mirrors ai_tags.py CricketImageAnalysis.action)
ACTIONS = [
    "batting", "bowling", "fielding", "catching", "throwing", "wicket-keeping",
    "celebrating", "running", "jogging", "stretching", "discussing",
    "strategizing", "practicing", "cheering", "walking", "talking", "sitting",
    "posing", "jumping", "interviewing", "signing autographs", "standing",
    "observing", "ordering food", "delivering an order", "resting",
]

# images.location  (mirrors ai_tags.py CricketImageAnalysis.location)
LOCATIONS = [
    "stadium", "field", "pitch", "crease", "practice nets", "hotel", "airport",
    "dressing room", "gym", "grandstand", "pavilion", "restaurant", "photo studio",
]

# images.apparel — jersey TYPE, not colour.
# (mirrors ai_tags.py CricketImageAnalysis.apparel; superset of the
#  jersey_classifier class_names ['Match Jersey', 'Off Field kit', 'Practice Jersey'])
APPAREL_TYPES = [
    "Match Jersey", "Practice Jersey", "Off Field kit", "Casual Attire", "Unknown",
]
