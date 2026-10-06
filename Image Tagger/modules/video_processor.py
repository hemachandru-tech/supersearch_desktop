# modules/video_processor.py
"""
Video Processor Module
Complete pipeline for processing cricket videos:
1. Extract frames using FFmpeg
2. Detect and recognize faces in frames (with rotation support)
3. AI analysis of frames with Gemini
4. Generate final summary
5. Save to database with thumbnail

UPDATED: Enhanced face detection with rotation, orientation, and improved crowd detection
"""

import os
import cv2
import time
import shutil
import subprocess
import glob
import re
import numpy as np
from google import genai
from google.genai import types
from PIL import Image
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional

from modules.prompts import get_frame_analysis_prompt, get_final_summary_prompt
from modules.config import get_face_app, get_classifier, get_label_encoder
from modules.image_processing import recognize_face
from modules import frozen_config as FROZEN
from modules.utils import format_seconds, is_unknown_player, limit_words, limit_chars

try:
    from faster_whisper import WhisperModel as _WhisperModel
except Exception:
    _WhisperModel = None

# Try to use imageio-ffmpeg for bundled ffmpeg binary
try:
    import imageio_ffmpeg as iio_ffmpeg
    FFMPEG_EXE = iio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = shutil.which('ffmpeg')


class VideoProcessor:
    """Complete video processing pipeline with enhanced face detection"""
    
    # Recognition constants. These deliberately mirror the image path so a face is
    # judged the same way whether it arrives as a photo or as a video frame — they are
    # read from frozen_config rather than duplicated here. The old hardcoded values
    # (98px faces, 99.99% SVC probability) rejected almost every face in a video frame.
    MIN_FACE_SIZE = FROZEN.FACE_MIN_SIZE
    SHARPNESS_THRESHOLD = FROZEN.FACE_MIN_SHARPNESS
    MAX_FACES_LIMIT = FROZEN.FACE_MAX_FACES
    COSINE_THRESHOLD = FROZEN.FACE_COSINE_THRESHOLD
    PRIMARY_ONLY = FROZEN.FACE_PRIMARY_ONLY
    PRIMARY_AREA_RATIO = FROZEN.FACE_PRIMARY_AREA_RATIO

    # Temporal consensus: a player must appear in at least this many frames (and this
    # fraction of all extracted frames) before they are tagged on the video. Without it
    # a single mis-identified frame put a wrong name on the whole clip.
    PLAYER_MIN_FRAMES = FROZEN.VIDEO_PLAYER_MIN_FRAMES
    PLAYER_MIN_FRAMES_RATIO = FROZEN.VIDEO_PLAYER_MIN_FRAMES_RATIO
    TRANSCRIBE_MAX_CHARS = int(os.getenv('TRANSCRIBE_MAX_CHARS', '10000'))  # Max transcript length for DB
    
    @staticmethod
    def _determine_time_of_day(datetime_str: Optional[str]) -> Optional[str]:
        """Convert datetime string (YYYY-mm-dd HH:MM:SS) to part-of-day label."""
        if not datetime_str:
            return None
        try:
            dt_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

        hour = dt_obj.hour
        if 6 <= hour < 12:
            return "Morning"
        if 12 <= hour < 16:
            return "Afternoon"
        if 16 <= hour < 19:
            return "Evening"
        return "Night"

    def __init__(self, api_keys: List[str], db_manager, max_workers: int = 4):
        """
        Initialize video processor
        
        Args:
            api_keys: List of Gemini API keys
            db_manager: Database manager instance
            max_workers: Number of parallel workers for AI analysis
        """
        self.api_keys = api_keys
        self.db_manager = db_manager
        self.max_workers = max_workers
        self.current_api_key_index = 0
        self.log_callback = None
        from modules import frozen_config as FROZEN
        self.model = FROZEN.GEMINI_MODEL  # FROZEN (was GEMINI_MODEL env / Settings dropdown)
        
        # Gemini clients (one per API key)
        self.clients = {key: genai.Client(api_key=key) for key in (api_keys or [])}
        
        # Temporary directories (writable cache dir; App Support/cache when packaged)
        from modules import paths
        self.frames_dir = os.path.join(paths.cache_dir(), "temp_frames")
        self.annotated_dir = os.path.join(paths.cache_dir(), "temp_annotated")
        os.makedirs(self.frames_dir, exist_ok=True)
        os.makedirs(self.annotated_dir, exist_ok=True)
        
        # Processing settings
        self.fps_extract = float(os.getenv('VIDEO_FPS_EXTRACT', '1.0'))
        self.large_video_threshold_gb = float(os.getenv('LARGE_VIDEO_THRESHOLD_GB', '10'))
        self.large_video_interval_seconds = float(os.getenv('LARGE_VIDEO_INTERVAL_SECONDS', '60'))
        self._whisper_model = None
        self._whisper_model_name = os.getenv('WHISPER_MODEL', 'large-v3')
        # Audio transcription (faster-whisper / CTranslate2) is OFF by default — its native
        # int8 CPU inference segfaults on some machines. Set ENABLE_TRANSCRIBE=true to re-enable.
        self.enable_transcribe = os.getenv('ENABLE_TRANSCRIBE', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

        self.log(f"\n✓ Video processor initialized")
        self.log(f"  Workers: {max_workers}")
        self.log(f"  FPS extraction: {self.fps_extract}")
        self.log(f"  API keys: {len(api_keys)}")
        self.log(f"  Min face size: {self.MIN_FACE_SIZE}px")
        self.log(f"  Crowd threshold: {self.MAX_FACES_LIMIT} faces")
        self.log(f"  Audio transcription: {'ENABLED' if self.enable_transcribe else 'DISABLED (ENABLE_TRANSCRIBE=false)'}")
    
    def log(self, *args, **kwargs):
        msg = " ".join(map(str, args))
        print(msg)
        if hasattr(self, 'log_callback') and self.log_callback:
            self.log_callback(msg)

    def get_next_api_key(self) -> str:
        """Rotate through API keys"""
        key = self.api_keys[self.current_api_key_index]
        self.current_api_key_index = (self.current_api_key_index + 1) % len(self.api_keys)
        return key
    
    def cleanup_temp_folders(self):
        """Clean up temporary directories"""
        try:
            if os.path.exists(self.frames_dir):
                shutil.rmtree(self.frames_dir)
                os.makedirs(self.frames_dir, exist_ok=True)
            if os.path.exists(self.annotated_dir):
                shutil.rmtree(self.annotated_dir)
                os.makedirs(self.annotated_dir, exist_ok=True)
        except Exception as e:
            self.log(f"⚠️ Cleanup warning: {e}")
    
    def get_video_duration(self, video_path: str) -> float:
        """Get video duration in seconds using ffmpeg"""
        if not FFMPEG_EXE:
            return 0
        try:
            cmd = [FFMPEG_EXE, '-i', video_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            stderr = result.stderr or result.stdout or ""
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = float(match.group(3))
                return hours * 3600 + minutes * 60 + seconds
            return 0
        except Exception:
            return 0

    def _determine_effective_fps(self, video_path: str) -> Tuple[float, Optional[Dict[str, float]]]:
        """
        Decide fps based on file size.
        - Files larger than threshold use 1 frame every `large_video_interval_seconds`.
        - Smaller files use configured fps.
        """
        try:
            size_bytes = os.path.getsize(video_path)
        except OSError:
            size_bytes = 0

        size_gb = size_bytes / (1024 ** 3)
        base_fps = self.fps_extract if self.fps_extract > 0 else 1.0

        if size_gb > self.large_video_threshold_gb:
            interval = max(1.0, self.large_video_interval_seconds)
            adjusted_fps = max(1.0 / interval, 0.0001)
            return adjusted_fps, {"size_gb": size_gb, "interval": interval}

        return base_fps, None
    
    def extract_frames_ffmpeg(self, video_path: str) -> List[Dict]:
        """Extract frames from video using FFmpeg"""
        if not FFMPEG_EXE:
            raise RuntimeError("FFmpeg not found! Install ffmpeg or imageio-ffmpeg package.")
        
        self.log(f"\n→ Extracting frames from video...")
        
        # Clean frames directory
        for f in glob.glob(os.path.join(self.frames_dir, "*.jpg")):
            try:
                os.remove(f)
            except:
                pass
        
        duration = self.get_video_duration(video_path)
        effective_fps, large_info = self._determine_effective_fps(video_path)
        expected_frames = int(duration * effective_fps) if duration > 0 else "unknown"
        self.log(f"  Duration: {duration:.1f}s")
        if large_info:
            self.log(
                f"  Large file detected ({large_info['size_gb']:.2f} GB) → sampling every "
                f"{int(large_info['interval'])}s ({effective_fps:.4f} fps)"
            )
        else:
            self.log(f"  FPS extraction: {effective_fps:.2f} fps")
        self.log(f"  Expected frames: ~{expected_frames}")
        
        output_pattern = os.path.join(self.frames_dir, "frame_%04d.jpg")
        
        command = [
            FFMPEG_EXE,
            '-i', video_path,
            '-vf', f'fps={effective_fps}',
            '-q:v', '5',
            '-threads', '0',
            '-y',
            output_pattern
        ]
        
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3000)
            
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error: {result.stderr[:200]}")
            
            frame_files = sorted(glob.glob(os.path.join(self.frames_dir, "frame_*.jpg")))
            
            if not frame_files:
                raise RuntimeError("No frames extracted")
            
            frame_paths = []
            for idx, frame_path in enumerate(frame_files):
                timestamp_sec = idx / self.fps_extract if self.fps_extract > 0 else idx
                frame_paths.append({
                    'path': frame_path,
                    'second': int(timestamp_sec),
                    'frame_num': int(idx)
                })
            
            self.log(f"✓ Extracted {len(frame_paths)} frames\n")
            return frame_paths
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("FFmpeg timed out")
        except Exception as e:
            raise RuntimeError(f"FFmpeg error: {str(e)}")
    
    def compute_sharpness(self, face_img: np.ndarray) -> float:
        """Compute sharpness score using Laplacian variance"""
        if face_img is None or face_img.size == 0:
            return 0
        gray = cv2.cvtColor(face_img, cv2.COLOR_RGB2GRAY)
        return cv2.Laplacian(gray, cv2.CV_64F).var()
    
    def detect_orientation(self, image_shape: Tuple[int, int]) -> str:
        """
        Detect image orientation based on dimensions
        Returns: 'Landscape', 'Portrait', or 'Square'
        """
        height, width = image_shape[:2]
        aspect_ratio = width / height
        
        if 0.95 <= aspect_ratio <= 1.05:
            return "Square"
        elif aspect_ratio > 1.05:
            return "Landscape"
        else:
            return "Portrait"
    
    def detect_faces_with_rotation(self, image_rgb: np.ndarray, orientation: str) -> Tuple[List, int]:
        """
        Detect faces with multiple rotation attempts if needed
        Ensures faces are found regardless of orientation
        Returns: (faces, rotation_angle)
        """
        app = get_face_app()
        # Try 1: Original orientation
        faces = app.get(image_rgb)
        if len(faces) > 0:
            return faces, 0
        
        # Try 2: Rotate 90° clockwise
        rotated_90 = cv2.rotate(image_rgb, cv2.ROTATE_90_CLOCKWISE)
        faces = app.get(rotated_90)
        if len(faces) > 0:
            return faces, 90
        
        # Try 3: Rotate 90° counter-clockwise
        rotated_270 = cv2.rotate(image_rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
        faces = app.get(rotated_270)
        if len(faces) > 0:
            return faces, 270
        
        # Try 4: Rotate 180°
        rotated_180 = cv2.rotate(image_rgb, cv2.ROTATE_180)
        faces = app.get(rotated_180)
        if len(faces) > 0:
            return faces, 180
        
        return [], 0
    
    def adjust_bbox_for_rotation(self, bbox: List[int], rotation_angle: int, image_shape: Tuple[int, int]) -> List[int]:
        """Adjust bounding box coordinates based on rotation angle"""
        x1, y1, x2, y2 = bbox
        height, width = image_shape[:2]
        
        if rotation_angle == 0:
            return [x1, y1, x2, y2]
        
        elif rotation_angle == 90:
            new_x1 = y1
            new_y1 = width - x2
            new_x2 = y2
            new_y2 = width - x1
            return [new_x1, new_y1, new_x2, new_y2]
        
        elif rotation_angle == 270:
            new_x1 = height - y2
            new_y1 = x1
            new_x2 = height - y1
            new_y2 = x2
            return [new_x1, new_y1, new_x2, new_y2]
        
        elif rotation_angle == 180:
            new_x1 = width - x2
            new_y1 = height - y2
            new_x2 = width - x1
            new_y2 = height - y1
            return [new_x1, new_y1, new_x2, new_y2]
        
        return [x1, y1, x2, y2]
    
    def detect_faces_in_frame(self, frame_path: str) -> Tuple[List[Dict], Optional[str], Optional[str], str, int]:
        """
        Enhanced face detection with rotation support and crowd detection.
        Player-name logic matches the tagging code (SVM prediction + confidence gate).
        Returns: (detections, annotated_path, skip_reason, orientation, rotation_applied)
        """
        try:
            # Read frame
            frame = cv2.imread(frame_path, cv2.IMREAD_COLOR)
            if frame is None:
                return [], None, None, "Unknown", 0
            
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Detect orientation
            orientation = self.detect_orientation(frame_rgb.shape)
            
            # Use rotation-aware face detection
            faces, rotation_angle = self.detect_faces_with_rotation(frame_rgb, orientation)
            
            # Check if too many faces (crowded scene)
            if len(faces) > self.MAX_FACES_LIMIT:
                skip_reason = f"crowd_detected_{len(faces)}_faces"
                return [], None, skip_reason, orientation, rotation_angle
            
            if not faces:
                return [], None, None, orientation, rotation_angle
            
            detections = []
            
            clf = get_classifier()
            label_encoder = get_label_encoder()
            
            # ---- PASS 1: keep the faces worth identifying (size + sharpness) ----
            candidates = []
            for face in faces:
                x1, y1, x2, y2 = face.bbox.astype(int)
                
                # Adjust bbox if rotation was applied
                if rotation_angle != 0:
                    if rotation_angle in [90, 270]:
                        rotated_shape = (frame_rgb.shape[1], frame_rgb.shape[0], frame_rgb.shape[2])
                    else:
                        rotated_shape = frame_rgb.shape
                    
                    x1, y1, x2, y2 = self.adjust_bbox_for_rotation([x1, y1, x2, y2], rotation_angle, rotated_shape)
                
                # Ensure valid crop
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(frame_rgb.shape[1], x2), min(frame_rgb.shape[0], y2)
                
                if x2 <= x1 or y2 <= y1:
                    continue
                
                # Check minimum face size
                face_width = x2 - x1
                face_height = y2 - y1
                
                if face_width < self.MIN_FACE_SIZE or face_height < self.MIN_FACE_SIZE:
                    continue
                
                # Extract face crop
                face_crop = frame_rgb[y1:y2, x1:x2]
                
                # Check sharpness
                sharpness = self.compute_sharpness(face_crop)
                if sharpness < self.SHARPNESS_THRESHOLD:
                    continue
                
                candidates.append({
                    'box': (int(x1), int(y1), int(x2), int(y2)),
                    'area': face_width * face_height,
                    'embedding': face.embedding,
                })
            
            # ---- Focus on the MAIN SUBJECT(s): drop small background faces ----
            # Crowd shots in a video otherwise contribute a long tail of tiny, badly-lit
            # faces, and those are exactly the ones that get misidentified.
            if self.PRIMARY_ONLY and candidates:
                max_area = max(c['area'] for c in candidates)
                candidates = [c for c in candidates
                              if c['area'] >= self.PRIMARY_AREA_RATIO * max_area]
            
            # ---- PASS 2: identify each kept face ----
            # Uses the same open-set recognition as the image path (closed-set SVM pick
            # vs. cosine-nearest player, whichever the facial features support better,
            # gated on cosine similarity to that player's reference templates). A face
            # that resembles no known player comes back "Unknown" and is dropped, rather
            # than being forced onto the nearest class as the old SVM-only code did.
            for c in candidates:
                x1, y1, x2, y2 = c['box']
                name, confidence = recognize_face(
                    c['embedding'], clf, label_encoder, self.COSINE_THRESHOLD
                )
                
                if not name or name == "Unknown":
                    continue
                
                detections.append({
                    'name': name,
                    'confidence': float(confidence or 0.0),
                    'bbox': [int(x1), int(y1), int(x2), int(y2)]
                })
            
            # Create annotated frame if faces detected
            annotated_path = None
            skip_reason = None
            
            if detections:
                for det in detections:
                    x1, y1, x2, y2 = det['bbox']
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    label = f"{det['name']} {det['confidence']:.1f}%"
                    cv2.putText(frame, label, (x1, y1-10), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)
                
                frame_name = os.path.basename(frame_path)
                annotated_path = os.path.join(self.annotated_dir, f"annotated_{frame_name}")
                cv2.imwrite(annotated_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            
            return detections, annotated_path, skip_reason, orientation, rotation_angle
            
        except Exception as e:
            self.log(f"  ⚠️ Frame detection error: {str(e)}")
            return [], None, None, "Unknown", 0
    
    def detect_faces_sequential(self, frame_paths: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Detect faces in all frames sequentially with enhanced detection"""
        self.log(f"→ Detecting faces in {len(frame_paths)} frames...")
        
        all_results = []
        frames_with_players = []
        crowd_frames = 0
        
        for idx, frame_info in enumerate(frame_paths):
            if (idx + 1) % 10 == 0 or idx == len(frame_paths) - 1:
                self.log(f"  Progress: {idx + 1}/{len(frame_paths)} frames")
            
            detections, annotated_path, skip_reason, orientation, rotation = self.detect_faces_in_frame(frame_info['path'])
            
            # Track crowd detections
            if skip_reason and skip_reason.startswith("crowd_detected"):
                crowd_frames += 1
            
            result = {
                'frame_info': frame_info,
                'detections': detections,
                'annotated_path': annotated_path,
                'skip_reason': skip_reason,
                'orientation': orientation,
                'rotation_applied': rotation
            }
            
            all_results.append(result)
            
            if detections:
                frames_with_players.append(result)
        
        self.log(f"✓ Detection complete: {len(frames_with_players)}/{len(frame_paths)} frames with players")
        if crowd_frames > 0:
            self.log(f"  🔍 {crowd_frames} crowd frames detected (>{self.MAX_FACES_LIMIT} faces)")
        self.log()
        
        return all_results, frames_with_players
    
    def analyze_frame_llm(self, frame_data: Dict, use_original_frame: bool = False) -> Optional[Dict]:
        """
        Analyze a single frame with Gemini AI
        Args:
            frame_data: Frame data with detections and frame_info
            use_original_frame: If True, use original frame path instead of annotated path
        """
        try:
            # Get player names (can be empty list)
            players = [d['name'] for d in frame_data.get('detections', [])]
            
            # Determine which image to use
            if use_original_frame or not frame_data.get('annotated_path'):
                # Use original frame if no annotated version or explicitly requested
                image_path = frame_data['frame_info']['path']
            else:
                # Use annotated frame if available
                image_path = frame_data['annotated_path']
            
            # Load image
            try:
                image = Image.open(image_path)
            except Exception as e:
                self.log(f"  ⚠️ Could not load image {image_path}: {str(e)}")
                return None
            
            # Generate prompt (handles empty players list)
            prompt = get_frame_analysis_prompt(players)
            
            api_key = self.get_next_api_key()
            client = self.clients.get(api_key)
            if not client:
                raise RuntimeError("No Gemini client for API key")
            response = client.models.generate_content(
                model=self.model,
                contents=[prompt, image],
                config=types.GenerateContentConfig(),
            )
            
            return {
                'frame_info': frame_data['frame_info'],
                'players': players,
                'description': response.text if response and response.text else "No response"
            }
        
        except Exception as e:
            self.log(f"  ⚠️ LLM analysis error: {str(e)}")
            return {
                'frame_info': frame_data['frame_info'],
                'players': [d['name'] for d in frame_data.get('detections', [])],
                'description': f"Error: {str(e)}"
            }
    
    def _frames_one_per_player_set(self, frame_list: List[Dict]) -> List[Dict]:
        """
        Reduce frames to one representative per unique set of player names (to control LLM calls).
        Same players in multiple frames → send 1 frame; when another player joins → send that frame too.
        """
        if not frame_list:
            return []
        seen = {}
        for frame in frame_list:
            names = tuple(sorted(d['name'] for d in frame.get('detections', [])))
            if names not in seen:
                seen[names] = frame
        return list(seen.values())
    
    def parallel_llm_analysis(self, frames_to_analyze: List[Dict], include_no_players: bool = False) -> List[Dict]:
        """
        Analyze frames in parallel using ThreadPoolExecutor
        Args:
            frames_to_analyze: List of frame data to analyze
            include_no_players: If True, analyze frames even without players
        """
        if not frames_to_analyze:
            return []
        
        # Reduce to one frame per unique player set to control LLM calls
        reduced = self._frames_one_per_player_set(frames_to_analyze)
        if len(reduced) < len(frames_to_analyze):
            self.log(f"  LLM: sending {len(reduced)} frame(s) (1 per unique player set, was {len(frames_to_analyze)} frames)")
        
        self.log(f"→ Analyzing {len(reduced)} frames with Gemini AI...")
        self.log(f"  Using {self.max_workers} parallel workers")
        if include_no_players:
            self.log(f"  Including frames without players")
        
        analyses = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for frame in reduced:
                # Use original frame if no players detected; otherwise use annotated (bbox) image only
                use_original = include_no_players and not frame.get('detections')
                futures.append(executor.submit(self.analyze_frame_llm, frame, use_original))
            
            completed = 0
            total = len(futures)
            
            for future in as_completed(futures):
                completed += 1
                if completed % 5 == 0 or completed == total:
                    self.log(f"  Progress: {completed}/{total} frames")
                
                try:
                    result = future.result(timeout=30)
                    if result:
                        analyses.append(result)
                except Exception as e:
                    self.log(f"  ⚠️ LLM future error: {str(e)}")
        
        self.log(f"✓ AI analysis complete: {len(analyses)} descriptions\n")
        
        return analyses
    
    @staticmethod
    def _clean_caption(text: str, max_words: int = 15) -> str:
        """Reduce a model section to one plain caption of at most `max_words` words.

        Keeps the first non-empty line (the model often lists alternatives), strips
        bullet markers, markdown emphasis and wrapping quotes, then truncates.
        """
        if not text:
            return ""
        line = next((l.strip() for l in str(text).splitlines() if l.strip()), "")
        line = re.sub(r"^[-*\u2022]\s*", "", line)      # bullet marker
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)     # **bold**
        line = line.strip().strip('"').strip("'").strip()
        line = limit_words(line, max_words).rstrip(" ,;:-")
        return line

    def parse_summary_response(self, summary_text: str) -> Dict[str, str]:
        """Parse the structured summary response from Gemini"""
        result = {
            'caption': '',
            'video_summary': '',
            'activities': '',
            'keywords': ''
        }
        
        try:
            lines = summary_text.split('\n')
            current_section = None
            section_content = []
            
            for line in lines:
                line = line.strip()
                
                # Check if line is a section header
                if line.startswith('**PRIMARY TAG:**'):
                    if current_section and section_content:
                        result[current_section] = '\n'.join(section_content).strip()
                    current_section = 'caption'
                    section_content = []
                    content_on_line = line.replace('**PRIMARY TAG:**', '').strip()
                    if content_on_line:
                        section_content.append(content_on_line)
                        
                elif line.startswith('**VIDEO SUMMARY:**'):
                    if current_section and section_content:
                        result[current_section] = '\n'.join(section_content).strip()
                    current_section = 'video_summary'
                    section_content = []
                    content_on_line = line.replace('**VIDEO SUMMARY:**', '').strip()
                    if content_on_line:
                        section_content.append(content_on_line)
                        
                elif line.startswith('**ACTIVITIES BREAKDOWN:**'):
                    if current_section and section_content:
                        result[current_section] = '\n'.join(section_content).strip()
                    current_section = 'activities'
                    section_content = []
                    content_on_line = line.replace('**ACTIVITIES BREAKDOWN:**', '').strip()
                    if content_on_line:
                        section_content.append(content_on_line)
                        
                elif line.startswith('**SEARCHABLE KEYWORDS:**'):
                    if current_section and section_content:
                        result[current_section] = '\n'.join(section_content).strip()
                    current_section = 'keywords'
                    section_content = []
                    content_on_line = line.replace('**SEARCHABLE KEYWORDS:**', '').strip()
                    if content_on_line:
                        section_content.append(content_on_line)
                        
                elif line.startswith('**PLAYER CONTRIBUTIONS:**'):
                    if current_section and section_content:
                        result[current_section] = '\n'.join(section_content).strip()
                    current_section = None  # Skip player contributions
                    section_content = []
                    
                elif current_section and line and not line.startswith('**'):
                    section_content.append(line)
            
            # Add last section
            if current_section and section_content:
                result[current_section] = '\n'.join(section_content).strip()
            
            # The caption and summary are meant to read like a short photo caption
            # ("Dhoni playing at nets"). The prompt asks for 15 words, but the model
            # drifts longer and sometimes returns several bulleted options, so take the
            # first line and enforce the limit here rather than trusting the model.
            result['caption'] = self._clean_caption(result['caption'])
            result['video_summary'] = self._clean_caption(result['video_summary'])
            
            # Ensure no empty values
            if not result['caption']:
                result['caption'] = 'Cricket Video'
            if not result['video_summary']:
                result['video_summary'] = 'Cricket training session'
            if not result['keywords']:
                result['keywords'] = 'cricket'
        
        except Exception as e:
            self.log(f"  ⚠️ Summary parsing error: {str(e)}")
            result['caption'] = 'Cricket Video'
            result['video_summary'] = 'Error parsing summary'
            result['keywords'] = 'cricket'
        
        return result
    
    def generate_final_summary(self, llm_analyses: List[Dict], all_detected_players: List[str], is_unknown_faces: bool = False) -> Dict[str, str]:
        """
        Generate final summary using Gemini
        Args:
            llm_analyses: List of frame analyses
            all_detected_players: List of detected players (can be empty)
            is_unknown_faces: If True, limit summary to 15 words
        """
        if not llm_analyses:
            default_summary = 'Cricket Video' if not is_unknown_faces else 'Cricket Scene'
            return {
                'caption': default_summary,
                'video_summary': 'No analysis available' if not is_unknown_faces else 'Cricket video scene',
                'activities': 'None',
                'keywords': 'cricket'
            }
        
        self.log(f"→ Generating final summary...")
        
        try:
            # Prepare frame analyses
            frame_analyses = []
            for analysis in llm_analyses:
                frame_info = analysis.get('frame_info', {})
                frame_analyses.append({
                    'frame': frame_info.get('frame_num', 0),
                    'timestamp': float(frame_info.get('second', 0)),
                    'players': analysis.get('players', []),
                    'analysis': analysis.get('description', '')
                })
            
            # Generate prompt
            prompt = get_final_summary_prompt(frame_analyses, all_detected_players, is_unknown_faces)
            
            api_key = self.get_next_api_key()
            client = self.clients.get(api_key)
            if not client:
                raise RuntimeError("No Gemini client for API key")
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(),
            )
            
            if response and response.text:
                parsed = self.parse_summary_response(response.text)
                
                # Caption and summary are always short and simple (max 15 words)
                parsed['caption'] = limit_words(parsed.get('caption', '').strip().strip('"\'*'), 15)
                parsed['video_summary'] = limit_words(parsed.get('video_summary', '').strip().strip('"\'*'), 15)
                
                self.log(f"✓ Summary generated\n")
                return parsed
            else:
                raise RuntimeError("No response from Gemini")
        
        except Exception as e:
            self.log(f"  ⚠️ Summary generation error: {str(e)}")
            default_summary = 'Cricket Video' if not is_unknown_faces else 'Cricket Scene'
            return {
                'caption': default_summary,
                'video_summary': 'Cricket video',
                'activities': 'Processing error',
                'keywords': 'cricket'
            }
    
    def create_thumbnail_from_first_frame(self, frame_paths: List[Dict], url: str):
        """Create and save thumbnail from first frame to thumbnails table"""
        if not frame_paths:
            return
        
        try:
            first_frame_path = frame_paths[0]['path']
            img = Image.open(first_frame_path).convert("RGB")
            
            # Resize to thumbnail
            img.thumbnail((400, 400))
            width, height = img.size
            
            # Convert to binary
            import io
            buffer = io.BytesIO()
            img.save(buffer, "JPEG", quality=80)
            thumbnail_data = buffer.getvalue()
            
            # Save to thumbnails table (same as images)
            self.db_manager.save_thumbnail(url, thumbnail_data, width, height)
            self.log(f"✓ Thumbnail saved to thumbnails table")
            
        except Exception as e:
            self.log(f"⚠️ Thumbnail creation failed: {e}")
    
    def extract_datetime_from_exif(self, video_path: str) -> Tuple[Optional[str], Optional[str]]:
        """Try to extract datetime from video metadata"""
        try:
            # Try using ffprobe if available
            ffprobe = shutil.which('ffprobe')
            if ffprobe:
                cmd = [ffprobe, '-v', 'quiet', '-show_entries', 
                       'format_tags=creation_time', '-of', 'default=noprint_wrappers=1:nokey=1', 
                       video_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    dt_str = result.stdout.strip()
                    dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    return dt.strftime('%Y-%m-%d %H:%M:%S'), dt.strftime('%Y-%m-%d')
        except:
            pass
        
        # Fallback to file modification time
        try:
            mtime = os.path.getmtime(video_path)
            dt = datetime.fromtimestamp(mtime)
            return dt.strftime('%Y-%m-%d %H:%M:%S'), dt.strftime('%Y-%m-%d')
        except:
            return None, None
    
    @staticmethod
    def _seconds_to_min_sec(seconds: float) -> str:
        """Format seconds as 'Xmin Ysec' (e.g. 62.5 -> '1min 2sec')."""
        s = max(0, float(seconds))
        mins = int(s) // 60
        secs = int(s) % 60
        return f"{mins}min {secs}sec"

    def _format_timestamped_transcript(self, segment_list: List[Dict], max_chars: Optional[int] = None) -> str:
        """
        Build transcript string with timestamps: '1min 2sec: paragraph\\n2min 5sec: paragraph\\n...'
        Applies max_chars for DB storage.
        """
        if not segment_list:
            return ""
        max_chars = max_chars if max_chars is not None else self.TRANSCRIBE_MAX_CHARS
        lines = []
        for seg in segment_list:
            start = seg.get("start", 0)
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            ts = self._seconds_to_min_sec(start)
            lines.append(f"{ts}: {text}")
        out = "\n".join(lines)
        return limit_chars(out, max_chars)

    def _load_whisper_model(self, model_name: Optional[str] = None):
        """Load Whisper model (cached)."""
        name = model_name or self._whisper_model_name
        if _WhisperModel is None:
            return None
        if self._whisper_model is None or getattr(self, '_last_whisper_name', None) != name:
            try:
                self._whisper_model = _WhisperModel(name, device="cpu", compute_type="int8")
                self._last_whisper_name = name
            except Exception as e:
                self.log(f"  ⚠️ Whisper model load failed: {e}")
                return None
        return self._whisper_model
    
    # Only transcribe when detected language is English (skip nn, no, etc.)
    TRANSCRIBE_LANGUAGE = os.getenv('TRANSCRIBE_LANGUAGE', 'en').strip().lower()

    def transcribe_video(self, video_path: str, max_chars: Optional[int] = None, model_name: Optional[str] = None) -> Tuple[Optional[str], Optional[List[Dict]]]:
        """
        Transcribe video audio using faster-whisper. Returns (transcript_text_truncated, segments).
        Only runs when detected language is English; skips transcription for other languages (e.g. nn, no).
        transcript is truncated to max_chars for DB storage (default TRANSCRIBE_MAX_CHARS).
        """
        # Hard kill-switch: skip the entire faster-whisper / CTranslate2 audio path.
        # This is the crashing path ("Processing audio with duration ..." → segfault),
        # so when disabled we never load the model or touch the audio decoder.
        if not self.enable_transcribe:
            self.log("  → Audio transcription DISABLED (ENABLE_TRANSCRIBE=false) — skipping audio; "
                  "using frames + player recognition + Gemini summary only")
            return None, None

        max_chars = max_chars if max_chars is not None else self.TRANSCRIBE_MAX_CHARS
        model = self._load_whisper_model(model_name)
        if model is None:
            return None, None
        try:
            segments, info = model.transcribe(video_path)
            # Only transcribe if detected language is English (en, en-US, etc.); skip nn, no, etc.
            detected_lang = (getattr(info, 'language', None) or '').strip()
            if detected_lang:
                allowed = [a.strip().lower() for a in self.TRANSCRIBE_LANGUAGE.split(',') if a.strip()] or ['en']
                lang_lower = detected_lang.lower()
                is_allowed = lang_lower in allowed or any(lang_lower.startswith(a) for a in allowed if len(a) >= 2)
                if not is_allowed:
                    self.log(f"  → Skipping transcribe: detected language '{detected_lang}' (only English transcribed)")
                    return None, None
            full_text = ""
            segment_list = []
            for seg in segments:
                t = seg.text or ""
                full_text += t + " "
                segment_list.append({"start": float(seg.start), "end": float(seg.end), "text": t})
            # Return raw transcript (truncated) and segments for timestamped format
            transcript = limit_chars(full_text.strip(), max_chars)
            return transcript, segment_list
        except Exception as e:
            self.log(f"  ⚠️ Transcription error: {e}")
            return None, None
    
    def extract_tags_for_db(self, llm_analyses: List[Dict]) -> Dict[str, str]:
        """
        Extract action, mood, event tags from frame analyses for DB storage.
        Only uses analyses from annotated frames (frames with detected players), not full-image
        analysis, to match image_processing LLM tags logic.
        Returns dict with keys: action, mood, event (comma-separated strings).
        """
        # Only consider analyses from frames that had players (annotated bbox image was sent to LLM)
        analyses_with_players = [a for a in (llm_analyses or []) if a.get('players')]
        llm_analyses = analyses_with_players
        mood_kw = {
            "confident": ["confident", "assured", "determined", "self-belief", "composed", "commanding", "assertive", "poised"],
            "focused": ["focused", "concentration", "concentrating", "locked-in", "serious", "intent", "attentive", "engrossed", "zoned-in"],
            "excited": ["excited", "energetic", "enthusiastic", "pumped", "thrilled", "animated", "exhilarated", "fired-up"],
            "celebrating": ["celebrating", "celebration", "cheering", "victorious", "triumphant", "jubilant", "elated", "ecstatic"],
            "tense": ["tense", "tension", "pressure", "nervous", "anxious", "stressed", "edgy", "on-edge"],
            "relaxed": ["relaxed", "calm", "casual", "comfortable", "at ease", "laid-back", "cool", "composed"],
            "motivated": ["motivated", "inspired", "driven", "passionate", "hungry", "eager"],
            "proud": ["proud", "satisfied", "pleased", "accomplished", "gratified"],
            "disappointed": ["disappointed", "dejected", "frustrated", "downcast", "crestfallen", "disheartened"],
            "aggressive": ["aggressive", "intense", "fierce", "combative", "charged-up"],
            "reflective": ["reflective", "thoughtful", "contemplative", "pensive", "introspective"],
            "joyful": ["joyful", "happy", "smiling", "beaming", "cheerful", "delighted"]
        }

        action_kw = {
            "batting": ["batting", "batsman", "batter", "shot", "drive", "hook", "pull", "sweep", "cut", "glance", "defense", "block", "stance"],
            "bowling": ["bowling", "bowler", "deliver", "delivery", "run-up", "overarm", "spin", "pace", "yorker", "bouncer", "appeal"],
            "fielding": ["fielding", "fielder", "catch", "catching", "throw", "throwing", "dive", "diving", "stop", "stopping", "sliding"],
            "wicketkeeping": ["wicketkeeper", "gloves", "stumping", "keeping", "behind stumps", "collecting", "diving catch"],
            "running": ["running", "sprinting", "running between wickets", "quick single", "dashing"],
            "warm-up": ["warm-up", "warming up", "stretch", "stretching", "drill", "practice", "loosening up"],
            "sitting": ["sitting", "seated", "sits", "bench", "dugout", "pavilion"],
            "interviewing": ["interviewing", "interview", "media talk", "press interaction", "answering questions"],
            "speaking": ["speaking", "talking", "addressing", "commenting", "discussing", "conversing"],
            "lounging": ["lounging", "reclining", "resting", "relaxing"],
            "celebration_gesture": ["fist pump", "clapping", "raising bat", "waving", "jumping", "high-five", "chest bump", "arms raised"],
            "walking": ["walking", "heading to pitch", "returning to pavilion", "striding", "marching"],
            "signing": ["signing", "autograph", "signing autographs", "signing memorabilia"],
            "posing": ["posing", "photo", "photograph", "picture", "photoshoot"],
            "drinking": ["drinking", "hydrating", "water break", "sipping"],
            "conferring": ["conferring", "discussing strategy", "consulting", "team talk"],
            "appealing": ["appealing", "appeal", "shouting", "claiming wicket"],
            "observing": ["observing", "watching", "looking", "monitoring", "tracking"],
            "adjusting": ["adjusting pads", "fixing gloves", "helmet adjustment", "gear check"]
        }

        event_kw = {
            "nets": ["nets", "net practice", "net session", "training nets"],
            "match": ["match", "game", "test match", "odi", "one day international", "t20", "twenty20", "ipl", "tournament"],
            "huddle": ["huddle", "team huddle", "team discussion", "strategy", "pep talk", "team talk"],
            "practice": ["practice", "practice session", "training session", "training", "practice match"],
            "interview": ["interview", "press conference", "media interaction", "post-match interview", "pre-match interview"],
            "toss": ["toss", "coin toss", "captains meeting"],
            "presentation": ["presentation ceremony", "post-match ceremony", "award ceremony", "trophy presentation"],
            "photoshoot": ["photoshoot", "photo session", "team photo", "official photo"],
            "fan_interaction": ["fan meet", "fan interaction", "meeting fans", "signing session", "fan engagement", "autograph session"],
            "arrival": ["arrival", "entering stadium", "team bus", "arriving at venue"],
            "departure": ["departure", "leaving", "exiting stadium", "heading out"],
            "national_anthem": ["national anthem", "anthem ceremony", "pre-match anthem"],
            "drinks_break": ["drinks break", "refreshment break", "strategic timeout"],
            "innings_break": ["innings break", "break between innings", "interval"],
            "warm_up_session": ["warm-up session", "pre-match warm-up", "fielding drills"],
            "dressing_room": ["dressing room", "locker room", "team room", "change room"],
            "ground_inspection": ["pitch inspection", "ground inspection", "checking conditions"],
            "sponsor_event": ["sponsor event", "promotional event", "brand activation", "commercial shoot"]
        }
        mood_set = set()
        action_set = set()
        event_set = set()
        for analysis in llm_analyses:
            desc = (analysis.get('description') or '').strip().lower()
            if not desc or desc.startswith('error:'):
                continue
            for tag, kws in mood_kw.items():
                if any(k in desc for k in kws):
                    mood_set.add(tag.title())
            for tag, kws in action_kw.items():
                if any(k in desc for k in kws):
                    action_set.add(tag.title())
            for tag, kws in event_kw.items():
                if any(k in desc for k in kws):
                    event_set.add(tag.title())
        return {
            'action': ', '.join(sorted(action_set)) if action_set else None,
            'mood': ', '.join(sorted(mood_set)) if mood_set else None,
            'event': ', '.join(sorted(event_set)) if event_set else None,
        }
    
    def process_single_video(self, video_info: Dict, shutdown_flag_ref=None) -> Dict:
        """
        Process a single video through complete pipeline
        Returns result dict ready for database insertion
        """
        local_file_path = video_info['file_path']
        file_name = video_info['file_name']
        url = video_info['url']
        drive_path = video_info.get('drive_path', '')
        
        self.log(f"\n{'='*60}")
        self.log(f"PROCESSING VIDEO: {file_name}")
        self.log(f"{'='*60}\n")
        
        result = {
            'file_name': file_name,
            'url': url,
            'video_path': drive_path,
            'tournament': None,
            'player_names': [],
            'datetime': None,
            'date': None,
            'time_of_day': None,
            'no_of_faces': 0,
            'video_summary': None,
            'caption': None,
            'keywords': None,
            'transcribe': None,
            'action': None,
            'mood': None,
            'event': None,
            'status': 'pending',
            'error_message': None
        }
        
        start_time = time.time()
        
        try:
            # Check shutdown flag
            if shutdown_flag_ref:
                self.log("⚠️ Shutdown requested, skipping video")
                result['status'] = 'skipped'
                return result
            
            # Step 1: Extract frames
            self.log("STEP 1: EXTRACT FRAMES")
            self.log("-" * 60)
            frame_paths = self.extract_frames_ffmpeg(local_file_path)
            
            # Step 2: Create thumbnail from first frame
            self.log("STEP 2: CREATE THUMBNAIL")
            self.log("-" * 60)
            # Thumbnail is saved to thumbnails table via save_thumbnail() method
            self.create_thumbnail_from_first_frame(frame_paths, url)
            
            # Step 3: Detect faces
            self.log("STEP 3: DETECT FACES")
            self.log("-" * 60)
            all_results, frames_with_players = self.detect_faces_sequential(frame_paths)
            
            # Collect all unique players (no_of_faces = count of unique players, not total detections)
            # ---- Temporal consensus ----
            # Count how many DISTINCT frames each player appears in, then keep only the
            # ones seen often enough. A name that shows up in a single frame out of
            # dozens is a misidentification, not a player in the video.
            frame_counts = {}
            for frame_result in all_results:
                for name in {d['name'] for d in frame_result['detections']}:
                    frame_counts[name] = frame_counts.get(name, 0) + 1
            
            min_frames = max(
                self.PLAYER_MIN_FRAMES,
                int(round(self.PLAYER_MIN_FRAMES_RATIO * len(all_results))),
            ) if all_results else self.PLAYER_MIN_FRAMES
            
            # Short clips can legitimately have fewer frames than the floor; fall back to
            # the busiest player(s) rather than silently tagging nobody.
            confirmed = {n for n, c in frame_counts.items() if c >= min_frames}
            if not confirmed and frame_counts:
                best = max(frame_counts.values())
                if best > 1:
                    confirmed = {n for n, c in frame_counts.items() if c == best}
            
            rejected = {n: c for n, c in frame_counts.items() if n not in confirmed}
            if rejected:
                self.log(f"  ⏳ Temporal consensus (min {min_frames} frames) dropped: "
                         + ", ".join(f"{n} ({c})" for n, c in sorted(rejected.items())))
            
            all_players = confirmed
            
            # Drop rejected names from the per-frame detections too. The frames are what
            # get sent to Gemini, and get_frame_analysis_prompt() names whoever is in
            # them — so without this a name consensus just rejected still reappears in
            # the frame descriptions and from there in the caption and summary.
            if rejected:
                for frame_result in all_results:
                    frame_result['detections'] = [d for d in frame_result['detections']
                                                  if d['name'] in confirmed]
                frames_with_players = [r for r in all_results if r['detections']]
            
            result['player_frame_counts'] = frame_counts
            result['no_of_faces'] = len(all_players)  # Unique players only (e.g. 5 frames same player -> 1)
            result['player_names'] = sorted(all_players)
            
            # Determine if this is an unknown faces video
            # Videos with no players OR all unknown players should be treated as unknown
            has_no_players = len(result['player_names']) == 0
            if result['player_names']:
                player_names_str = ', '.join(result['player_names'])
                result['is_unknown'] = is_unknown_player(player_names_str)
            else:
                result['is_unknown'] = True  # No players detected = unknown faces video
            
            # Step 4: AI Analysis
            self.log("STEP 4: AI ANALYSIS")
            self.log("-" * 60)
            # If no players detected, analyze all frames (including those without players)
            if has_no_players:
                self.log("  No players detected - analyzing all frames")
                # Analyze all frames, not just those with players
                frames_to_analyze = all_results
                llm_analyses = self.parallel_llm_analysis(frames_to_analyze, include_no_players=True)
            else:
                # Only analyze frames with players
                llm_analyses = self.parallel_llm_analysis(frames_with_players, include_no_players=False)
            
            # Step 5: Generate summary
            self.log("STEP 5: GENERATE SUMMARY")
            self.log("-" * 60)
            summary_data = self.generate_final_summary(llm_analyses, result['player_names'], is_unknown_faces=result['is_unknown'])
            
            result['caption'] = summary_data.get('caption', 'Cricket Video')
            result['video_summary'] = summary_data.get('video_summary', '')
            result['keywords'] = summary_data.get('keywords', '')
            
            # Tags for DB (action, mood, event) from frame analyses
            tags_for_db = self.extract_tags_for_db(llm_analyses)
            result['action'] = tags_for_db.get('action')
            result['mood'] = tags_for_db.get('mood')
            result['event'] = tags_for_db.get('event')
            
            # Transcribe audio; save with timestamps (e.g. "1min 2sec: paragraph\n2min 5sec: ...")
            transcript, segment_list = self.transcribe_video(local_file_path, max_chars=self.TRANSCRIBE_MAX_CHARS)
            if segment_list:
                result['transcribe'] = self._format_timestamped_transcript(segment_list, self.TRANSCRIBE_MAX_CHARS)
            else:
                result['transcribe'] = transcript
            
            # Extract datetime
            dt, date = self.extract_datetime_from_exif(local_file_path)
            result['datetime'] = dt
            result['date'] = date
            result['time_of_day'] = self._determine_time_of_day(dt)
            
            # Tournament from .env file
            result['tournament'] = os.getenv('TOURNAMENT_NAME', os.getenv('DEFAULT_TOURNAMENT', 'Unknown'))
            
            result['status'] = 'completed'
            
            processing_time = time.time() - start_time
            
            self.log(f"\n{'='*60}")
            self.log(f"VIDEO PROCESSED SUCCESSFULLY")
            self.log(f"{'='*60}")
            self.log(f"Players detected: {', '.join(result['player_names'])}")
            self.log(f"Caption: {result['caption'][:50]}...")
            self.log(f"Processing time: {format_seconds(processing_time)}")
            self.log(f"{'='*60}\n")
            
        except Exception as e:
            result['status'] = 'error'
            result['error_message'] = str(e)
            self.log(f"\n✗ Video processing failed: {str(e)}\n")
        
        finally:
            # Cleanup frames and annotated images
            self.cleanup_temp_folders()
        
        return result
    
    async def process_videos_batch(self, video_info_list: List[Dict], shutdown_flag_ref=None):
        """
        Process multiple videos sequentially
        Saves results to database with unknown face handling (similar to images)
        """
        if not video_info_list:
            self.log("→ No videos to process")
            return
        
        self.log(f"\n{'#'*60}")
        self.log(f"VIDEO PROCESSING BATCH")
        self.log(f"{'#'*60}")
        self.log(f"Total videos: {len(video_info_list)}")
        self.log(f"{'#'*60}\n")
        
        results = []
        unknown_faces_videos = []
        
        for idx, video_info in enumerate(video_info_list, 1):
            if shutdown_flag_ref:
                self.log("\n⚠️ Shutdown requested, stopping video processing")
                break
            
            self.log(f"\n[{idx}/{len(video_info_list)}] Processing video...")
            
            result = self.process_single_video(video_info, shutdown_flag_ref)
            
            # Separate unknown faces videos (videos with no players or all unknown players)
            if result.get('is_unknown') and result.get('status') == 'completed':
                unknown_faces_videos.append(result)
                player_count = len(result.get('player_names', []))
                if player_count == 0:
                    self.log(f"  🔍 No players detected in video: {result['file_name']}")
                else:
                    self.log(f"  🔍 Unknown face detected in video: {result['file_name']}")
            else:
                results.append(result)
        
        # Save to database
        self.log(f"\n{'='*60}")
        self.log("SAVING RESULTS TO DATABASE")
        self.log(f"{'='*60}")
        
        completed = [r for r in results if r['status'] == 'completed']
        errors = [r for r in results if r['status'] == 'error']
        unknown_completed = [r for r in unknown_faces_videos if r['status'] == 'completed']
        unknown_errors = [r for r in unknown_faces_videos if r['status'] == 'error']
        
        # Save unknown faces videos first (to unknown_faces_video table)
        if unknown_completed:
            self.log(f"→ Saving {len(unknown_completed)} unknown faces videos to database...")
            try:
                self.db_manager.save_unknown_faces_video_batch(unknown_completed)
                self.log(f"✓ Saved {len(unknown_completed)} unknown faces videos")
            except Exception as e:
                self.log(f"✗ Error saving unknown faces videos: {e}")
        
        # Save known player videos
        if completed:
            try:
                self.db_manager.save_videos_batch(completed)
                self.log(f"✓ Saved {len(completed)} videos to database")
            except Exception as e:
                self.log(f"✗ Database save error: {e}")
        
        if errors:
            self.log(f"⚠️ {len(errors)} videos had errors")
        if unknown_errors:
            self.log(f"⚠️ {len(unknown_errors)} unknown faces videos had errors")
        
        self.log(f"\n📊 Processing Statistics:")
        self.log(f"  ✓ Known players:     {len(completed)}/{len(video_info_list)}")
        self.log(f"  🔍 Unknown faces:    {len(unknown_completed)}/{len(video_info_list)}")
        self.log(f"{'='*60}\n")
