# modules/drive_downloader.py
"""
Google Drive Downloader Module - Updated for Images & Videos with Combined Size Limits
Handles authentication and fast parallel downloading from Google Drive
Separates images and videos for appropriate pipeline routing
Supports TOTAL download size limit (images + videos combined) to manage storage constraints
"""

import os
import re
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


class GoogleDriveDownloader:
    """Handles Google Drive authentication and file downloads"""
    
    # Supported file extensions
    IMAGE_EXTENSIONS = {
        # Standard formats
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.avif',
        # RAW formats (including iPhone)
        '.heic', '.heif',  # iPhone/iOS High Efficiency Image Format
        '.dng',            # Digital Negative (RAW)
        '.cr2', '.cr3',    # Canon RAW
        '.nef',            # Nikon RAW
        '.arw',            # Sony RAW
        # Other formats
        '.tiff', '.tif', '.svg'
    }

    VIDEO_EXTENSIONS = {
        # Standard formats
        '.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v',
        # iPhone/iOS formats
        '.hevc',           # High Efficiency Video Coding
        '.3gp', '.3g2',    # 3GPP formats (sometimes used on mobile)
        # Other formats
        '.mpg', '.mpeg', '.m2v', '.m4p', '.ogv', '.qt', '.vob', '.mts', '.m2ts'
    }
    
    @staticmethod
    def parse_size_limit(size_str):
        """
        Parse size limit string to bytes
        Examples: '100GB', '500MB', '1.5GB', '2000mb'
        Returns: size in bytes, or None if invalid/not set
        """
        if not size_str or size_str.strip() == '':
            return None
        
        size_str = size_str.strip().upper()
        
        # Extract number and unit
        match = re.match(r'^([\d.]+)\s*(GB|MB)$', size_str)
        if not match:
            print(f"⚠️ Invalid size format: {size_str}. Expected format: '100GB' or '500MB'")
            return None
        
        value = float(match.group(1))
        unit = match.group(2)
        
        if unit == 'GB':
            return int(value * 1024 * 1024 * 1024)
        elif unit == 'MB':
            return int(value * 1024 * 1024)
        
        return None

    @staticmethod
    def format_size(bytes_size):
        """Format bytes to human-readable size"""
        if bytes_size is None:
            return "N/A"
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"

    @staticmethod
    def load_existing_urls_from_db(db_manager):
        """Load existing URLs from database to avoid duplicates"""
        return db_manager.get_processed_urls()

    @staticmethod
    async def authenticate():
        """Authenticate with Google Drive API using stored token"""
        creds = None
        
        if os.path.exists("token.json"):
            try:
                creds = Credentials.from_authorized_user_file("token.json", SCOPES)
                print("✓ Using saved authentication")
            except Exception as e:
                print(f"✗ Could not load saved authentication: {e}")
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    print("✓ Authentication refreshed")
                except Exception as e:
                    print(f"✗ Could not refresh authentication: {e}")
                    creds = None
            
            if not creds:
                client_secret_path = os.getenv('GOOGLE_CLIENT_SECRET_PATH', 'models/client.json')
                
                if not os.path.exists(client_secret_path):
                    raise FileNotFoundError(
                        f"Google client secret file not found at: {client_secret_path}\n"
                        "Please download it from Google Cloud Console and set GOOGLE_CLIENT_SECRET_PATH in .env"
                    )
                
                print("→ Opening browser for authentication...")
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
                creds = flow.run_local_server(port=8080)
                print("✓ Authentication successful")
            
            with open("token.json", "w") as token:
                token.write(creds.to_json())
                print("✓ Authentication saved for future use")
        
        return build("drive", "v3", credentials=creds)

    @staticmethod
    def extract_file_id_from_url(url):
        """Extract file ID from Google Drive URL"""
        patterns = [
            r'/file/d/([a-zA-Z0-9_-]+)',
            r'id=([a-zA-Z0-9_-]+)',
            r'/d/([a-zA-Z0-9_-]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    async def get_all_folders_recursive(service, folder_id, depth=0):
        """Recursively get all folder IDs inside a given folder"""
        all_folders = [folder_id]
        
        try:
            query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = service.files().list(
                q=query,
                fields="files(id, name)"
            ).execute()
            
            subfolders = results.get("files", [])
            
            if subfolders:
                print(f"{'  ' * depth}→ Found {len(subfolders)} subfolder(s)")
                
            for subfolder in subfolders:
                subfolder_id = subfolder["id"]
                subfolder_name = subfolder["name"]
                print(f"{'  ' * depth}  └─ {subfolder_name}")
                
                nested_folders = await GoogleDriveDownloader.get_all_folders_recursive(
                    service, subfolder_id, depth + 1
                )
                all_folders.extend(nested_folders)
        
        except Exception as e:
            print(f"✗ Error scanning folder: {e}")
        
        return all_folders

    @staticmethod
    def get_file_type(filename):
        """Determine if file is image, video, or other"""
        ext = os.path.splitext(filename.lower())[1]
        if ext in GoogleDriveDownloader.IMAGE_EXTENSIONS:
            return 'image'
        elif ext in GoogleDriveDownloader.VIDEO_EXTENSIONS:
            return 'video'
        else:
            return 'other'

    @staticmethod
    async def build_folder_paths(service, root_folder_id):
        """Build mapping of folder IDs to relative paths from the provided root."""
        paths = {root_folder_id: ""}
        
        def get_folder_name(folder_id):
            """Get folder name by ID"""
            try:
                folder = service.files().get(fileId=folder_id, fields="name").execute()
                return folder.get("name", "")
            except:
                return ""
        
        def walk(parent_id, parent_path, depth=0):
            query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            page_token = None
            subfolders = []
            while True:
                results = service.files().list(
                    q=query,
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token
                ).execute()
                subfolders.extend(results.get("files", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break
            
            for subfolder in subfolders:
                sub_id = subfolder["id"]
                sub_name = subfolder.get("name", "").strip()
                next_path = sub_name if not parent_path else parent_path + "/" + sub_name
                paths[sub_id] = next_path
                walk(sub_id, next_path, depth + 1)
        
        try:
            walk(root_folder_id, "")
        except Exception as e:
            print(f"✗ Error building folder paths: {e}")
        
        return paths

    @staticmethod
    async def get_all_drive_files_with_sizes(service, folder_id):
        """
        Get ALL image and video URLs from Drive folder (recursively) with their file sizes
        Returns: (drive_images, drive_videos) where each dict maps url -> {file_id, file_name, mime_type, drive_path, size}
        """
        print("\n→ Scanning all Drive folders for media files...")
        all_folder_ids = await GoogleDriveDownloader.get_all_folders_recursive(service, folder_id)
        
        print(f"✓ Found {len(all_folder_ids)} folder(s) (including root)")
        print("→ Building folder path mapping...")
        folder_paths = await GoogleDriveDownloader.build_folder_paths(service, folder_id)
        print("→ Collecting image and video URLs with sizes from Drive...\n")
        
        drive_images = {}
        drive_videos = {}
        total_images = 0
        total_videos = 0
        total_image_size = 0
        total_video_size = 0
        
        for idx, current_folder_id in enumerate(all_folder_ids, 1):
            try:
                # Query for both images and videos with size information
                query = (
                    f"'{current_folder_id}' in parents and "
                    f"(mimeType contains 'image/' or mimeType contains 'video/') and "
                    f"trashed=false"
                )
                
                # Handle pagination - Google Drive API returns max 100 files per request
                page_token = None
                all_items = []
                while True:
                    results = service.files().list(
                        q=query,
                        fields="nextPageToken, files(id, name, webViewLink, mimeType, parents, size)",
                        pageSize=100,  # Maximum allowed by API
                        pageToken=page_token
                    ).execute()
                    
                    items = results.get("files", [])
                    all_items.extend(items)
                    
                    page_token = results.get("nextPageToken")
                    if not page_token:
                        break
                
                folder_images = 0
                folder_videos = 0
                folder_image_size = 0
                folder_video_size = 0
                
                for item in all_items:
                    web_url = item["webViewLink"].strip().rstrip('/')
                    file_type = GoogleDriveDownloader.get_file_type(item["name"])
                    file_size = int(item.get("size", 0))  # Size in bytes
                    
                    # Get folder path
                    parent_ids = item.get("parents", [])
                    drive_path = ""
                    if parent_ids:
                        parent_id = parent_ids[0]
                        parent_path = folder_paths.get(parent_id, "")
                        file_name = item["name"]
                        drive_path = parent_path + "/" + file_name if parent_path else file_name
                    
                    if file_type == 'image':
                        drive_images[web_url] = {
                            "file_id": item["id"],
                            "file_name": item["name"],
                            "mime_type": item.get("mimeType", ""),
                            "drive_path": drive_path,
                            "size": file_size
                        }
                        folder_images += 1
                        folder_image_size += file_size
                    elif file_type == 'video':
                        drive_videos[web_url] = {
                            "file_id": item["id"],
                            "file_name": item["name"],
                            "mime_type": item.get("mimeType", ""),
                            "drive_path": drive_path,
                            "size": file_size
                        }
                        folder_videos += 1
                        folder_video_size += file_size
                
                if folder_images > 0 or folder_videos > 0:
                    total_images += folder_images
                    total_videos += folder_videos
                    total_image_size += folder_image_size
                    total_video_size += folder_video_size
                    print(f"→ Folder {idx}/{len(all_folder_ids)}: "
                          f"{folder_images} image(s) ({GoogleDriveDownloader.format_size(folder_image_size)}), "
                          f"{folder_videos} video(s) ({GoogleDriveDownloader.format_size(folder_video_size)})")
                    
            except Exception as e:
                print(f"✗ Error scanning folder {idx}: {e}")
        
        print(f"\n✓ Total media found in Drive:")
        print(f"  📷 Images: {total_images} ({GoogleDriveDownloader.format_size(total_image_size)})")
        print(f"  🎥 Videos: {total_videos} ({GoogleDriveDownloader.format_size(total_video_size)})")
        print(f"  📊 Total: {total_images + total_videos} ({GoogleDriveDownloader.format_size(total_image_size + total_video_size)})\n")
        
        return drive_images, drive_videos

    @staticmethod
    async def download_media_with_combined_limit(folder_id, db_manager, download_dir="input_files", max_workers=20, total_size_limit=None):
        """
        Download images and videos with a COMBINED total size limit
        
        Args:
            folder_id: Google Drive folder ID
            db_manager: Database manager instance
            download_dir: Directory to download files to
            max_workers: Number of parallel download workers
            total_size_limit: Total download size limit in bytes (None = no limit)
        
        Returns:
            (image_info, video_info): Lists of downloaded image and video info
        """
        # Create directories
        images_dir = os.path.join(download_dir, "images")
        videos_dir = os.path.join(download_dir, "videos")
        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(videos_dir, exist_ok=True)
        
        main_service = await GoogleDriveDownloader.authenticate()

        print("→ Loading cache from database...")
        existing_urls = GoogleDriveDownloader.load_existing_urls_from_db(db_manager)
        drive_images, drive_videos = await GoogleDriveDownloader.get_all_drive_files_with_sizes(main_service, folder_id)

        print("→ Comparing Drive files with database...")
        
        # Filter out already processed files
        images_to_download = {url: info for url, info in drive_images.items() if url not in existing_urls}
        videos_to_download = {url: info for url, info in drive_videos.items() if url not in existing_urls}

        # Combine all files into single list with type marker
        all_files = []
        for url, info in images_to_download.items():
            all_files.append({"url": url, "file_type": "image", **info})
        for url, info in videos_to_download.items():
            all_files.append({"url": url, "file_type": "video", **info})
        
        # Sort by size (smallest first = more files in one batch)
        all_files.sort(key=lambda x: x.get('size', 0))
        
        total_available_size = sum(f.get('size', 0) for f in all_files)

        print(f"\n{'='*60}")
        print(f"COMBINED DOWNLOAD PLAN")
        print(f"{'='*60}")
        print(f"Total files in Drive:      {len(drive_images) + len(drive_videos)}")
        print(f"  📷 Images:                {len(drive_images)}")
        print(f"  🎥 Videos:                {len(drive_videos)}")
        print(f"Already processed (DB):    {len(existing_urls)}")
        print(f"New files to download:     {len(all_files)} ({GoogleDriveDownloader.format_size(total_available_size)})")
        print(f"  📷 New images:            {len(images_to_download)}")
        print(f"  🎥 New videos:            {len(videos_to_download)}")
        
        # Apply combined size limit
        files_to_download = all_files
        if total_size_limit:
            print(f"Total download limit:      {GoogleDriveDownloader.format_size(total_size_limit)}")
            
            if total_available_size > total_size_limit:
                limited_files = []
                accumulated_size = 0
                
                for file_info in all_files:
                    file_size = file_info.get('size', 0)
                    if accumulated_size + file_size <= total_size_limit:
                        limited_files.append(file_info)
                        accumulated_size += file_size
                    else:
                        break
                
                limited_images = sum(1 for f in limited_files if f['file_type'] == 'image')
                limited_videos = sum(1 for f in limited_files if f['file_type'] == 'video')
                
                print(f"⚠️  Total size exceeds limit!")
                print(f"Limiting to:               {len(limited_files)} files ({GoogleDriveDownloader.format_size(accumulated_size)})")
                print(f"  📷 Images:                {limited_images}")
                print(f"  🎥 Videos:                {limited_videos}")
                print(f"Skipping for next batch:   {len(all_files) - len(limited_files)} files")
                
                files_to_download = limited_files
        
        print(f"{'='*60}\n")

        if not files_to_download:
            print("✓ No new files to download - all files already processed!")
            return [], []

        print(f"→ Starting parallel download of {len(files_to_download)} files using {max_workers} workers...\n")

        creds = main_service._http.credentials

        def _download_single_file(info):
            """Download a single file with optimized chunk size and retry logic"""
            file_id = info["file_id"]
            url = info["url"]
            file_name = info["file_name"]
            file_type = info["file_type"]
            
            # Determine output directory based on file type
            output_dir = images_dir if file_type == 'image' else videos_dir
            file_path = os.path.join(output_dir, file_name)

            # Handle duplicate filenames
            base, ext = os.path.splitext(file_name)
            counter = 1
            while os.path.exists(file_path):
                file_path = os.path.join(output_dir, f"{base}_{counter}{ext}")
                counter += 1

            for attempt in range(1, 4):
                try:
                    # Create a fresh service instance per thread
                    service = build("drive", "v3", credentials=creds, cache_discovery=False)
                    request = service.files().get_media(fileId=file_id)
                    
                    # Download directly without chunking - single request per file
                    file_content = request.execute()
                    
                    # Write to disk in one operation
                    with open(file_path, "wb") as f:
                        f.write(file_content)

                    return {
                        "file_path": file_path,
                        "url": url,
                        "file_name": file_name,
                        "file_type": file_type,
                        "drive_path": info.get("drive_path", ""),
                        "size": info.get("size", 0),
                        "status": "ok",
                    }

                except Exception as e:
                    err = str(e)
                    # Only retry on network errors
                    if any(x in err.lower() for x in ["ssl", "connection", "timeout", "reset", "broken pipe", "rate limit"]):
                        if attempt < 3:
                            wait_time = (2 ** attempt) * 0.5 + random.uniform(0.1, 0.5)
                            print(f"  ⚠️ [{attempt}/3] Retry {file_name[:30]}... after {wait_time:.1f}s")
                            time.sleep(wait_time)
                            continue
                    
                    # Non-retryable error or last attempt
                    return {
                        "file_path": None,
                        "url": url,
                        "file_name": file_name,
                        "file_type": file_type,
                        "drive_path": info.get("drive_path", ""),
                        "size": info.get("size", 0),
                        "status": "error",
                        "error": err[:200],
                    }

            return {
                "file_path": None,
                "url": url,
                "file_name": file_name,
                "file_type": file_type,
                "drive_path": info.get("drive_path", ""),
                "size": info.get("size", 0),
                "status": "error",
                "error": "Max retries reached",
            }

        image_info = []
        video_info = []
        failed = []
        downloaded_size = 0

        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_download_single_file, info): info for info in files_to_download}
            completed = 0
            total = len(futures)

            for future in as_completed(futures):
                completed += 1
                try:
                    res = future.result()
                    if res["status"] == "ok":
                        if res["file_type"] == "image":
                            image_info.append(res)
                        else:
                            video_info.append(res)
                        downloaded_size += res.get("size", 0)
                    else:
                        failed.append(res)
                except Exception as e:
                    failed.append({"file_name": "unknown", "url": "", "file_type": "unknown", "size": 0, "error": str(e)})

                # More frequent progress updates
                if completed % 5 == 0 or completed == total:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(f"  → Progress: {completed}/{total} ({rate:.1f} files/sec, "
                          f"{GoogleDriveDownloader.format_size(downloaded_size)} downloaded, {elapsed:.1f}s elapsed)")

        elapsed_total = time.time() - start_time

        print(f"\n{'='*60}")
        print(f"DOWNLOAD SUMMARY")
        print(f"{'='*60}")
        print(f"Successfully downloaded:   {len(image_info) + len(video_info)} files ({GoogleDriveDownloader.format_size(downloaded_size)})")
        print(f"  📷 Images:                {len(image_info)}")
        print(f"  🎥 Videos:                {len(video_info)}")
        print(f"Failed:                    {len(failed)}")
        print(f"Total time:                {elapsed_total:.1f} seconds")
        if elapsed_total > 0:
            print(f"Avg speed:                 {(len(image_info) + len(video_info))/elapsed_total:.1f} files/sec")
            print(f"Download speed:            {GoogleDriveDownloader.format_size(downloaded_size/elapsed_total)}/sec")
        print(f"{'='*60}\n")

        if failed:
            print("⚠️ Some downloads failed:")
            for f in failed[:10]:
                print(f"  - {f['file_name']}: {f.get('error', 'Unknown error')[:80]}")

        return image_info, video_info

    @staticmethod
    async def download_media_with_filters(
        folder_id,
        db_manager,
        download_dir="input_files",
        max_workers=25,
        video_min_size_bytes=None,
        image_size_limit_bytes=None,
        total_size_limit=None,
    ):
        """
        Download media with filters (same subfolder-wise scan as main):
        - video_min_size_bytes: only download videos with size >= this (e.g. 1GB). Skip smaller videos.
        - image_size_limit_bytes: cap total image download size to this (e.g. 500MB).
        - total_size_limit: optional combined cap for this batch (images + videos).
        Returns (image_info, video_info).
        """
        images_dir = os.path.join(download_dir, "images")
        videos_dir = os.path.join(download_dir, "videos")
        os.makedirs(images_dir, exist_ok=True)
        os.makedirs(videos_dir, exist_ok=True)

        main_service = await GoogleDriveDownloader.authenticate()
        print("→ Loading cache from database...")
        existing_urls = GoogleDriveDownloader.load_existing_urls_from_db(db_manager)
        drive_images, drive_videos = await GoogleDriveDownloader.get_all_drive_files_with_sizes(main_service, folder_id)

        print("→ Comparing Drive files with database...")
        images_to_download = {url: info for url, info in drive_images.items() if url not in existing_urls}
        videos_to_download = {url: info for url, info in drive_videos.items() if url not in existing_urls}

        # Filter videos: only >= video_min_size_bytes (e.g. 1GB minimum)
        if video_min_size_bytes is not None and video_min_size_bytes > 0:
            before = len(videos_to_download)
            videos_to_download = {url: info for url, info in videos_to_download.items() if info.get("size", 0) >= video_min_size_bytes}
            skipped = before - len(videos_to_download)
            if skipped:
                print(f"→ Videos filter: only >= {GoogleDriveDownloader.format_size(video_min_size_bytes)} → {len(videos_to_download)} videos (skipped {skipped} smaller)")

        # Filter images: cap total size to image_size_limit_bytes
        image_list = [{"url": url, "file_type": "image", **info} for url, info in images_to_download.items()]
        if image_size_limit_bytes is not None and image_size_limit_bytes > 0 and image_list:
            image_list.sort(key=lambda x: x.get("size", 0))
            capped = []
            acc = 0
            for f in image_list:
                sz = f.get("size", 0)
                if acc + sz <= image_size_limit_bytes:
                    capped.append(f)
                    acc += sz
                else:
                    break
            image_list = capped
            print(f"→ Image download limit: {GoogleDriveDownloader.format_size(image_size_limit_bytes)} → {len(image_list)} images ({GoogleDriveDownloader.format_size(acc)})")

        video_list = [{"url": url, "file_type": "video", **info} for url, info in videos_to_download.items()]
        all_files = image_list + video_list
        all_files.sort(key=lambda x: x.get("size", 0))

        total_available = sum(f.get("size", 0) for f in all_files)
        print(f"\n{'='*60}")
        print(f"FILTERED DOWNLOAD PLAN")
        print(f"{'='*60}")
        print(f"  📷 Images to download:   {len(image_list)} ({GoogleDriveDownloader.format_size(sum(f.get('size', 0) for f in image_list))})")
        print(f"  🎥 Videos to download:   {len(video_list)} ({GoogleDriveDownloader.format_size(sum(f.get('size', 0) for f in video_list))}) (only >= min size)")
        if total_size_limit:
            print(f"  Total batch limit:       {GoogleDriveDownloader.format_size(total_size_limit)}")
        print(f"{'='*60}\n")

        if total_size_limit and total_available > total_size_limit:
            limited = []
            acc = 0
            for f in all_files:
                sz = f.get("size", 0)
                if acc + sz <= total_size_limit:
                    limited.append(f)
                    acc += sz
                else:
                    break
            all_files = limited

        if not all_files:
            print("✓ No new files to download (after filters) or all already processed!")
            return [], []

        print(f"→ Starting parallel download of {len(all_files)} files using {max_workers} workers...\n")
        creds = main_service._http.credentials

        def _download_single(info):
            file_id = info["file_id"]
            url = info["url"]
            file_name = info["file_name"]
            file_type = info["file_type"]
            output_dir = images_dir if file_type == "image" else videos_dir
            file_path = os.path.join(output_dir, file_name)
            base, ext = os.path.splitext(file_name)
            c = 1
            while os.path.exists(file_path):
                file_path = os.path.join(output_dir, f"{base}_{c}{ext}")
                c += 1
            for attempt in range(1, 4):
                try:
                    service = build("drive", "v3", credentials=creds, cache_discovery=False)
                    content = service.files().get_media(fileId=file_id).execute()
                    with open(file_path, "wb") as fp:
                        fp.write(content)
                    return {"file_path": file_path, "url": url, "file_name": file_name, "file_type": file_type, "drive_path": info.get("drive_path", ""), "size": info.get("size", 0), "status": "ok"}
                except Exception as e:
                    err = str(e)
                    if any(x in err.lower() for x in ["ssl", "connection", "timeout", "reset", "broken pipe", "rate limit"]) and attempt < 3:
                        time.sleep((2 ** attempt) * 0.5 + random.uniform(0.1, 0.5))
                        continue
                    return {"file_path": None, "url": url, "file_name": file_name, "file_type": file_type, "drive_path": info.get("drive_path", ""), "size": info.get("size", 0), "status": "error", "error": err[:200]}
            return {"file_path": None, "url": url, "file_name": file_name, "file_type": file_type, "drive_path": info.get("drive_path", ""), "size": info.get("size", 0), "status": "error", "error": "Max retries"}

        image_info = []
        video_info = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_download_single, f): f for f in all_files}
            for future in as_completed(futures):
                try:
                    res = future.result()
                    if res["status"] == "ok":
                        if res["file_type"] == "image":
                            image_info.append(res)
                        else:
                            video_info.append(res)
                except Exception as e:
                    pass
        print(f"✓ Downloaded: {len(image_info)} images, {len(video_info)} videos\n")
        return image_info, video_info