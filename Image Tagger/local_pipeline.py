"""
local_pipeline.py
=================
The tagging engine for the LOCAL version.

It reuses your EXISTING, proven pipeline modules:
    - modules.image_processing.extract_exif_details   -> face recognition (player names),
                                                          no. of faces, shot type, camera, date
    - modules.ai_tags.CricketImageAnalyzer            -> Gemini tags (event, mood, action,
                                                          location, jersey colour, caption, ...)
    - modules.jersey_classifier                       -> Match / Practice / Off-field kit

What changed vs. the old cloud version:
    - INPUT  : a local folder you pick (not Google Drive)
    - OUTPUT : tags are written into each image file's metadata (metadata_writer.py)
               AND indexed in a local SQLite database (local_db.py)
    - No MySQL, no uploads, no downloads.
"""

import ssl  # noqa: F401  - must load OpenSSL BEFORE the image libraries below,
#                            otherwise Anaconda's _ssl DLL gets shadowed and HTTPS
#                            (used by the Gemini API) fails with a DLL load error.
import os
import time
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

# HEIC (iPhone) support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

# Formats the AI pipeline can actually "see" (decode to a normal picture).
AI_READABLE = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif", ".avif"}
# RAW formats need special decoding -> we index them but skip AI in this version.
RAW_FORMATS = {".arw", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2"}
VIDEO_FORMATS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
ALL_SUPPORTED = AI_READABLE | RAW_FORMATS | VIDEO_FORMATS


def file_md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def generate_editorial_caption(players, team, tournament, event, action, date_str):
    import datetime
    month_day_upper = ""
    month_day_year = ""
    if date_str:
        try:
            # Usually "YYYY:MM:DD HH:MM:SS" from EXIF
            dt = datetime.datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
            month_day_upper = dt.strftime("%B %d").upper()
            month_day_year = dt.strftime("%B %d, %Y")
        except Exception:
            pass

    def normalize(val):
        if not val or val.lower() in ("unknown", "none", "n/a", "not visible", "others"):
            return ""
        return val.strip()

    p = normalize(players)
    t = normalize(team)
    e = normalize(event)
    a = normalize(action)
    
    if not p:
        p_str = "Players"
    else:
        parts = [x.strip() for x in p.split(",")]
        if len(parts) > 1:
            p_str = ", ".join(parts[:-1]) + " and " + parts[-1]
        else:
            p_str = p

    parts = []
    
    if t:
        parts.append(f"{p_str} of {t}")
    else:
        parts.append(p_str)
            
    if a:
        parts.append(a.lower())
    else:
        parts.append("seen")
        
    if e:
        tourn = normalize(tournament)
        if tourn and tourn.lower() not in e.lower():
            parts.append(f"during the {tourn} {e.lower()}")
        else:
            parts.append(f"during a {e.lower()}")
            
    if month_day_year:
        parts.append(f"on {month_day_year}")

    sentence = " ".join(parts) + "."
    sentence = sentence[0].upper() + sentence[1:]

    if month_day_upper:
        return f"{month_day_upper}: {sentence}"
    return sentence



def clean_player_names(raw):
    """
    The face module returns strings like 'Dhoni, Raina + 1 Unknown'.
    Keep only the real recognised names for clean tags.
    """
    if not raw:
        return ""
    names = []
    for part in str(raw).split(","):
        part = part.split("+")[0].strip()
        if part and "unknown" not in part.lower() and part.lower() != "crowd":
            names.append(part)
    return ", ".join(dict.fromkeys(names))  # de-dupe, keep order


def _clean_text(s):
    """Replace fancy unicode punctuation with plain ASCII so it never shows up as a '?'
    in Windows file properties (em/en dashes, smart quotes, ellipsis, non-breaking space)."""
    if not s:
        return s
    repl = {
        "—": "-", "–": "-", "‒": "-", "―": "-",  # — – ‒ ―  -> -
        "‘": "'", "’": "'", "‚": "'",                  # ' ' ‚ -> '
        "“": '"', "”": '"', "„": '"',                  # " " „ -> "
        "…": "...", " ": " ", "•": "-", "·": "-",  # … nbsp • ·
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def _humanize_names(names):
    """['MS Dhoni'] -> 'MS Dhoni'; ['A','B'] -> 'A and B'; ['A','B','C'] -> 'A, B and C'."""
    names = [n for n in (names or []) if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def match_names(name1, name2):
    """Check if name1 and name2 refer to the same player (e.g. 'MS Dhoni' and 'Mahendra Singh Dhoni')."""
    n1_clean = name1.strip().lower()
    n2_clean = name2.strip().lower()
    
    if n1_clean == n2_clean:
        return True
        
    parts1 = n1_clean.split()
    parts2 = n2_clean.split()
    
    if not parts1 or not parts2:
        return False
        
    # If one name is just a single word (e.g. 'Dhoni'), check if it matches the last name of the other
    if len(parts1) == 1:
        return parts1[0] == parts2[-1]
    if len(parts2) == 1:
        return parts2[0] == parts1[-1]
        
    # Last names must match
    if parts1[-1] != parts2[-1]:
        return False
        
    # Compare first names
    first1 = " ".join(parts1[:-1])
    first2 = " ".join(parts2[:-1])
    
    if first1 == first2:
        return True
        
    # Check if initials match (e.g. 'ms' and 'mahendra singh')
    def get_initial_chars(name_parts):
        return "".join([p[0] for p in name_parts if p])
        
    # Only allow initials matching if one of the first name parts is short (abbreviated)
    is_abbrev1 = any(len(p) <= 2 for p in parts1[:-1])
    is_abbrev2 = any(len(p) <= 2 for p in parts2[:-1])
    
    if is_abbrev1 or is_abbrev2:
        init1 = get_initial_chars(parts1[:-1])
        init2 = get_initial_chars(parts2[:-1])
        if init1 == init2 or init1 == first2.replace(" ", "") or init2 == first1.replace(" ", ""):
            return True
            
    return False


class DummyVideoDB:
    def save_thumbnail(self, url, thumbnail_data, width, height):
        pass
    def save_videos_batch(self, completed):
        pass
    def save_unknown_faces_video_batch(self, unknown_completed):
        pass


def get_raw_preview(path):
    """Return JPEG preview bytes for a RAW file (.arw/.dng/.cr2/...).
    1) fast path: pull the embedded JPEG preview with ExifTool.
    2) fallback: decode the RAW directly with rawpy (handles files with no embedded
       preview, and works even when ExifTool isn't installed)."""
    import subprocess
    import metadata_writer
    if metadata_writer.EXIFTOOL_PATH:
        for tag in ["-PreviewImage", "-JpgFromRaw", "-ThumbnailImage"]:
            try:
                proc = subprocess.run(
                    [metadata_writer.EXIFTOOL_PATH, "-b", tag, path],
                    capture_output=True, timeout=15
                )
                if proc.returncode == 0 and proc.stdout and proc.stdout.startswith(b'\xff\xd8'):
                    return proc.stdout
            except Exception:
                pass
    # Fallback: full RAW decode (rawpy is optional; included in requirements_desktop.txt).
    try:
        import io
        import rawpy
        from PIL import Image
        with rawpy.imread(path) as raw:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return None


class LocalTaggingPipeline:
    def __init__(self, api_keys, db, tournament_name="", max_workers=3,
                 jersey_model_path=None, write_metadata_enabled=True):
        self.db = db
        self.tournament_name = tournament_name
        self.max_workers = max_workers
        self.write_metadata_enabled = write_metadata_enabled

        # Lazy / explicit heavy imports so the server starts instantly and only
        # loads the ML models the first time tagging actually runs.
        from modules.ai_tags import CricketImageAnalyzer
        from modules.jersey_classifier import load_model

        print("[PIPELINE] Loading Gemini analyzer...")
        self.cricket = CricketImageAnalyzer(api_keys=api_keys, max_workers=max_workers)

        # FROZEN: the jersey classifier is always on (was the ENABLE_JERSEY Settings toggle).
        from modules import frozen_config as FROZEN
        self.jersey_enabled = FROZEN.ENABLE_JERSEY
        self.jersey_model = None
        if self.jersey_enabled:
            from modules import paths
            jersey_model_path = jersey_model_path or os.getenv("JERSEY_MODEL_PATH", paths.resource_path("models", "jersey.pth"))
            print(f"[PIPELINE] Loading jersey classifier: {jersey_model_path}")
            try:
                self.jersey_model = load_model(jersey_model_path)
            except Exception as e:
                print(f"[PIPELINE] WARNING: jersey model not loaded ({e}). Apparel will be 'Unknown'.")
        else:
            print("[PIPELINE] Jersey classifier disabled (ENABLE_JERSEY=false).")

        # Progress state (read by the UI)
        self._lock = threading.Lock()
        self.stop_requested = False
        self.reset_progress()

    def stop(self):
        self.stop_requested = True
        self._log("STOP REQUESTED. Cancelling remaining tasks...")

    # ------------------------------------------------------------------
    def reset_progress(self):
        with self._lock:
            self.progress = {
                "running": False, "total": 0, "done": 0, "ok": 0,
                "errors": 0, "skipped": 0, "current": "", "log": [],
                "finished": False, "folder": "",
                "rate": 0.0, "eta_seconds": 0, "elapsed": 0,
            }

    def _log(self, msg):
        print(msg)
        with self._lock:
            self.progress["log"].append(msg)
            self.progress["log"] = self.progress["log"][-300:]  # keep last 300 lines

    def get_progress(self):
        with self._lock:
            return dict(self.progress)

    def ensure_video_processor(self):
        if hasattr(self, "video_processor") and self.video_processor is not None:
            return self.video_processor
        from modules.video_processor import VideoProcessor
        self.video_processor = VideoProcessor(
            api_keys=self.cricket.api_keys,
            db_manager=DummyVideoDB(),
            max_workers=self.max_workers
        )
        return self.video_processor

    # ------------------------------------------------------------------
    def scan_folder(self, folder, recursive=True):
        files = []
        if recursive:
            for root, _, names in os.walk(folder):
                for n in names:
                    if os.path.splitext(n)[1].lower() in ALL_SUPPORTED:
                        files.append(os.path.join(root, n))
        else:
            for n in os.listdir(folder):
                p = os.path.join(folder, n)
                if os.path.isfile(p) and os.path.splitext(n)[1].lower() in ALL_SUPPORTED:
                    files.append(p)
        return sorted(files)

    # ------------------------------------------------------------------
    def tag_folder(self, folder, recursive=True, force=False, disable_ai_tags=False, tournament_context="", team_context=""):
        """Tag every image in a folder. Blocking; run it in a background thread."""
        import metadata_writer

        folder = os.path.abspath(folder)
        self.stop_requested = False
        self.reset_progress()
        with self._lock:
            self.progress["running"] = True
            self.progress["folder"] = folder

        if not os.path.isdir(folder):
            self._log(f"ERROR: folder not found: {folder}")
            with self._lock:
                self.progress["running"] = False
                self.progress["finished"] = True
            return

        self._log(f"Scanning folder: {folder}")
        files = self.scan_folder(folder, recursive)
        self._log(f"Found {len(files)} supported image file(s).")
        self._log(f"Metadata backend: {metadata_writer.backend_name()}")
        with self._lock:
            self.progress["total"] = len(files)

        # Decide which files to tag.
        #   - force (the "Re-tag already-tagged images" box) -> tag everything.
        #   - otherwise we SKIP a file ONLY if it is ALREADY FULLY TAGGED in the
        #     file's own metadata (keywords + caption + the AI fields). Untagged
        #     or PARTIALLY tagged files are processed so the missing tags get
        #     filled in.
        # CRITICAL SAFETY RULE: skipping a file NEVER writes to the database, so
        # existing tags can never be wiped. We only ever INSERT a skipped file's
        # tags if that file is not in the database at all (e.g. tagged elsewhere).
        to_process = []
        already_complete = 0
        for p in files:
            if self.stop_requested:
                break
            if force:
                to_process.append(p)
                continue
            try:
                complete, md = metadata_writer.tag_completeness(p)
            except Exception:
                complete, md = False, {}
            if complete:
                already_complete += 1
                if not self.db.get_existing(p):
                    self._index_existing(p, md, tournament_context=tournament_context)   # insert-only; never overwrites
                with self._lock:
                    self.progress["skipped"] += 1
                    self.progress["done"] += 1
                continue
            to_process.append(p)

        self._log(f"{len(to_process)} file(s) to tag. "
                  f"{already_complete} already fully tagged -> skipped (left untouched).")

        def worker(path):
            if self.stop_requested:
                return None
            return self._process_one(path, metadata_writer, force=force, disable_ai_tags=disable_ai_tags, tournament_context=tournament_context, team_context=team_context)

        proc_start = time.time()
        n_to_process = len(to_process)
        workers = self.max_workers  # FROZEN (set from frozen_config at pipeline construction)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(worker, p): p for p in to_process}
            for fut in as_completed(futures):
                if self.stop_requested:
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break
                path = futures[fut]
                with self._lock:
                    self.progress["current"] = os.path.basename(path)
                try:
                    record = fut.result()
                    if record is None:
                        continue
                    self.db.upsert_image(record)
                    with self._lock:
                        self.progress["done"] += 1
                        if record.get("status") == "completed":
                            self.progress["ok"] += 1
                        else:
                            self.progress["errors"] += 1
                        # live speed + estimated time remaining
                        processed = self.progress["ok"] + self.progress["errors"]
                        elapsed = time.time() - proc_start
                        rate = processed / elapsed if elapsed > 0 else 0
                        self.progress["elapsed"] = int(elapsed)
                        self.progress["rate"] = round(rate, 2)
                        self.progress["eta_seconds"] = int((n_to_process - processed) / rate) if rate > 0 else 0
                    self._log(f"[{self.progress['done']}/{self.progress['total']}] "
                              f"{os.path.basename(path)} -> "
                              f"{record.get('player_names') or 'Unknown'} | "
                              f"{record.get('action') or '-'} | "
                              f"{record.get('event_type') or '-'}")
                except Exception as e:
                    with self._lock:
                        self.progress["done"] += 1
                        self.progress["errors"] += 1
                    self._log(f"ERROR tagging {os.path.basename(path)}: {e}")

        with self._lock:
            self.progress["running"] = False
            self.progress["finished"] = True
            self.progress["current"] = ""
        self._log(f"DONE. Tagged {self.progress['ok']}, "
                  f"errors {self.progress['errors']}, skipped {self.progress['skipped']}.")

    # ------------------------------------------------------------------
    def _index_existing(self, path, md, tournament_context=""):
        """
        A file that ALREADY had tags embedded: don't re-run AI, but add it to the
        search index using the tags already inside it, so it still shows in search.
        Safety: refuse to touch a file that is already in the database (never wipe).
        """
        if self.db.get_existing(path):
            return
        rec = {
            "file_path": path,
            "file_name": os.path.basename(path),
            "folder": os.path.dirname(path),
            "tournament": tournament_context or self.tournament_name,
            "status": "completed",
            "metadata_written": 1,
            "embedded_tags": str(md.get("Tags") or ""),
            "caption": str(md.get("Title") or md.get("Subject") or ""),
            "photographer": str(md.get("Authors") or ""),
        }
        try:
            rec["file_hash"] = file_md5(path)
        except Exception:
            rec["file_hash"] = None
        try:
            with Image.open(path) as im:
                rec["width"], rec["height"] = im.size
        except Exception:
            pass
        self.db.upsert_image(rec)

    # ------------------------------------------------------------------
    def _process_video_file(self, path, force=False, tournament_context="", team_context=""):
        import time
        import os
        import json
        t0 = time.time()
        record = {
            "file_path": path,
            "file_name": os.path.basename(path),
            "folder": os.path.dirname(path),
            "tournament": tournament_context or self.tournament_name,
            "status": "completed",
            "metadata_written": 0,
            "processing_time": 0.0,
        }
        try:
            record["file_hash"] = file_md5(path)
        except Exception:
            record["file_hash"] = None

        try:
            # 1. Get video width/height using OpenCV
            import cv2
            cap = cv2.VideoCapture(path)
            if cap.isOpened():
                record["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                record["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            else:
                record["width"] = record["height"] = None
            cap.release()
        except Exception:
            record["width"] = record["height"] = None

        try:
            # 2. Lazy init video processor
            vp = self.ensure_video_processor()
            vp.log_callback = self._log
            
            # 3. Call process_single_video
            video_info = {
                "file_path": path,
                "file_name": os.path.basename(path),
                "url": path,
                "drive_path": path
            }
            class ShutdownRef:
                def __init__(self, pipe):
                    self.pipe = pipe
                def __bool__(self):
                    return self.pipe.stop_requested

            res = vp.process_single_video(video_info, shutdown_flag_ref=ShutdownRef(self))
            
            if res.get("status") == "error":
                record["status"] = "error"
                record["error_message"] = res.get("error_message") or "Video processing error"
            else:
                record["player_names"] = ", ".join(res.get("player_names") or []) or "Unknown"
                record["no_of_faces"] = res.get("no_of_faces") or 0
                record["event_type"] = res.get("event") or "Others"
                record["mood"] = res.get("mood") or "Neutral"
                record["action"] = res.get("action") or "Standing"
                record["embedded_tags"] = res.get("keywords") or ""
                
                # collate summary + transcription inside caption
                base_caption = generate_editorial_caption(
                    players=record["player_names"],
                    team=team_context,
                    tournament=tournament_context or self.tournament_name,
                    event=record["event_type"],
                    action=record["action"],
                    date_str=res.get("datetime", "")
                )
                summary_text = res.get("video_summary") or ""
                transcribe_text = res.get("transcribe") or ""
                
                full_caption = base_caption
                if summary_text:
                    full_caption += "\n\nSummary:\n" + summary_text
                if transcribe_text:
                    full_caption += "\n\nTranscript:\n" + transcribe_text
                    
                record["caption"] = full_caption
                
                # set datetime/date/time of day
                record["date_time_original"] = res.get("datetime")
                record["date"] = res.get("date")
                record["time_of_day"] = res.get("time_of_day")
                
                # create faces_json list
                faces_list = []
                for name in (res.get("player_names") or []):
                    faces_list.append({
                        "name": name,
                        "conf": 1.0, # Human/pipeline confirmed
                        "status": "confirmed",
                        "bbox": [0, 0, 0, 0]
                    })
                record["faces_json"] = json.dumps(faces_list)
                
        except Exception as e:
            record["status"] = "error"
            record["error_message"] = f"Video tagging failed: {e}"
            self._log(f"  Video tagging failed for {record['file_name']}: {str(e)[:80]}")

        # ---- EMBED TAGS INTO THE VIDEO FILE (parity with photos) ----
        # Videos used to be analysed but never written back to. Now we embed the same
        # tags (players, event, mood, action, caption) into the video's QuickTime/XMP
        # metadata so they travel with the file, just like photos.
        if record.get("status") != "error" and self.write_metadata_enabled:
            try:
                import metadata_writer as _mw
                res_md = _mw.write_metadata(path, record)
                record["metadata_written"] = 1 if res_md.get("ok") else 0
                self._log(f"  Video tags {'embedded' if res_md.get('ok') else 'NOT embedded'} "
                          f"for {record['file_name']}: {res_md.get('note', '')[:80]}")
            except Exception as e:
                self._log(f"  Video metadata write failed for {record['file_name']}: {str(e)[:80]}")

        record["processing_time"] = round(time.time() - t0, 2)
        return record

    def _process_one(self, path, metadata_writer, force=False, disable_ai_tags=False, tournament_context="", team_context=""):
        if self.stop_requested:
            return None
        from modules.utils import safe_extract_exif_with_retries

        ext = os.path.splitext(path)[1].lower()
        t0 = time.time()
        
        # Route video files to the video tagging processor
        if ext in VIDEO_FORMATS:
            return self._process_video_file(path, force=force, tournament_context=tournament_context, team_context=team_context)

        record = {
            "file_path": path,
            "file_name": os.path.basename(path),
            "folder": os.path.dirname(path),
            "tournament": tournament_context or self.tournament_name,
            "status": "completed",
            "metadata_written": 0,
        }
        try:
            record["file_hash"] = file_md5(path)
        except Exception:
            record["file_hash"] = None

        # RAW formats: extract preview bytes using ExifTool to run pipeline on them
        is_raw = ext in RAW_FORMATS
        preview_temp_path = None
        if is_raw:
            preview_bytes = get_raw_preview(path)
            if not preview_bytes:
                record["status"] = "error"
                record["error_message"] = "RAW format: ExifTool could not extract JPEG preview. Convert to JPEG to AI-tag."
                record["processing_time"] = round(time.time() - t0, 2)
                return record
            
            # Save preview bytes to a temp file in the writable scratch directory
            from modules import paths
            scratch_dir = os.path.join(paths.cache_dir(), "scratch")
            os.makedirs(scratch_dir, exist_ok=True)
            preview_temp_path = os.path.join(scratch_dir, f"temp_preview_{record['file_hash'] or 'raw'}.jpg")
            try:
                from PIL import Image
                import io
                im = Image.open(io.BytesIO(preview_bytes))
                
                # Fetch original orientation from ExifTool and rotate the image so it is straight
                orientation = metadata_writer.get_original_orientation(path)
                im = metadata_writer.rotate_image_by_orientation(im, orientation)
                
                im.save(preview_temp_path, "JPEG", quality=90)
            except Exception as e:
                record["status"] = "error"
                record["error_message"] = f"RAW format: failed to save temp preview image ({e})."
                record["processing_time"] = round(time.time() - t0, 2)
                return record

        try:
            # ---- image size ----
            try:
                with Image.open(preview_temp_path if is_raw else path) as im:
                    record["width"], record["height"] = im.size
            except Exception:
                record["width"] = record["height"] = None

            # ---- FACE RECOGNITION + EXIF (player names, faces, shot type, camera) ----
            try:
                exif = safe_extract_exif_with_retries(record["file_name"], preview_temp_path if is_raw else path, max_retries=3) or {}
            except Exception as e:
                exif = {}
                self._log(f"  face/EXIF failed for {record['file_name']}: {str(e)[:80]}")

            if is_raw:
                try:
                    raw_exif = metadata_writer.read_raw_exif_tags(path)
                    for k, v in raw_exif.items():
                        if v:
                            exif[k] = v
                    dto = exif.get("DateTimeOriginal")
                    if dto:
                        try:
                            exif["Date"] = dto.split()[0].replace(":", "/")
                            from modules.image_processing import categorize_time_of_day
                            exif["TimeOfDay"] = categorize_time_of_day(dto)
                        except Exception:
                            pass
                except Exception as e:
                    self._log(f"  Failed to read raw EXIF for {record['file_name']}: {e}")

            raw_players = exif.get("Player Name", "")
            record["player_names"] = clean_player_names(raw_players) or "Unknown"
            record["no_of_faces"] = exif.get("NoOfFaces", 0)
            record["shot_type"] = exif.get("Shot Type")
            record["focus"] = exif.get("Focus")
            record["photographer"] = exif.get("Photographer")
            record["copyright"] = exif.get("Copyright")
            record["camera_make"] = exif.get("Camera Make")
            record["camera_model"] = exif.get("Camera Model")
            record["date_time_original"] = exif.get("DateTimeOriginal")
            record["date"] = exif.get("Date")
            record["time_of_day"] = exif.get("TimeOfDay")

            # ---- SERIALIZE FACES TO JSON FOR UI ----
            # A face is auto-confirmed only when we're sure of the FACE. Unknown faces and
            # low-confidence matches go to the review queue (boxed) for a human yes/no.
            from modules import frozen_config as FROZEN
            review_conf = FROZEN.FACE_REVIEW_CONFIDENCE  # FROZEN ("Auto-confirm confidence")
            faces_list = []
            raw_faces = exif.get("faces") or []
            for face in raw_faces:
                x1, y1, x2, y2, name, conf = face
                conf01 = round(conf / 100.0, 2)
                if name == "Unknown":
                    status = "review"
                elif conf01 < review_conf:
                    status = "review"   # identified, but not confident enough to auto-accept
                else:
                    status = "confirmed"
                faces_list.append({
                    "name": name,
                    "conf": conf01,
                    "status": status,
                    "bbox": [int(x1), int(y1), int(x2), int(y2)]
                })
            import json
            record["faces_json"] = json.dumps(faces_list)

            # ---- GEMINI SCENE TAGS ----
            if disable_ai_tags:
                self._log(f"  Skipping AI tagging for {record['file_name']} (Disabled by user)")
            else:
                try:
                    ai = self.cricket.analyze_single_image(preview_temp_path if is_raw else path, force_recache=force, player_names=record["player_names"])
                    record["event_type"] = ai.event_type
                    record["mood"] = ai.mood
                    record["action"] = ai.action
                    record["location"] = ai.location
                    record["jersey_color"] = ai.jersey_color
                    record["apparels_seen"] = ai.apparels_seen
                    record["crowd_present"] = ai.crowd_present
                    record["caption"] = ai.caption
                    record["logos_branding"] = ai.logos_branding
                    record["input_tokens"] = ai.input_tokens
                    record["output_tokens"] = ai.output_tokens
                    record["total_tokens"] = ai.total_tokens
                    record["api_key_used"] = (ai.api_key_used or "")[-6:]
                    if ai.status == "error":
                        record["status"] = "error"
                        record["error_message"] = ai.error_message
                except Exception as e:
                    record["status"] = "error"
                    record["error_message"] = f"Gemini failed: {e}"
                    self._log(f"  Gemini failed for {record['file_name']}: {str(e)[:80]}")

            # ---- PLAYER NAMES: our face recognition is the SINGLE source of truth ----
            # We deliberately do NOT let Gemini add or drop player names (the user does not
            # trust Flash to name people). Gemini writes the caption name-free; we inject our
            # OWN recognised names into the caption further below.
            try:
                from modules.config import label_encoder
                known_players = list(label_encoder.classes_)
            except Exception:
                known_players = []

            existing = []
            if record.get("player_names") and record["player_names"] != "Unknown":
                existing = [p.strip() for p in record["player_names"].split(",") if p.strip()]
            # Keep only names the model actually knows; de-dupe, preserve order.
            confirmed = [p for p in dict.fromkeys(existing) if (not known_players) or p in known_players]
            record["player_names"] = ", ".join(confirmed) if confirmed else "Unknown"

            # ---- SYNC FACES_JSON WITH FINAL PLAYER NAMES ----
            final_players = [p.strip() for p in record.get("player_names", "").split(",") if p.strip() and p.strip() != "Unknown"]
            faces_list = []
            if record.get("faces_json"):
                try:
                    faces_list = json.loads(record["faces_json"])
                except Exception:
                    pass
            
            # Mark faces confirmed only when they're a final player AND confident enough;
            # otherwise they go to review (the user confirms low-confidence ones by hand).
            for face in faces_list:
                if face["name"] in final_players:
                    face["status"] = "confirmed" if face.get("conf", 0) >= review_conf else "review"
                elif face["status"] == "confirmed":
                    face["name"] = "Unknown"
                    face["status"] = "review"

            # Add final players not in faces_list as confirmed
            face_names = {f["name"] for f in faces_list if f["name"] != "Unknown"}
            for p in final_players:
                if p not in face_names:
                    faces_list.append({
                        "name": p,
                        "conf": 1.0,
                        "status": "confirmed",
                        "bbox": [0, 0, 0, 0]
                    })
            record["faces_json"] = json.dumps(faces_list)

            # ---- CAPTION: Build Editorial String ----
            tourn_ctx = tournament_context or self.tournament_name
            record["caption"] = generate_editorial_caption(
                players=record.get("player_names", ""),
                team=team_context,
                tournament=tourn_ctx,
                event=record.get("event_type", ""),
                action=record.get("action", ""),
                date_str=record.get("date_time_original", "")
            )
            record["caption"] = _clean_text(record["caption"])

            # ---- JERSEY CLASSIFIER (apparel type) ----
            record["apparel"] = "Unknown"
            # 1. Use Gemini apparel classification if available
            gemini_apparel = getattr(ai, "apparel", None) if 'ai' in locals() else None
            if gemini_apparel and gemini_apparel != "Unknown":
                record["apparel"] = gemini_apparel

            # 2. Fallback to ResNet model if Gemini did not specify
            if self.jersey_enabled and record["apparel"] in ("Unknown", "", None) and self.jersey_model is not None:
                try:
                    from modules.jersey_classifier import predict_jersey_type
                    label, _conf = predict_jersey_type(preview_temp_path if is_raw else path, self.jersey_model)
                    record["apparel"] = label
                except Exception:
                    pass

            # 3. Apparel decision — user rule based on the DOMINANT jersey colour, and the
            #    field is NEVER left empty:
            #      dominant yellow -> Match Jersey
            #      dominant blue   -> Practice Jersey
            #    CSK kits list several colours (e.g. "Yellow, Blue, Red"), so we look at the
            #    FIRST/dominant colour rather than "any yellow" (which mislabelled blue kits).
            color_tokens = [c.strip().lower() for c in (record.get("jersey_color") or "").split(",") if c.strip()]
            primary = color_tokens[0] if color_tokens else ""
            colors_all = ", ".join(color_tokens)
            gemini_apparel = (record.get("apparel") or "").strip()
            ev = (record.get("event_type") or "").lower()

            if "yellow" in primary or "gold" in primary:
                record["apparel"] = "Match Jersey"
            elif "blue" in primary or "navy" in primary:
                record["apparel"] = "Practice Jersey"
            elif gemini_apparel and gemini_apparel.lower() not in ("unknown", "none", ""):
                record["apparel"] = gemini_apparel            # keep Off Field kit / Casual Attire / etc.
            elif "yellow" in colors_all or "gold" in colors_all:
                record["apparel"] = "Match Jersey"
            elif "blue" in colors_all or "navy" in colors_all:
                record["apparel"] = "Practice Jersey"
            else:
                # last resort so the apparel field is never empty
                record["apparel"] = "Practice Jersey" if ev in ("practice", "training") else "Match Jersey"
            self._log(f"  [Apparel] {record['apparel']} (jersey colours: {colors_all or 'n/a'})")

            # ---- WRITE TAGS INTO THE IMAGE FILE ----
            if self.write_metadata_enabled:
                res = metadata_writer.write_metadata(path, record)
                record["metadata_written"] = 1 if res["ok"] else 0
                if not res["ok"]:
                    self._log(f"  metadata not embedded ({record['file_name']}): {res['note']}")

        finally:
            if preview_temp_path and os.path.exists(preview_temp_path):
                try:
                    os.remove(preview_temp_path)
                except Exception:
                    pass

        record["processing_time"] = round(time.time() - t0, 2)
        return record

