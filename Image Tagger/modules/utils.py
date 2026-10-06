# modules/utils.py
"""
Utility Functions Module
Contains helper functions used across the application
"""

import os
import time
import random
import io
import pandas as pd
from datetime import timedelta
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from modules.image_processing import extract_exif_details


def format_seconds(seconds):
    """Format seconds into a human-readable string"""
    duration = timedelta(seconds=seconds)
    minutes = int(duration.total_seconds() // 60)
    seconds = int(duration.total_seconds() % 60)
    return f"{minutes} min {seconds} sec"


def safe_extract_exif_with_retries(file_name, file_path, max_retries=5):
    """Try EXIF extraction up to max_retries times before giving up"""
    for attempt in range(1, max_retries + 1):
        try:
            exif_data = extract_exif_details(file_path)
            if isinstance(exif_data, dict):
                return exif_data
            else:
                raise ValueError("Invalid EXIF result format")
        except Exception as e:
            err_str = str(e)
            if "Unknown C++ exception from OpenCV" in err_str or "cv2" in err_str:
                print(f"  ⚠️ [Attempt {attempt}/{max_retries}] EXIF extraction failed for {file_name}: {err_str}")
                time.sleep(random.uniform(0.3, 0.8))
            else:
                print(f"  ⚠️ [Attempt {attempt}/{max_retries}] Non-OpenCV EXIF error for {file_name}: {err_str}")
            
            if attempt == max_retries:
                print(f"  ✗ EXIF extraction permanently failed after {max_retries} attempts for {file_name}")
                return None
    return None


def is_unknown_player(player_name):
    """Check if player name indicates unknown face"""
    if pd.isna(player_name):
        return False
    
    player_str = str(player_name).strip().lower()
    return player_str == "unknown" or "unknown" in player_str.split(",")


def limit_words(text, max_words=15):
    """Limit text to maximum number of words"""
    if not text or text is None:
        return ""
    text_str = str(text).strip()
    if not text_str:
        return ""
    words = text_str.split()
    if len(words) <= max_words:
        return text_str
    return " ".join(words[:max_words])


def limit_chars(text, max_chars=10000):
    """Limit text to maximum number of characters (for DB transcript field)"""
    if not text or text is None:
        return ""
    text_str = str(text).strip()
    if not text_str or len(text_str) <= max_chars:
        return text_str
    return text_str[:max_chars]


def make_thumbnail(image_path: str, url: str, db_manager, max_side: int = 400) -> bool:
    """
    Create a JPEG thumbnail and save to database
    Returns True if successful, False otherwise
    """
    try:
        # Open and convert image
        img = Image.open(image_path).convert("RGB")
        
        # Calculate thumbnail size
        img.thumbnail((max_side, max_side))
        width, height = img.size
        
        # Convert to binary data
        buffer = io.BytesIO()
        img.save(buffer, "JPEG", quality=80)
        thumbnail_data = buffer.getvalue()
        
        # Save to database
        db_manager.save_thumbnail(url, thumbnail_data, width, height)
        
        return True
    except Exception as e:
        print(f"✗ Thumbnail creation failed for {image_path}: {e}")
        return False


def build_thumbnails_for_local_images(image_info: list, db_manager, max_workers: int = 10) -> dict:
    """
    Build thumbnails for local images in parallel and save to database
    Returns dict of {file_path: success_status}
    """
    if not image_info:
        return {}
    
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(
                make_thumbnail, 
                item["file_path"], 
                item["url"], 
                db_manager
            ): item["file_path"] 
            for item in image_info
        }
        for fut in as_completed(futs):
            fp = futs[fut]
            try:
                results[fp] = fut.result()
            except Exception as e:
                print(f"✗ Thumbnail processing error for {fp}: {e}")
                results[fp] = False
    
    success_count = sum(1 for v in results.values() if v)
    print(f"✓ Thumbnails saved to database: {success_count}/{len(image_info)}")
    return results