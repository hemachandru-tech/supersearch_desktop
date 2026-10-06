import os
from google import genai
from google.genai import types
from PIL import Image
import json
from pydantic import BaseModel, Field

import pandas as pd
from pathlib import Path
import time
import logging
from datetime import datetime
import hashlib
from typing import Dict, List, Optional, Tuple
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3
from dataclasses import dataclass
from queue import Queue
from io import BytesIO
import re

# Project root (parent of this module's "modules" folder). Used so the log file and
# the Gemini result cache resolve to a stable location regardless of the process CWD
# (important once the app is packaged / launched from arbitrary working directories).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from modules import paths

# Configure logging — log file lives in the writable data dir (App Support when packaged).
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(paths.data_path('cricket_analyzer.log')),
              logging.StreamHandler()]
)

# Optional: where we look for annotated twins of the image
ANNOTATED_DIRS: List[str] = ["results/annotated", "annotated", "outputs/annotated"]

def _prepare_image_for_gemini(pil_img: Image.Image, max_side: int = 1024, quality: int = 80) -> Image.Image:
    """
    Make a Gemini-friendly copy:
      - RGB only (no CMYK/alpha/16-bit)
      - downscale to max_side
      - strip EXIF by round-tripping through BytesIO
      - JPEG quality (default 80)
    Returns a new PIL.Image ready for generate_content().
    """
    img = pil_img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, subsampling=2)
    buf.seek(0)
    return Image.open(buf)


class CricketImageAnalysis(BaseModel):
    event_type: str = Field(description="One of: match, practice, training, press conference, promotional event, fan engagement, community engagement, award ceremony, team meeting, team travel, post-match interview, Others")
    mood: str = Field(description="One of: focused, relaxed, determined, confident, energetic, happy, surprised, calm, proud, tense, disappointed, intense, anxious, relieved, joyful, Neutral")
    action: str = Field(description="One of: batting, bowling, fielding, catching, throwing, wicket-keeping, celebrating, running, jogging, stretching, discussing, strategizing, practicing, cheering, walking, talking, sitting, posing, jumping, interviewing, signing autographs, standing, observing, ordering food, delivering an order, resting")
    location: str = Field(description="One of: stadium, field, pitch, crease, practice nets, hotel, airport, dressing room, gym, grandstand, pavilion, restaurant, photo studio")
    jersey_color: str = Field(description="Comma-separated colors that clearly appear, e.g. Yellow, Blue, or 'Not visible'")
    apparels_seen: str = Field(description="Comma-separated list of visible apparel items")
    apparel: str = Field(description="The primary kit type visible on the main player(s). Select one of: Match Jersey, Practice Jersey, Off Field kit, Casual Attire, Unknown")
    crowd_present: str = Field(description="Yes or No")
    logos_branding: str = Field(description="Comma-separated commercial sponsor/brand names only (e.g. Gulf, TVS) or 'None'. Do NOT include league/tournament/competition names like SA20 or IPL.")
    players: str = Field(description="Comma-separated list of recognized cricket player names (full names if possible, e.g. 'MS Dhoni, Ruturaj Gaikwad'), or 'None'")
    caption: str = Field(description="A vivid 2-3 sentence description (about 40-70 words) covering the main action, the setting/location, the kit/jersey colour, and the mood. Professional sports-commentary style. NO player names, nicknames, jersey numbers, league/tournament/season names or years.")

@dataclass
class AnalysisResult:
    image_file: str
    event_type: str = "Others"
    file_path: str = ""
    mood: str = "Neutral"
    action: str = "Standing"
    location: str = "Stadium"
    jersey_color: str = "Not visible"
    apparels_seen: str = "Jersey"
    apparel: str = "Unknown"
    caption: str = "Cricket scene"
    crowd_present: str = "No"
    logos_branding: str = "None"
    players: str = "None"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    processing_time: float = 0.0
    status: str = "pending"
    error_message: str = ""
    retry_count: int = 0
    api_key_used: str = ""
    # Confidence scores
    mood_confidence: float = 0.0
    action_confidence: float = 0.0
    location_confidence: float = 0.0
    event_type_confidence: float = 0.0

class CricketImageAnalyzer:
    def __init__(self, api_keys: List[str], max_workers: int = 3, max_retries: int = 3):
        if not api_keys:
            import logging
            logging.warning("No Gemini API key provided. AI tagging features will fail if invoked.")
            api_keys = []

        self.api_keys = api_keys
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.confidence_threshold = 0.80
        # Get model from state or fallback to FROZEN
        from modules import frozen_config as FROZEN
        self.model = FROZEN.GEMINI_MODEL
        try:
            import json, os
            from modules.paths import data_path
            state_file = data_path("app_state.json")
            if os.path.exists(state_file):
                with open(state_file, encoding="utf-8") as f:
                    state = json.load(f) or {}
                    if "gemini_model" in state:
                        self.model = state["gemini_model"]
        except Exception:
            pass

        self.api_key_queue = Queue()
        for key in api_keys:
            self.api_key_queue.put(key)

        self.clients = {}
        for key in api_keys:
            try:
                self.clients[key] = genai.Client(api_key=key)
            except Exception as e:
                logging.error(f"Error initializing client for API key: {str(e)}")

        self.db_path = paths.data_path("cricket_analysis_progress.db")
        self.init_database()

        self.cricket_vocabulary = {
            "mood": ["focused","relaxed","determined","confident","energetic","happy","surprised","calm","proud",
                     "tense","disappointed","intense","anxious","relieved","joyful"],
            "actions": ["batting","bowling","fielding","catching","throwing","wicket-keeping","celebrating","running",
                        "jogging","stretching","discussing","strategizing","practicing","cheering","walking","talking",
                        "sitting","posing","jumping","interviewing","signing autographs","standing","observing",
                        "ordering food","delivering an order","resting"],
            "locations":["stadium","field","pitch","crease","practice nets","hotel","airport","dressing room","gym",
                         "grandstand","pavilion","restaurant","photo studio"],
            "event_types": ["match","practice","training","press conference","promotional event","fan engagement",
                            "community engagement","award ceremony","team meeting","team travel","post-match interview"],
            "apparel_items":["jersey","trousers","hat","cap","helmet","batting pads","wicket-keeping pads",
                             "batting gloves","wicket-keeping gloves","shoes","spikes","sunglasses","arm guard",
                             "thigh pad","chest guard","wristband","training kit","tracksuit","towel","polo shirt"],
            "crowd_present": ["Yes","No"],
            "jersey_colors": ["Blue","Red","Green","Yellow","White","Black","Orange","Purple","Pink","Grey","Navy",
                              "Sky Blue","Dark Green","Light Blue","Maroon","Multi-colored","Not visible"]
        }

        self.api_key_stats = {key: {'last_request_time': 0,'request_count': 0,'token_count': 0,'error_count': 0}
                              for key in api_keys}
        self.min_request_interval = 1.0
        self.request_lock = threading.Lock()

    # ---------- Gemini helpers ----------
    def _genai_call_with_backoff(self, client, prompt: str, pil_img: Image.Image):
        """
        One call with progressively smaller/leaner images if Gemini returns 500/internal errors.
        """
        tiers = [
            (1024, 80),
            (896, 75),
            (768, 70),
            (640, 65),
            (512, 60),
        ]
        last_err = None
        for max_side, quality in tiers:
            try:
                prepped = _prepare_image_for_gemini(pil_img, max_side=max_side, quality=quality)
                resp = client.models.generate_content(
                    model=self.model,
                    contents=[prompt, prepped],
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=CricketImageAnalysis
                    ),
                )
                return resp, (max_side, quality)
            except Exception as e:
                msg = str(e).lower()
                last_err = e
                if "500" in msg or "internal error" in msg or "backend error" in msg:
                    logging.warning(f"Gemini 500/internal at tier {max_side}/{quality}. Trying smaller tier...")
                    continue
                else:
                    raise
        raise last_err if last_err else RuntimeError("Gemini call failed without exception detail")

    def get_next_api_key(self) -> str:
        with self.request_lock:
            key = self.api_key_queue.get()
            self.api_key_queue.put(key)
            return key

    def update_api_key_stats(self, api_key: str, tokens_used: int = 0, error_occurred: bool = False):
        with self.request_lock:
            stats = self.api_key_stats[api_key]
            stats['last_request_time'] = time.time()
            stats['request_count'] += 1
            stats['token_count'] += tokens_used
            if error_occurred:
                stats['error_count'] += 1

    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_hash TEXT UNIQUE,
                image_path TEXT,
                status TEXT,
                result_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def get_image_hash(self, image_content: bytes) -> str:
        return hashlib.md5(image_content).hexdigest()

    def is_already_processed(self, image_hash: str) -> Optional[AnalysisResult]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT result_json FROM analysis_progress WHERE image_hash = ? AND status = 'completed'",
            (image_hash,)
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return AnalysisResult(**json.loads(result[0]))
        return None

    def save_progress(self, image_hash: str, image_path: str, result: AnalysisResult):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO analysis_progress (image_hash, image_path, status, result_json)
            VALUES (?, ?, ?, ?)
        ''', (image_hash, image_path, result.status, json.dumps(result.__dict__)))
        conn.commit()
        conn.close()

    def find_annotated_version(self, image_path: str) -> Optional[str]:
        base = os.path.basename(image_path)
        for d in ANNOTATED_DIRS:
            cand = os.path.join(d, base)
            if os.path.exists(cand):
                return cand
        parent = os.path.dirname(image_path)
        cand_local = os.path.join(parent, "annotated", base)
        if os.path.exists(cand_local):
            return cand_local
        return None

    def create_analysis_prompt(self, player_names: str = None) -> str:
        player_info_str = ""
        if player_names and player_names != "Unknown" and player_names.strip():
            player_info_str = f"""
**PLAYERS PRESENT (CONTEXT ONLY — DO NOT NAME THEM):**
Our face-recognition system has already identified the player(s) in this image: {player_names}.
- This is for your scene understanding ONLY. Do NOT write any of these names (or any other
  player names) in the Caption. We add the correct names ourselves afterwards.
- Refer to people generically in the caption (e.g. "the batsman", "two players", "the team").
"""

        # SINGLE-CALL prompt: includes caption in required output.
        return f"""You are a cricket image analysis expert. Analyze this cricket image and provide values with confidence scores.

{player_info_str}
**CRITICAL INSTRUCTIONS FOR JERSEY & APPAREL IDENTIFICATION:**
- **Match Jersey**: This is the official jersey worn by players during actual tournament matches or official match-day promotional media shoots.
  - For CSK (Chennai Super Kings), it is the iconic BRIGHT YELLOW jersey, typically featuring prominent sponsors on the front (such as "Gulf", "Etihad Airways", "Eurogrip Tyres").
  - For RR (Rajasthan Royals), it is Royal Blue or Pink match kit.
  - It is typically seen in a stadium, pitch, or crease setting, often with a crowd, floodlights, or action-packed match play (batting, bowling, fielding, celebrating a wicket).
- **Practice Jersey / Training Kit**: This is worn during nets practice, training sessions, warm-ups, or gym workouts.
  - For CSK, training/practice jerseys are typically NAVY BLUE, ROYAL BLUE, or secondary blue training designs. (Sometimes yellow shirts are used, but they lack the official match-day sponsors/detailing).
  - For RR, practice kits are typically pink/purple/navy training shirts.
  - It is typically seen in "practice nets" or gym locations, and the crowd is almost always "No".
- **Off Field kit**: Official team travel gear, team meeting polos, tracksuits, or hoodies worn during travel, hotel stays, press conferences, or team meetings.
- **Casual Attire**: Everyday civilian clothes, t-shirts, shirts, or suits worn when players are off-duty, or when fans are pictured.

**GUIDELINES FOR OTHER ATTRIBUTES:**
- **Event Type**: Choose `match` ONLY for actual match play. Choose `practice` or `training` for net sessions and practice fields. Choose `promotional event` for studio shoots, commercial shoots, or official pose sessions.
- **Crowd Present**: Select `Yes` if spectators are visible in the background stadium seats. Select `No` for practice nets, empty stadiums, dressing rooms, hotels, or studio photoshoots.
- **Mood**: Choose the option that best reflects the emotional tone (e.g., `focused` during active play/nets; `relaxed` in dressing rooms/dugouts; `joyful` during celebrations; `Neutral` for normal/idle).
- **Location**: Be specific: `stadium` (general stadium context), `pitch` or `crease` (on the playing wicket), `practice nets` (nets visible in background), `dressing room`, `hotel`, etc.

**VOCABULARY LISTS**
EVENT TYPES (select ONE most fitting for the overall context of the image):
{', '.join(self.cricket_vocabulary['event_types'])}
MOODS (choose ONE that best matches the overall context of the image):
{', '.join(self.cricket_vocabulary['mood'])}
ACTIONS (choose ONE primary action):
{', '.join(self.cricket_vocabulary['actions'])}
LOCATIONS (choose ONE):
{', '.join(self.cricket_vocabulary['locations'])}
JERSEY COLORS (can list multiple if visible):
{', '.join(self.cricket_vocabulary['jersey_colors'])}
APPARELS SEEN (list all visible, comma-separated):
{', '.join(self.cricket_vocabulary['apparel_items'])}
APPAREL (choose ONE primary kit classification):
Match Jersey, Practice Jersey, Off Field kit, Casual Attire, Unknown
CROWD PRESENT: Yes or No

**DESCRIPTION GUIDELINES (MANDATORY - DO NOT SKIP):**
- Write a vivid, informative description of 2-3 sentences (about 40-70 words) - NOT one line.
- Cover: the main action, the setting/location, the KIT/JERSEY COLOUR, the mood, and any
  notable context (crowd, floodlights, nets, studio, dressing room, etc.).
- Style: Professional sports commentary (energetic but factual).
- CRITICAL: Do NOT include ANY player names, nicknames, or jersey numbers.
  Refer to people generically: "the batsman", "a bowler", "two players", "the team".
  (The correct names are added automatically from our own face recognition.)
- CRITICAL: Do NOT name or guess any league, tournament, competition, season, or year
  (e.g. do NOT write "SA20", "IPL", "2026"). The tournament is recorded separately.
- NO hashtags, emojis, or promotional language.
- Example: "A batsman in a bright yellow match jersey executes a powerful pull shot on the
  pitch. Teammates watch from the boundary as the floodlit stadium crowd looks on, capturing
  a tense, high-energy passage of match play."
- Example: "Two players in navy-blue practice kit run drills in the nets during a relaxed
  training session. The empty practice ground and focused expressions convey a calm, workmanlike mood."

**OUTPUT FORMAT (follow exactly, include ALL fields):**
Event Type: [value] (Confidence: XX%)
Mood: [value] (Confidence: XX%)
Action: [value] (Confidence: XX%)
Location: [value] (Confidence: XX%)
Jersey Color: [comma-separated values]
Apparels Seen: [comma-separated values]
Apparel: [value]
Crowd Present: [Yes/No] (Confidence: XX%)
Logos/Branding: [List brand/team/sponsor names or "None"]
Players: [Leave as "None" — player identification is handled by our own face-recognition system]
Caption: [Write a complete descriptive sentence here, with NO player names - MANDATORY]
"""

    def rate_limit(self, api_key: str):
        with self.request_lock:
            stats = self.api_key_stats[api_key]
            current_time = time.time()
            time_since_last = current_time - stats['last_request_time']
            if time_since_last < self.min_request_interval:
                time.sleep(self.min_request_interval - time_since_last)

    def extract_confidence(self, text: str) -> Tuple[str, float]:
        confidence_pattern = r'\(Confidence:\s*(\d+)%\)'
        match = re.search(confidence_pattern, text)
        if match:
            confidence = float(match.group(1)) / 100.0
            value = re.sub(confidence_pattern, '', text).strip()
            return value, confidence
        return text.strip(), 0.0

    def select_with_confidence(self, value: str, confidence: float,
                               vocabulary_list: List[str], default: str) -> Tuple[str, float]:
        if confidence < self.confidence_threshold:
            logging.info(f"Confidence {confidence:.2%} below threshold for '{value}', using highest confidence option")
        value_lower = value.lower().strip()
        for vocab in vocabulary_list:
            if vocab.lower() == value_lower:
                return vocab, confidence
        for vocab in vocabulary_list:
            if value_lower in vocab.lower() or vocab.lower() in value_lower:
                return vocab, confidence
        logging.warning(f"No vocabulary match for '{value}', using default '{default}'")
        return default, 0.0

    def parse_analysis_text(self, analysis_text: str) -> Dict[str, any]:
        parsed = {
            'event_type': 'Others','mood': 'Neutral','action': 'Standing','location': 'Stadium',
            'jersey_color': 'Not visible','apparels_seen': 'Jersey','apparel': 'Unknown','caption': 'Cricket scene',
            'crowd_present': 'No','logos_branding': 'None','players': 'None',
            'event_type_confidence': 0.0,'mood_confidence': 0.0,'action_confidence': 0.0,'location_confidence': 0.0
        }
        lines = analysis_text.split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('Event Type:'):
                raw_value = line.replace('Event Type:', '').strip()
                value, conf = self.extract_confidence(raw_value)
                parsed['event_type'], parsed['event_type_confidence'] = self.select_with_confidence(
                    value, conf, self.cricket_vocabulary['event_types'], 'Others'
                )
            elif line.startswith('Mood:'):
                raw_value = line.replace('Mood:', '').strip()
                value, conf = self.extract_confidence(raw_value)
                parsed['mood'], parsed['mood_confidence'] = self.select_with_confidence(
                    value, conf, self.cricket_vocabulary['mood'], 'Neutral'
                )
            elif line.startswith('Action:'):
                raw_value = line.replace('Action:', '').strip()
                value, conf = self.extract_confidence(raw_value)
                parsed['action'], parsed['action_confidence'] = self.select_with_confidence(
                    value, conf, self.cricket_vocabulary['actions'], 'Standing'
                )
            elif line.startswith('Location:'):
                raw_value = line.replace('Location:', '').strip()
                value, conf = self.extract_confidence(raw_value)
                parsed['location'], parsed['location_confidence'] = self.select_with_confidence(
                    value, conf, self.cricket_vocabulary['locations'], 'Stadium'
                )
            elif line.startswith('Jersey Color:'):
                value = line.replace('Jersey Color:', '').strip()
                colors = [c.strip() for c in value.split(',')]
                validated = []
                for color in colors:
                    for vocab in self.cricket_vocabulary['jersey_colors']:
                        if color.lower() in vocab.lower() or vocab.lower() in color.lower():
                            validated.append(vocab)
                            break
                parsed['jersey_color'] = ', '.join(validated) if validated else 'Not visible'
            elif line.startswith('Apparels Seen:'):
                value = line.replace('Apparels Seen:', '').strip()
                items = [a.strip() for a in value.split(',')]
                validated = []
                for apparel in items:
                    for vocab in self.cricket_vocabulary['apparel_items']:
                        if apparel.lower() in vocab.lower() or vocab.lower() in apparel.lower():
                            validated.append(vocab)
                            break
                parsed['apparels_seen'] = ', '.join(set(validated)) if validated else 'Jersey'
            elif line.startswith('Apparel:'):
                value = line.replace('Apparel:', '').strip()
                parsed['apparel'] = value if value else 'Unknown'
            elif line.startswith('Caption:'):
                # already included in single-call analysis
                cap = line.replace('Caption:', '').strip()
                # Remove extra whitespace but keep the sentence structure
                cap = re.sub(r"\s+", " ", cap).strip()
                
                # Only truncate if significantly over limit (25 words)
                words = cap.split()
                if len(words) > 25:
                    cap = " ".join(words[:25])
                    # Clean trailing punctuation
                    cap = re.sub(r'[,;:\s]+$', '', cap)
                
                # Use the caption if it's meaningful (not empty and not just punctuation)
                if cap and len(cap) > 5 and not cap.replace(' ', '').replace('.', '').replace(',', '') == '':
                    parsed['caption'] = cap
                else:
                    logging.warning(f"Caption parsing failed or empty: '{cap}'")
                    parsed['caption'] = 'Cricket scene'
            elif line.startswith('Crowd Present:'):
                raw_value = line.replace('Crowd Present:', '').strip()
                value, _ = self.extract_confidence(raw_value)
                parsed['crowd_present'] = 'Yes' if 'yes' in value.lower() else 'No'
            elif line.startswith('Logos/Branding:'):
                value = line.replace('Logos/Branding:', '').strip()
                parsed['logos_branding'] = value if value and value.lower() not in ['unknown','n/a','none detected','none'] else 'None'
            elif line.startswith('Players:'):
                value = line.replace('Players:', '').strip()
                parsed['players'] = value if value and value.lower() not in ['none', 'unknown', 'n/a'] else 'None'
        return parsed

    def analyze_single_image(self, image_path: str, retry_count: int = 0, force_recache: bool = False, player_names: str = None) -> AnalysisResult:
        result = AnalysisResult(
            image_file=os.path.basename(image_path),
            file_path=image_path,
            retry_count=retry_count
        )
        try:
            start_time = time.time()
            with open(image_path, 'rb') as f:
                image_content = f.read()
                image_hash = self.get_image_hash(image_content)
            original_img = Image.open(BytesIO(image_content))

            # USE ANNOTATED IMAGE FOR THE SINGLE CALL IF AVAILABLE
            annotated_path = self.find_annotated_version(image_path)
            image_for_single_call = Image.open(annotated_path) if annotated_path else original_img

            cached_result = None if force_recache else self.is_already_processed(image_hash)
            if cached_result:
                logging.info(f"Using cached result for {result.image_file}")
                return cached_result

            api_key = self.get_next_api_key()
            result.api_key_used = api_key
            self.rate_limit(api_key)

            client = self.clients.get(api_key)
            if not client:
                raise RuntimeError(f"No Gemini client for API key")
            # ---- SINGLE CALL (analysis + caption) with backoff on compressed variants ----
            prompt = self.create_analysis_prompt(player_names)
            try:
                response, tier = self._genai_call_with_backoff(client, prompt, image_for_single_call)
                logging.info(f"Single-call (analysis+caption) generated using tier {tier[0]}/{tier[1]}")
            except Exception as e:
                raise RuntimeError(f"Gemini single-call failed after compression backoff: {e}")

            # Debug logging - see what Gemini is actually returning
            response_text = getattr(response, "text", "") or ""
            logging.info(f"=== RAW GEMINI RESPONSE for {result.image_file} ===")
            logging.info(response_text)
            logging.info(f"=== END RESPONSE ===")

            # New SDK: usage on response.usage_metadata or response.usage
            usage = getattr(response, 'usage_metadata', None) or getattr(response, 'usage', None)
            if usage is not None:
                result.input_tokens = getattr(usage, 'prompt_token_count', None) or getattr(usage, 'prompt_tokens', 0) or 0
                result.output_tokens = getattr(usage, 'candidates_token_count', None) or getattr(usage, 'completion_tokens', 0) or 0
                result.total_tokens = getattr(usage, 'total_token_count', None) or getattr(usage, 'total_tokens', 0) or (result.input_tokens + result.output_tokens)

            result.processing_time = time.time() - start_time
            self.update_api_key_stats(api_key, result.total_tokens)

            parsed_data = {}
            try:
                parsed_data = json.loads(response_text)
                # Set confidence score defaults
                parsed_data['event_type_confidence'] = 0.95
                parsed_data['mood_confidence'] = 0.95
                parsed_data['action_confidence'] = 0.95
                parsed_data['location_confidence'] = 0.95
            except Exception as json_err:
                logging.warning(f"JSON parsing failed for {result.image_file}, falling back to text parsing: {json_err}")
                parsed_data = self.parse_analysis_text(response_text)

            for key, value in parsed_data.items():
                if hasattr(result, key) and value is not None:
                    setattr(result, key, value)

            result.status = "completed"
            self.save_progress(image_hash, image_path, result)

            logging.info(
                f"Successfully analyzed {result.image_file} - "
                f"Mood: {result.mood} ({result.mood_confidence:.0%}), "
                f"Action: {result.action} ({result.action_confidence:.0%}), "
                f"Caption: {result.caption}"
            )

        except Exception as e:
            result.status = "error"
            result.error_message = str(e)
            if 'api_key' in locals():
                self.update_api_key_stats(api_key, error_occurred=True)

            # A quota / rate-limit error (HTTP 429) will NOT succeed on retry within
            # this run, so fail fast instead of waiting ~60s per image.
            err_lower = str(e).lower()
            is_quota = ("resource_exhausted" in err_lower or "429" in err_lower
                        or "quota" in err_lower)
            if is_quota:
                result.error_message = (
                    "Gemini quota exceeded (HTTP 429). This key/model has no available "
                    "quota right now - enable billing on the Google project, or use a key/"
                    "model that has quota. Skipping AI tags for this image."
                )
                logging.error(f"QUOTA: {result.image_file} - {result.error_message}")
                # fall through (do not retry) and save what we have
            elif retry_count < self.max_retries:
                logging.info(f"Retrying {result.image_file} (attempt {retry_count + 1}/{self.max_retries})")
                time.sleep(2 ** retry_count)
                return self.analyze_single_image(image_path, retry_count + 1, force_recache=force_recache, player_names=player_names)
            else:
                logging.error(f"Max retries reached for {result.image_file}")

            # Save whatever we have (quota error, or retries exhausted).
            try:
                with open(image_path, 'rb') as f:
                    image_content = f.read()
                    image_hash = self.get_image_hash(image_content)
                self.save_progress(image_hash, image_path, result)
            except Exception:
                pass

        return result

    # --- rest of class unchanged: list_local_images, save_results, analyze_vocabulary_usage, analyze_batch, log_api_key_usage ---

    def list_local_images(self, folder_path: str) -> List[str]:
        """List all image files in a local folder"""
        image_extensions = {'.jpg', '.jpeg', '.png'}
        files = []
        try:
            for entry in os.scandir(folder_path):
                if entry.is_file() and os.path.splitext(entry.name)[1].lower() in image_extensions:
                    files.append(entry.path)
        except Exception as e:
            logging.error(f"Error listing files: {str(e)}")
            raise
        return files

    def save_results(self, results: List[AnalysisResult], output_dir: Path):
        """Save results with confidence scores"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = output_dir / f"cricket_analysis_{timestamp}.csv"

        output_fields = [
            'image_file',
            'event_type',
            'event_type_confidence',
            'mood',
            'mood_confidence',
            'action',
            'action_confidence',
            'location',
            'location_confidence',
            'jersey_color',
            'apparels_seen',
            'caption',
            'crowd_present',
            'logos_branding'
        ]

        csv_data = []
        for result in results:
            row = {}
            for field in output_fields:
                value = getattr(result, field, None)
                if 'confidence' in field and value is not None:
                    row[field] = f"{value:.2%}"
                else:
                    row[field] = value
            csv_data.append(row)

        df = pd.DataFrame(csv_data)
        df.to_csv(csv_file, index=False, encoding='utf-8')

        json_file = output_dir / f"cricket_analysis_{timestamp}.json"
        json_data = []
        for result in results:
            filtered_result = {k: v for k, v in result.__dict__.items()
                               if k in output_fields}
            json_data.append(filtered_result)

        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        stats_file = output_dir / f"analysis_stats_{timestamp}.json"
        successful_results = [r for r in results if r.status == "completed"]

        confidence_stats = {
            'event_type': [r.event_type_confidence for r in successful_results if r.event_type_confidence > 0],
            'mood': [r.mood_confidence for r in successful_results if r.mood_confidence > 0],
            'action': [r.action_confidence for r in successful_results if r.action_confidence > 0],
            'location': [r.location_confidence for r in successful_results if r.location_confidence > 0]
        }

        stats = {
            'summary': {
                'total_images': len(results),
                'successful': len(successful_results),
                'errors': len([r for r in results if r.status == "error"]),
                'total_tokens': sum(r.total_tokens for r in successful_results),
                'total_processing_time': sum(r.processing_time for r in results),
                'avg_processing_time': sum(r.processing_time for r in results) / len(results) if results else 0,
                'avg_tokens_per_image': sum(r.total_tokens for r in successful_results) / len(successful_results) if successful_results else 0
            },
            'confidence_statistics': {
                field: {
                    'avg': sum(scores) / len(scores) if scores else 0,
                    'min': min(scores) if scores else 0,
                    'max': max(scores) if scores else 0,
                    'above_threshold': sum(1 for s in scores if s >= self.confidence_threshold),
                    'below_threshold': sum(1 for s in scores if s < self.confidence_threshold)
                }
                for field, scores in confidence_stats.items()
            },
            'vocabulary_usage': self.analyze_vocabulary_usage(successful_results),
            'api_key_usage': {key[-6:]: stats for key, stats in self.api_key_stats.items()}
        }

        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2)

        logging.info(f"Results saved to {csv_file}, {json_file}, and {stats_file}")

    def analyze_vocabulary_usage(self, results: List[AnalysisResult]) -> Dict:
        usage_stats = {
            'event_types': {},
            'moods': {},
            'actions': {},
            'locations': {}
        }

        for result in results:
            if result.event_type:
                usage_stats['event_types'][result.event_type] = usage_stats['event_types'].get(result.event_type, 0) + 1
            if result.mood:
                usage_stats['moods'][result.mood] = usage_stats['moods'].get(result.mood, 0) + 1
            if result.action:
                usage_stats['actions'][result.action] = usage_stats['actions'].get(result.action, 0) + 1
            if result.location:
                usage_stats['locations'][result.location] = usage_stats['locations'].get(result.location, 0) + 1

        for category in usage_stats:
            usage_stats[category] = dict(sorted(usage_stats[category].items(), key=lambda x: x[1], reverse=True))

        return usage_stats

    def analyze_batch(self, folder_path: str, output_dir: str = None) -> List[AnalysisResult]:
        output_dir = Path(output_dir or "analysis_results")
        output_dir.mkdir(exist_ok=True)

        try:
            image_files = self.list_local_images(folder_path)
            if not image_files:
                logging.warning("No images found in folder")
                return []

            results = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self.analyze_single_image, file): file
                    for file in image_files
                }

                for future in as_completed(futures):
                    file_path = futures[future]
                    try:
                        results.append(future.result())
                    except Exception as e:
                        logging.error(f"Error processing {file_path}: {str(e)}")
                        results.append(AnalysisResult(
                            image_file=os.path.basename(file_path),
                            file_path=file_path,
                            status="error",
                            error_message=str(e)
                        ))

            self.save_results(results, output_dir)
            return results

        except Exception as e:
            logging.error(f"Batch processing failed: {str(e)}")
            return []

    def log_api_key_usage(self):
        logging.info("\nAPI Key Usage Statistics:")
        for key, stats in self.api_key_stats.items():
            logging.info(f"Key {key[-6:]}:")
            logging.info(f"  Requests: {stats['request_count']}")
            logging.info(f"  Tokens: {stats['token_count']:,}")
            logging.info(f"  Errors: {stats['error_count']}")
            logging.info("-" * 30)

def main():
    print("🏏 Cricket Image Analyzer - Single-call (Analysis + Caption)")
    print("=" * 60)
    print("✓ Uses annotated image if available for complete tagging")
    print("✓ Single LLM call returns all fields + caption")
    print("=" * 60)

    api_keys = input("Enter API keys (comma separated): ").strip().split(',')
    folder_path = input("Enter local folder path containing images: ").strip()
    output_dir = input("Enter output dir (optional): ").strip() or None

    analyzer = CricketImageAnalyzer(
        api_keys=[k.strip() for k in api_keys if k.strip()],
        max_workers=3
    )

    results = analyzer.analyze_batch(folder_path, output_dir)

    print("\n" + "=" * 60)
    print("Analysis Complete!")
    print(f"Processed {len([r for r in results if r.status == 'completed'])}/{len(results)} images")
    print("=" * 60)
    analyzer.log_api_key_usage()

if __name__ == "__main__":
    main()
