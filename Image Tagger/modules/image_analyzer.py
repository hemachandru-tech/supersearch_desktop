# modules/image_analyzer.py
"""
Image Analyzer Module
Handles complete image analysis including face detection, AI analysis, and jersey classification
FIXED: Updated to handle new process_image return values (results, face_count, skip_reason, orientation, rotation)
"""

import os
import time
import shutil
import numpy as np
from datetime import datetime
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

from modules.ai_tags import CricketImageAnalyzer, AnalysisResult
from modules.image_processing import extract_exif_details, save_annotated_image, process_image
from modules.drive_downloader import GoogleDriveDownloader
from modules.utils import (
    format_seconds, 
    safe_extract_exif_with_retries,
    is_unknown_player,
    build_thumbnails_for_local_images
)
from modules.jersey_classifier import load_model, predict_jersey_type


class CombinedAnalyzer:
    """Combines all analysis components into a unified pipeline"""
    
    def __init__(self, api_keys: list, db_manager, max_workers: int = 4):
        """Initialize analyzer with API keys and database"""
        print(f"\n→ Initializing analyzer with {len(api_keys)} API keys")
        print(f"→ Parallel workers: {max_workers}")
        
        self.cricket_analyzer = CricketImageAnalyzer(
            api_keys=api_keys,
            max_workers=max_workers
        )
        
        from modules import paths
        model_path = os.getenv('JERSEY_MODEL_PATH', paths.resource_path('models', 'jersey.pth'))
        self.jersey_model = load_model(model_path)
        self.max_workers = max_workers
        self.db_manager = db_manager
        
        print(f"✓ Analyzer ready with {max_workers} parallel workers")

    async def process_from_drive(self, folder_id, shutdown_flag_ref, output_dir="results", predownloaded_images=None, tournament_name=None):
        """Full processing pipeline with database storage
        
        Args:
            folder_id: Google Drive folder ID (ignored if predownloaded_images is provided)
            shutdown_flag_ref: Reference to shutdown flag
            output_dir: Output directory for results
            predownloaded_images: Optional list of already downloaded images to skip download step
            tournament_name: Tournament name from .env file
        """
        
        script_start_time = datetime.now()
        print(f"\n{'='*60}")
        print(f"PROCESSING STARTED")
        print(f"{'='*60}")
        print(f"Start time: {script_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Parallel workers: {self.max_workers}")
        print(f"{'='*60}\n")
        
        total_start = time.time()
        
        # Download Images (or use predownloaded)
        if predownloaded_images is not None:
            print("PHASE 1: USING PREDOWNLOADED IMAGES")
            print("-" * 60)
            download_start = time.time()
            image_info = predownloaded_images
            thumb_map = build_thumbnails_for_local_images(image_info, self.db_manager, max_workers=self.max_workers)
            download_time = time.time() - download_start
            print(f"✓ Using {len(image_info)} predownloaded images")
            print(f"✓ Thumbnails processed in {format_seconds(download_time)}\n")
        else:
            print("PHASE 1: DOWNLOADING IMAGES")
            print("-" * 60)
            download_start = time.time()
            image_info = await GoogleDriveDownloader.download_images_from_drive(
                folder_id, 
                self.db_manager
            )
            thumb_map = build_thumbnails_for_local_images(image_info, self.db_manager, max_workers=self.max_workers)
            download_time = time.time() - download_start
            print(f"✓ Download phase completed in {format_seconds(download_time)}\n")

        total_images = len(image_info)
        
        if not image_info:
            print("→ No new images to process")
            return

        if shutdown_flag_ref:
            print("\n⚠️  Shutdown requested during download phase. Exiting...")
            return

        # Image Processing
        print(f"PHASE 2: COMPLETE AI ANALYSIS ({total_images} images)")
        print(f"→ Running {self.max_workers} images simultaneously")
        print("-" * 60)
        processing_start = time.time()
        
        results = []
        unknown_faces = []
        processed_count = 0
        
        def process_single_image_complete(img):
            """Process one complete image with unknown face detection"""
            if shutdown_flag_ref:
                return None
                
            file_path = img["file_path"]
            file_name = img["file_name"]
            url = img["url"]
            drive_path = img.get("drive_path") or None
            
            result = {
                "file_name": file_name,
                "url": url,
                "tournament": tournament_name,
                "image_path": drive_path,
                "drive_link": url,
            }
            
            # EXIF EXTRACTION
            exif_data = safe_extract_exif_with_retries(file_name, file_path, max_retries=5)

            if exif_data:
                result.update(exif_data)
            else:
                result.update({
                    "Photographer": None,
                    "Copyright": None,
                    "DateTimeOriginal": None,
                    "Date": "Unknown",
                    "Camera Make": None,
                    "Camera Model": None,
                    "NoOfFaces": 0,
                    "Focus": "null",
                    "Shot Type": "Unknown",
                    "Player Name": "Unknown"
                })
            
            # CHECK IF PLAYER IS UNKNOWN OR CROWD
            player_name = result.get("Player Name", "")
            
            # Check for crowd
            if player_name == "crowd":
                return {
                    "file_name": file_name,
                    "url": url,
                    "tournament": tournament_name,
                    "image_path": drive_path,
                    "drive_link": url,
                    "Player Name": "crowd",
                    "is_unknown": True,
                    "skip_reason": "crowd_detected"
                }
            
            # Check for unknown faces
            if is_unknown_player(player_name):
                return {
                    "file_name": file_name,
                    "url": url,
                    "tournament": tournament_name,
                    "image_path": drive_path,
                    "drive_link": url,
                    "Player Name": "Unknown",
                    "is_unknown": True
                }
            
            # Face Detection - FIXED: Handle all 5 return values
            try:
                image_np = np.array(Image.open(file_path).convert("RGB"))
                # IMPORTANT: process_image now returns 5 values
                face_results, face_count, skip_reason, orientation, rotation = process_image(image_np)
                
                if face_results:
                    try:
                        annotated_path = save_annotated_image(
                            file_path,
                            face_results,
                            out_dir=os.path.join("results", "annotated")
                        )
                    except:
                        pass
            except Exception as e:
                print(f"  ⚠️ Face detection skipped for {file_name}: {str(e)[:50]}")
            
            # AI Cricket Analysis
            cricket_result = None
            try:
                cricket_result = self.cricket_analyzer.analyze_single_image(file_path)
            except Exception as e:
                print(f"  ⚠️ AI analysis failed for {file_name}: {e}")
            
            result.update(self._format_cricket_result(cricket_result))
            
            # Jersey Classification
            try:
                apparel_label, apparel_conf = predict_jersey_type(file_path, self.jersey_model)
                result["apparel"] = apparel_label
            except Exception as e:
                print(f"  ⚠️ Jersey classification failed for {file_name}: {e}")
                result["apparel"] = "Unknown"
            
            result["is_unknown"] = False
            return result
        
        # Process ALL images in parallel
        print(f"→ Starting parallel processing...\n")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_img = {
                executor.submit(process_single_image_complete, img): img 
                for img in image_info
            }
            
            for future in as_completed(future_to_img):
                if shutdown_flag_ref:
                    print("\n⚠️  Cancelling remaining tasks...")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                    
                img = future_to_img[future]
                try:
                    result = future.result()
                    
                    if result is None:
                        continue
                    
                    # Separate unknown faces and crowds
                    if result.get("is_unknown"):
                        unknown_faces.append(result)
                        if result.get("skip_reason") == "crowd_detected":
                            print(f"  🔍 Crowd detected: {result['file_name']}")
                        else:
                            print(f"  🔍 Unknown face detected: {result['file_name']}")
                    else:
                        results.append(result)
                    
                    processed_count += 1
                    
                    if processed_count % 5 == 0 or processed_count == total_images:
                        print(f"→ Progress: {processed_count}/{total_images} images completed")
                        
                except Exception as e:
                    print(f"✗ Error processing {img['file_name']}: {e}")
                    results.append({
                        "file_name": img["file_name"],
                        "url": img["url"],
                        "apparel": "Unknown",
                        "error": str(e),
                        "is_unknown": False
                    })
                    processed_count += 1
        
        processing_time = time.time() - processing_start
        avg_time_per_image = processing_time / total_images if total_images > 0 else 0
        
        print(f"\n✓ Complete AI analysis finished in {format_seconds(processing_time)}")
        print(f"  Average: {avg_time_per_image:.2f} sec/image with {self.max_workers} workers")
        print(f"\n📊 Processing Statistics:")
        print(f"  ✓ Known players:     {len(results)}/{total_images}")
        print(f"  🔍 Unknown faces:    {len(unknown_faces)}/{total_images}")
        print()

        if shutdown_flag_ref:
            print("\n⚠️  Shutdown requested. Saving processed results...")

        # Save Results to Database
        print("PHASE 3: SAVING TO DATABASE")
        print("-" * 60)
        result_save_start = time.time()
        self._save_results_to_database(results, unknown_faces)
        result_save_time = time.time() - result_save_start
        print(f"✓ Results saved to database in {format_seconds(result_save_time)}\n")

        total_time = time.time() - total_start
        script_end_time = datetime.now()

        print(f"{'='*60}")
        print(f"PROCESSING COMPLETED")
        print(f"{'='*60}")
        print(f"Start time:  {script_start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End time:    {script_end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total time:  {format_seconds(total_time)}")
        print(f"Images:      {total_images} processed")
        print(f"Workers:     {self.max_workers} parallel")
        print(f"Speed:       {avg_time_per_image:.2f} sec/image")
        print(f"{'='*60}\n")

        # Cleanup
        self._cleanup_input_images(image_info)
        self._cleanup_annotated_folder()

    def _format_cricket_result(self, result: AnalysisResult) -> dict:
        """Format cricket analysis result"""
        if result is None:
            return {
                "event_type": None,
                "mood": None,
                "action": None,
                "location": None,
                "jersey_color": None,
                "accessories_seen": None,
                "crowd_present": None,
                "caption": None,
                "logos_branding": None,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "processing_time": None,
                "status": "failed",
                "error_message": "AI analysis failed",
                "api_key_used": None
            }
        
        return {
            "event_type": result.event_type,
            "mood": result.mood,
            "action": result.action,
            "location": result.location,
            "jersey_color": result.jersey_color,
            "accessories_seen": result.apparels_seen,
            "crowd_present": result.crowd_present,
            "caption": result.caption,
            "logos_branding": result.logos_branding,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
            "processing_time": result.processing_time,
            "status": result.status,
            "error_message": result.error_message,
            "api_key_used": result.api_key_used
        }

    def _cleanup_input_images(self, image_info: list):
        """Delete all downloaded input images after processing"""
        if not image_info:
            return
            
        print("→ Cleaning up input images...")
        deleted_count = 0
        
        for img in image_info:
            file_path = img.get("file_path")
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except:
                    pass
        
        print(f"✓ Deleted {deleted_count} processed images")
        
        try:
            input_dir = "input_images"
            if os.path.exists(input_dir) and not os.listdir(input_dir):
                os.rmdir(input_dir)
        except:
            pass

    def _cleanup_annotated_folder(self):
        """Delete the entire annotated images folder after processing"""
        annotated_dir = os.path.join("results", "annotated")
        
        if not os.path.exists(annotated_dir):
            return
        
        try:
            shutil.rmtree(annotated_dir)
            print("✓ Annotated images cleaned up")
        except:
            pass

    def _save_results_to_database(self, results: list, unknown_faces: list):
        """Save results to MySQL database"""
        
        if not results and not unknown_faces:
            print("→ No results to save")
            return

        # Save unknown faces
        if unknown_faces:
            print(f"→ Saving {len(unknown_faces)} unknown faces to database...")
            try:
                self.db_manager.save_unknown_faces_batch(unknown_faces)
                print(f"✓ Saved {len(unknown_faces)} unknown faces")
            except Exception as e:
                print(f"✗ Error saving unknown faces: {e}")

        # Save known player images
        if results:
            print(f"→ Saving {len(results)} images to database...")
            
            # Process datetime fields
            import pandas as pd
            for result in results:
                # Format DateTimeOriginal
                if result.get('DateTimeOriginal'):
                    try:
                        dt = pd.to_datetime(result['DateTimeOriginal'], format='%Y:%m:%d %H:%M:%S', errors='coerce')
                        result['DateTimeOriginal'] = dt.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(dt) else None
                    except:
                        result['DateTimeOriginal'] = None
                
                # Format Date
                if result.get('Date'):
                    try:
                        dt = pd.to_datetime(result['Date'], errors='coerce')
                        result['Date'] = dt.strftime('%Y-%m-%d') if pd.notna(dt) else None
                    except:
                        result['Date'] = None
            
            try:
                self.db_manager.save_images_batch(results)
                print(f"✓ Saved {len(results)} images to database")
            except Exception as e:
                print(f"✗ Error saving images: {e}")
                import traceback
                traceback.print_exc()