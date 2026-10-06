"""
MySQL Database Manager
Handles all database operations including connection pooling, table creation, and CRUD operations
Updated to support both images and videos

CONFIGURATION OPTIONS:
- Local Database: Comment out SSH tunnel code (default)
- Production Database: Uncomment SSH tunnel code
"""

import os
import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv
# from sshtunnel import SSHTunnelForwarder  # Uncomment for production with SSH tunnel

load_dotenv()


# ============================================================================
# SSH TUNNEL CONFIGURATION (FOR PRODUCTION)
# ============================================================================
# Uncomment this function and the tunnel initialization in __init__ for production
"""
def start_ssh_tunnel():
    '''Start SSH tunnel to forward MySQL connection through SSH'''
    tunnel = SSHTunnelForwarder(
        (os.getenv("SSH_HOST"), 22),
        ssh_username=os.getenv("SSH_USER"),
        ssh_pkey=os.getenv("SSH_PEM_PATH"),
        remote_bind_address=('127.0.0.1', 3306),
        local_bind_address=('127.0.0.1', int(os.getenv("DB_PORT")))
    )
    tunnel.start()
    print("SSH Tunnel Started → localhost:", tunnel.local_bind_port)
    return tunnel
"""


class DatabaseManager:
    """Manages MySQL database connections and operations"""

    def __init__(self):
        """Initialize database connection pool"""
        
        # ====================================================================
        # FOR PRODUCTION: Uncomment the lines below to enable SSH tunnel
        # ====================================================================
        # self.tunnel = start_ssh_tunnel()
        
        # ====================================================================
        # LOCAL DATABASE CONFIGURATION (Default)
        # ====================================================================
        # For local MySQL, connect directly without SSH tunnel
        self.config = {
            'host': os.getenv('DB_HOST', 'localhost'),  # Use DB_HOST from .env or default to localhost
            'port': int(os.getenv('DB_PORT', '3306')),  # Use DB_PORT from .env or default to 3306
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME'),
            'pool_name': 'image_processor_pool',
            'pool_size': 10,
            'pool_reset_session': True
        }
        
        # ====================================================================
        # PRODUCTION DATABASE CONFIGURATION (Uncomment for production)
        # ====================================================================
        # For production with SSH tunnel, use 127.0.0.1 to connect through tunnel
        """
        self.config = {
            'host': '127.0.0.1',  # Connect through SSH tunnel
            'port': int(os.getenv('DB_PORT')),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'database': os.getenv('DB_NAME'),
            'pool_name': 'image_processor_pool',
            'pool_size': 10,
            'pool_reset_session': True
        }
        """

        print(f"\n→ Connecting to MySQL database...")
        print(f"   Host: {self.config['host']}:{self.config['port']}")
        print(f"   Database: {self.config['database']}")

        try:
            # Create database if not exists
            self._create_database_if_not_exists()

            # Create connection pool
            self.pool = mysql.connector.pooling.MySQLConnectionPool(**self.config)

            # Create tables
            self._create_tables()

            print(f"✓ Database connected successfully\n")

        except mysql.connector.Error as e:
            print(f"✗ Database connection failed: {e}")
            # Uncomment for production with SSH tunnel
            # if hasattr(self, 'tunnel') and self.tunnel:
            #     try:
            #         self.tunnel.stop()
            #     except:
            #         pass
            raise
        except Exception as e:
            print(f"✗ Database initialization failed: {e}")
            # Uncomment for production with SSH tunnel
            # if hasattr(self, 'tunnel') and self.tunnel:
            #     try:
            #         self.tunnel.stop()
            #     except:
            #         pass
            raise

    # -------------------------------------------------------------------
    # URL NORMALIZATION
    # -------------------------------------------------------------------
    @staticmethod
    def normalize_drive_url(url: str) -> str:
        """
        Normalize Google Drive URLs to a consistent format using file ID only.
        """
        if not url or "drive.google.com" not in url:
            return url
        
        if "open?id=" in url:
            file_id = url.split("open?id=")[1].split("&")[0]
        elif "/file/d/" in url:
            file_id = url.split("/file/d/")[1].split("/")[0]
        elif "id=" in url:
            file_id = url.split("id=")[1].split("&")[0]
        else:
            return url
        
        return file_id

    # -------------------------------------------------------------------
    # CREATE DATABASE
    # -------------------------------------------------------------------
    def _create_database_if_not_exists(self):
        """Create database if it doesn't exist"""
        temp_config = self.config.copy()
        temp_config.pop('database')
        temp_config.pop('pool_name')
        temp_config.pop('pool_size')
        temp_config.pop('pool_reset_session')

        conn = mysql.connector.connect(**temp_config)
        cursor = conn.cursor()

        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS {self.config['database']} "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )

        cursor.close()
        conn.close()

    # -------------------------------------------------------------------
    # CREATE TABLES
    # -------------------------------------------------------------------
    def _create_tables(self):
        """Create all required tables including videos table"""
        conn = self.pool.get_connection()
        cursor = conn.cursor()

        # -------------------------
        # PLAYERS TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                player_id VARCHAR(20) PRIMARY KEY,
                player_name VARCHAR(191) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_player_name (player_name(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # EVENTS TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id VARCHAR(20) PRIMARY KEY,
                event_name VARCHAR(191) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_event_name (event_name(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # IMAGES TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INT AUTO_INCREMENT PRIMARY KEY,
                file_name VARCHAR(500) NOT NULL,
                image_path VARCHAR(1000),
                url VARCHAR(1000) NOT NULL,
                drive_link VARCHAR(1000),
                tournament VARCHAR(200),
                player_ids VARCHAR(500),
                date_time_original DATETIME,
                date DATE,
                time_of_day VARCHAR(50),
                no_of_faces INT DEFAULT 0,
                apparel VARCHAR(100),
                focus VARCHAR(100),
                shot_type VARCHAR(100),
                event_ids VARCHAR(200),
                mood VARCHAR(500),
                action TEXT,
                location VARCHAR(500),
                jersey_color VARCHAR(500),
                apparels_seen TEXT,
                crowd_present VARCHAR(50),
                caption TEXT,
                brands_and_logos TEXT,
                camera_make VARCHAR(100),
                camera_model VARCHAR(100),
                copyright VARCHAR(255),
                photographer VARCHAR(255),
                input_tokens INT,
                output_tokens INT,
                total_tokens INT,
                processing_time FLOAT,
                status VARCHAR(50),
                error_message TEXT,
                api_key_used VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

                UNIQUE KEY unique_url (url(191)),
                INDEX idx_date (date),
                INDEX idx_status (status),
                INDEX idx_player_ids (player_ids(191)),
                INDEX idx_event_ids (event_ids(191)),
                INDEX idx_tournament (tournament(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # Add tournament column if it doesn't exist (migration for existing tables)
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'images' 
                AND COLUMN_NAME = 'tournament'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE images 
                    ADD COLUMN tournament VARCHAR(200) AFTER url
                """)
                # Add index if it doesn't exist
                try:
                    cursor.execute("""
                        ALTER TABLE images 
                        ADD INDEX idx_tournament (tournament(191))
                    """)
                except mysql.connector.Error:
                    # Index might already exist, ignore
                    pass
                print("✓ Added tournament column to images table")
        except Exception as e:
            print(f"⚠️ Migration warning (tournament column): {e}")

        # Add image_path column if it doesn't exist
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'images' 
                AND COLUMN_NAME = 'image_path'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE images 
                    ADD COLUMN image_path VARCHAR(1000) AFTER file_name
                """)
                print("✓ Added image_path column to images table")
        except Exception as e:
            print(f"⚠️ Migration warning (image_path column): {e}")

        # Add drive_link column if it doesn't exist
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'images' 
                AND COLUMN_NAME = 'drive_link'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE images 
                    ADD COLUMN drive_link VARCHAR(1000) AFTER url
                """)
                print("✓ Added drive_link column to images table")
        except Exception as e:
            print(f"⚠️ Migration warning (drive_link column): {e}")

        # -------------------------
        # VIDEOS TABLE (NEW)
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                file_name VARCHAR(500) NOT NULL,
                url VARCHAR(1000) NOT NULL,
                video_path VARCHAR(1000) COMMENT 'Path to video file',
                tournament VARCHAR(200),
                player_ids VARCHAR(500) COMMENT 'Comma-separated player IDs',
                datetime DATETIME,
                date DATE,
                time_of_day VARCHAR(50),
                no_of_faces INT DEFAULT 0,
                video_summary TEXT COMMENT 'AI-generated video summary (50-75 words)',
                caption TEXT COMMENT 'Primary tag from AI analysis (5 words max)',
                
                keywords TEXT COMMENT 'Searchable keywords from AI (comma-separated)',
                status VARCHAR(50) DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

                UNIQUE KEY unique_url (url(191)),
                INDEX idx_date (date),
                INDEX idx_status (status),
                INDEX idx_player_ids (player_ids(191)),
                INDEX idx_tournament (tournament(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # Migration: Rename image_path to video_path and remove thumbnail column if they exist
        try:
            # Check if image_path exists
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'videos' 
                AND COLUMN_NAME = 'image_path'
            """)
            if cursor.fetchone()[0] > 0:
                # Check if video_path doesn't exist yet
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.COLUMNS 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME = 'videos' 
                    AND COLUMN_NAME = 'video_path'
                """)
                if cursor.fetchone()[0] == 0:
                    cursor.execute("""
                        ALTER TABLE videos 
                        CHANGE COLUMN image_path video_path VARCHAR(1000) COMMENT 'Path to video file'
                    """)
                    print("✓ Renamed image_path to video_path in videos table")
            
            # Remove thumbnail column if it exists
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'videos' 
                AND COLUMN_NAME = 'thumbnail'
            """)
            if cursor.fetchone()[0] > 0:
                cursor.execute("""
                    ALTER TABLE videos 
                    DROP COLUMN thumbnail
                """)
                print("✓ Removed thumbnail column from videos table")
        except Exception as e:
            print(f"⚠️ Migration warning (video_path/thumbnail): {e}")

        # Add time_of_day column to videos if missing
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'videos'
                AND COLUMN_NAME = 'time_of_day'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE videos
                    ADD COLUMN time_of_day VARCHAR(50) AFTER date
                """)
                print("✓ Added time_of_day column to videos table")
        except Exception as e:
            print(f"⚠️ Migration warning (videos.time_of_day): {e}")

        # Add no_of_faces column to videos if missing
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'videos'
                AND COLUMN_NAME = 'no_of_faces'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE videos
                    ADD COLUMN no_of_faces INT DEFAULT 0 AFTER time_of_day
                """)
                print("✓ Added no_of_faces column to videos table")
        except Exception as e:
            print(f"⚠️ Migration warning (videos.no_of_faces): {e}")

        # Add transcribe column to videos if missing
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'videos'
                AND COLUMN_NAME = 'transcribe'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE videos
                    ADD COLUMN transcribe TEXT COMMENT 'Audio transcript (max chars applied before save)' AFTER keywords
                """)
                print("✓ Added transcribe column to videos table")
        except Exception as e:
            print(f"⚠️ Migration warning (videos.transcribe): {e}")

        # Add action column to videos if missing
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'videos'
                AND COLUMN_NAME = 'action'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE videos
                    ADD COLUMN action TEXT COMMENT 'Action tags from frame analysis' AFTER transcribe
                """)
                print("✓ Added action column to videos table")
        except Exception as e:
            print(f"⚠️ Migration warning (videos.action): {e}")

        # Add mood column to videos if missing
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'videos'
                AND COLUMN_NAME = 'mood'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE videos
                    ADD COLUMN mood VARCHAR(500) COMMENT 'Mood/emotion tags' AFTER action
                """)
                print("✓ Added mood column to videos table")
        except Exception as e:
            print(f"⚠️ Migration warning (videos.mood): {e}")

        # Add event column to videos if missing
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'videos'
                AND COLUMN_NAME = 'event'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE videos
                    ADD COLUMN event VARCHAR(500) COMMENT 'Event/context tags' AFTER mood
                """)
                print("✓ Added event column to videos table")
        except Exception as e:
            print(f"⚠️ Migration warning (videos.event): {e}")

        # -------------------------
        # THUMBNAILS TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thumbnails (
                id INT AUTO_INCREMENT PRIMARY KEY,
                file_id VARCHAR(191) NOT NULL COMMENT 'Normalized Google Drive file ID',
                original_url VARCHAR(1000) NOT NULL COMMENT 'Original URL for reference',
                thumbnail_data MEDIUMBLOB NOT NULL,
                width INT,
                height INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_file_id (file_id),
                INDEX idx_file_id (file_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # UNKNOWN FACES TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS unknown_faces (
                id INT AUTO_INCREMENT PRIMARY KEY,
                file_name VARCHAR(500) NOT NULL,
                url VARCHAR(1000) NOT NULL,
                player_name VARCHAR(50) DEFAULT 'Unknown',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_url (url(191)),
                INDEX idx_url (url(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # UNKNOWN FACES VIDEO TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS unknown_faces_video (
                id INT AUTO_INCREMENT PRIMARY KEY,
                file_name VARCHAR(500) NOT NULL,
                url VARCHAR(1000) NOT NULL,
                video_path VARCHAR(1000) COMMENT 'Path to video file',
                tournament VARCHAR(200),
                player_ids VARCHAR(500) COMMENT 'Comma-separated player IDs (Unknown)',
                datetime DATETIME,
                date DATE,
                time_of_day VARCHAR(50),
                no_of_faces INT DEFAULT 0,
                video_summary TEXT COMMENT 'AI-generated video summary (15 words max)',
                caption TEXT COMMENT 'Primary tag from AI analysis (15 words max)',
                keywords TEXT COMMENT 'Searchable keywords from AI (comma-separated)',
                status VARCHAR(50) DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_url (url(191)),
                INDEX idx_date (date),
                INDEX idx_status (status),
                INDEX idx_player_ids (player_ids(191)),
                INDEX idx_tournament (tournament(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # Ensure new metadata columns exist in unknown_faces_video
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'unknown_faces_video'
                AND COLUMN_NAME = 'time_of_day'
            """)
            time_col_exists = cursor.fetchone()[0] > 0

            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = 'unknown_faces_video'
                AND COLUMN_NAME = 'no_of_faces'
            """)
            faces_col_exists = cursor.fetchone()[0] > 0

            if not time_col_exists:
                cursor.execute("""
                    ALTER TABLE unknown_faces_video
                    ADD COLUMN time_of_day VARCHAR(50) AFTER date
                """)
                print("✓ Added time_of_day column to unknown_faces_video table")

            if not faces_col_exists:
                cursor.execute("""
                    ALTER TABLE unknown_faces_video
                    ADD COLUMN no_of_faces INT DEFAULT 0 AFTER time_of_day
                """)
                print("✓ Added no_of_faces column to unknown_faces_video table")
        except Exception as e:
            print(f"⚠️ Migration warning (unknown_faces_video metadata): {e}")

        # Add transcribe, action, mood, event columns to unknown_faces_video if missing
        for col, col_def in [
            ('transcribe', "ADD COLUMN transcribe TEXT COMMENT 'Audio transcript (max chars applied)' AFTER keywords"),
            ('action', "ADD COLUMN action TEXT COMMENT 'Action tags' AFTER transcribe"),
            ('mood', "ADD COLUMN mood VARCHAR(500) COMMENT 'Mood tags' AFTER action"),
            ('event', "ADD COLUMN event VARCHAR(500) COMMENT 'Event tags' AFTER mood"),
        ]:
            try:
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = 'unknown_faces_video'
                    AND COLUMN_NAME = %s
                """, (col,))
                if cursor.fetchone()[0] == 0:
                    cursor.execute(f"ALTER TABLE unknown_faces_video {col_def}")
                    print(f"✓ Added {col} column to unknown_faces_video table")
            except Exception as e:
                print(f"⚠️ Migration warning (unknown_faces_video.{col}): {e}")

        # -------------------------
        # PROCESSING CACHE TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processing_cache (
                url VARCHAR(1000),
                file_name VARCHAR(500),
                file_type VARCHAR(20) COMMENT 'image or video',
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (url(191)),
                INDEX idx_processed_at (processed_at),
                INDEX idx_file_type (file_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # Add file_type column if it doesn't exist (migration for existing tables)
        try:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'processing_cache' 
                AND COLUMN_NAME = 'file_type'
            """)
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                    ALTER TABLE processing_cache 
                    ADD COLUMN file_type VARCHAR(20) COMMENT 'image or video' AFTER file_name
                """)
                # Add index if it doesn't exist
                try:
                    cursor.execute("""
                        ALTER TABLE processing_cache 
                        ADD INDEX idx_file_type (file_type)
                    """)
                except mysql.connector.Error:
                    # Index might already exist, ignore
                    pass
                print("✓ Added file_type column to processing_cache table")
        except Exception as e:
            print(f"⚠️ Migration warning (file_type column): {e}")

        # -------------------------
        # USER BOOKMARKS TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_bookmarks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                image_id INT NOT NULL,
                user_name VARCHAR(191) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_user_bookmark (user_name, image_id),
                INDEX idx_user_bookmarks_image (image_id),
                INDEX idx_user_bookmarks_user (user_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # USER FAVORITES TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_favorites (
                id INT AUTO_INCREMENT PRIMARY KEY,
                image_id INT NOT NULL,
                user_name VARCHAR(191) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_user_favorite (user_name, image_id),
                INDEX idx_user_favorites_image (image_id),
                INDEX idx_user_favorites_user (user_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # USER FEEDBACK TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INT AUTO_INCREMENT PRIMARY KEY,
                image_id INT NULL,
                file_name VARCHAR(500),
                url VARCHAR(1000),
                user_name VARCHAR(191) NOT NULL,
                original_player_name VARCHAR(191),
                requested_player_name VARCHAR(191),
                context TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_feedback_image (image_id),
                INDEX idx_user_feedback_user (user_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # USER QUESTIONS TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_questions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_name VARCHAR(191),
                question_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_questions_user (user_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # USER QUESTION FEEDBACK TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_question_feedback (
                id INT AUTO_INCREMENT PRIMARY KEY,
                question_id INT NOT NULL,
                user_name VARCHAR(191),
                feedback_type ENUM('thumbs_up','thumbs_down') NOT NULL,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_uqf_question (question_id),
                INDEX idx_uqf_user (user_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # -------------------------
        # USER SEARCH LOG TABLE
        # -------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_search_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_name VARCHAR(191) NOT NULL,
                search_query TEXT NOT NULL,
                feedback ENUM('up', 'down', 'none') NOT NULL DEFAULT 'none',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_user_search_log_user (user_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.commit()
        cursor.close()
        conn.close()

        print("✓ Database tables created/verified")

    # -------------------------------------------------------------------
    # GET ALL PROCESSED URLS
    # -------------------------------------------------------------------
    def get_processed_urls(self):
        """Get all previously processed URLs from cache"""
        conn = self.pool.get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT url FROM processing_cache")
        urls = {row[0].strip().rstrip('/') for row in cursor.fetchall()}

        cursor.close()
        conn.close()

        return urls

    # -------------------------------------------------------------------
    # PLAYER HELPERS
    # -------------------------------------------------------------------
    def get_or_create_player_id(self, player_name):
        """Get existing player ID or create new one"""
        conn = self.pool.get_connection()
        cursor = conn.cursor()

        player_name = player_name.strip()

        cursor.execute("SELECT player_id FROM players WHERE player_name = %s", (player_name,))
        result = cursor.fetchone()

        if result:
            cursor.close()
            conn.close()
            return result[0]

        cursor.execute("SELECT COUNT(*) FROM players")
        count = cursor.fetchone()[0]
        player_id = f"p{count + 1}"

        try:
            cursor.execute(
                "INSERT INTO players (player_id, player_name) VALUES (%s, %s)",
                (player_id, player_name)
            )
            conn.commit()
        except mysql.connector.IntegrityError:
            conn.rollback()
            cursor.execute("SELECT player_id FROM players WHERE player_name = %s", (player_name,))
            player_id = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return player_id

    # -------------------------------------------------------------------
    # EVENT HELPERS
    # -------------------------------------------------------------------
    def get_or_create_event_id(self, event_name):
        """Get existing event ID or create new one"""
        conn = self.pool.get_connection()
        cursor = conn.cursor()

        event_name = event_name.strip()

        cursor.execute("SELECT event_id FROM events WHERE event_name = %s", (event_name,))
        result = cursor.fetchone()

        if result:
            cursor.close()
            conn.close()
            return result[0]

        cursor.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        event_id = f"e{count + 1}"

        try:
            cursor.execute(
                "INSERT INTO events (event_id, event_name) VALUES (%s, %s)",
                (event_id, event_name)
            )
            conn.commit()
        except mysql.connector.IntegrityError:
            conn.rollback()
            cursor.execute("SELECT event_id FROM events WHERE event_name = %s", (event_name,))
            event_id = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return event_id

    # -------------------------------------------------------------------
    # SAVE THUMBNAIL
    # -------------------------------------------------------------------
    def save_thumbnail(self, url, thumbnail_data, width, height):
        """Save thumbnail binary data to database using normalized file ID"""
        conn = self.pool.get_connection()
        cursor = conn.cursor()

        try:
            file_id = self.normalize_drive_url(url)
            
            cursor.execute("""
                INSERT INTO thumbnails (file_id, original_url, thumbnail_data, width, height)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    original_url = VALUES(original_url),
                    thumbnail_data = VALUES(thumbnail_data),
                    width = VALUES(width),
                    height = VALUES(height)
            """, (file_id, url, thumbnail_data, width, height))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"✗ Failed to save thumbnail for {url}: {e}")
        finally:
            cursor.close()
            conn.close()

    # -------------------------------------------------------------------
    # GET THUMBNAIL
    # -------------------------------------------------------------------
    def get_thumbnail(self, url):
        """Retrieve thumbnail binary data from database using normalized file ID"""
        conn = self.pool.get_connection()
        cursor = conn.cursor()

        try:
            file_id = self.normalize_drive_url(url)
            
            cursor.execute("""
                SELECT thumbnail_data, width, height 
                FROM thumbnails 
                WHERE file_id = %s
            """, (file_id,))
            
            result = cursor.fetchone()
            
            if result:
                return {
                    'data': result[0],
                    'width': result[1],
                    'height': result[2]
                }
            return None
        finally:
            cursor.close()
            conn.close()

    # -------------------------------------------------------------------
    # SAVE IMAGES BATCH
    # -------------------------------------------------------------------
    def save_images_batch(self, results):
        """Save batch of image results to database"""
        if not results:
            return

        conn = self.pool.get_connection()
        cursor = conn.cursor()

        for idx, result in enumerate(results, 1):
            # ADD DEBUG HERE:
            print(f"\n🔍 DEBUG - Saving image {idx}/{len(results)}: {result.get('file_name')}")
            print(f"  Player Name: '{result.get('Player Name')}'")
            print(f"  caption: '{result.get('caption')}'")
            print(f"  url: '{result.get('url')}'")
            
            # Validate critical fields
            if not result.get('file_name'):
                print(f"  ⚠️ WARNING: Empty file_name")
            if not result.get('url'):
                print(f"  ⚠️ WARNING: Empty url")
            
            # Player IDs
            player_ids = None
            if result.get('Player Name'):
                names = [n.strip() for n in str(result['Player Name']).split(',') if n.strip()]
                if names:
                    ids = [self.get_or_create_player_id(name) for name in names]
                    player_ids = ','.join(ids)

            # Event IDs
            event_ids = None
            if result.get('event_type'):
                names = [n.strip() for n in str(result['event_type']).split(',') if n.strip()]
                if names:
                    ids = [self.get_or_create_event_id(name) for name in names]
                    event_ids = ','.join(ids)

            # Prepare all values, ensuring None for missing fields
            values = (
                result.get('file_name'),
                result.get('image_path'),
                result.get('url'),
                result.get('drive_link'),
                result.get('tournament'),
                player_ids,
                result.get('DateTimeOriginal'),
                result.get('Date'),
                result.get('TimeOfDay'),
                result.get('NoOfFaces', 0),
                result.get('apparel'),
                result.get('Focus'),
                result.get('Shot Type'),
                event_ids,
                result.get('mood'),
                result.get('action'),
                result.get('location'),
                result.get('jersey_color'),
                result.get('accessories_seen'),
                result.get('crowd_present'),
                result.get('caption'),
                result.get('logos_branding'),
                result.get('Camera Make'),
                result.get('Camera Model'),
                result.get('Copyright'),
                result.get('Photographer'),
                result.get('input_tokens'),
                result.get('output_tokens'),
                result.get('total_tokens'),
                result.get('processing_time'),
                result.get('status'),
                result.get('error_message'),
                result.get('api_key_used')
            )

            try:
                cursor.execute("""
                INSERT INTO images (
                    file_name,
                    image_path,
                    url,
                    drive_link,
                    tournament,
                    player_ids,
                    date_time_original,
                    date,
                    time_of_day,
                    no_of_faces,
                    apparel,
                    focus,
                    shot_type,
                    event_ids,
                    mood,
                    action,
                    location,
                    jersey_color,
                    apparels_seen,
                    crowd_present,
                    caption,
                    brands_and_logos,
                    camera_make,
                    camera_model,
                    copyright,
                    photographer,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    processing_time,
                    status,
                    error_message,
                    api_key_used
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON DUPLICATE KEY UPDATE
                    file_name = VALUES(file_name),
                    image_path = VALUES(image_path),
                    drive_link = VALUES(drive_link),
                    tournament = VALUES(tournament),
                    player_ids = VALUES(player_ids),
                    date_time_original = VALUES(date_time_original),
                    date = VALUES(date),
                    time_of_day = VALUES(time_of_day),
                    no_of_faces = VALUES(no_of_faces),
                    apparel = VALUES(apparel),
                    focus = VALUES(focus),
                    shot_type = VALUES(shot_type),
                    event_ids = VALUES(event_ids),
                    mood = VALUES(mood),
                    action = VALUES(action),
                    location = VALUES(location),
                    jersey_color = VALUES(jersey_color),
                    apparels_seen = VALUES(apparels_seen),
                    crowd_present = VALUES(crowd_present),
                    caption = VALUES(caption),
                    brands_and_logos = VALUES(brands_and_logos),
                    camera_make = VALUES(camera_make),
                    camera_model = VALUES(camera_model),
                    copyright = VALUES(copyright),
                    photographer = VALUES(photographer),
                    input_tokens = VALUES(input_tokens),
                    output_tokens = VALUES(output_tokens),
                    total_tokens = VALUES(total_tokens),
                    processing_time = VALUES(processing_time),
                    status = VALUES(status),
                    error_message = VALUES(error_message),
                    api_key_used = VALUES(api_key_used)
                """, values)
                
                print(f"  ✓ SQL executed successfully for {result.get('file_name')}")
                
            except Exception as e:
                print(f"  ✗ SQL ERROR for {result.get('file_name')}: {e}")
                raise

            # Save to cache
            cursor.execute("""
                INSERT INTO processing_cache (url, file_name, file_type)
                VALUES (%s, %s, 'image')
                ON DUPLICATE KEY UPDATE file_name = VALUES(file_name), file_type = 'image'
            """, (result.get('url'), result.get('file_name')))

        conn.commit()
        cursor.close()
        conn.close()

    # -------------------------------------------------------------------
    # SAVE VIDEOS BATCH (NEW)
    # -------------------------------------------------------------------
    def save_videos_batch(self, results):
        """Save batch of video results to database"""
        if not results:
            return

        conn = self.pool.get_connection()
        cursor = conn.cursor()

        for idx, result in enumerate(results, 1):
            # ADD DEBUG HERE:
            print(f"\n🔍 DEBUG - Saving video {idx}/{len(results)}: {result.get('file_name')}")
            print(f"  caption: '{result.get('caption')}'")
            print(f"  video_summary: '{result.get('video_summary')}'")
            print(f"  keywords: '{result.get('keywords')}'")
            
            # Validate critical fields
            if not result.get('caption'):
                print(f"  ⚠️ WARNING: Empty caption, using fallback")
                result['caption'] = 'Cricket Video'
            if not result.get('video_summary'):
                print(f"  ⚠️ WARNING: Empty summary, using fallback")
                result['video_summary'] = 'Cricket training session'
            if not result.get('keywords'):
                print(f"  ⚠️ WARNING: Empty keywords, using fallback")
                result['keywords'] = 'cricket'
            
            # Player IDs
            player_ids = None
            if result.get('player_names'):
                names = result['player_names']
                ids = [self.get_or_create_player_id(name) for name in names]
                player_ids = ','.join(ids)

            try:
                cursor.execute("""
                    INSERT INTO videos (
                        file_name, url, video_path, tournament, player_ids, datetime, date,
                        time_of_day, no_of_faces, video_summary, caption, keywords,
                        transcribe, action, mood, event,
                        status, error_message
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s
                    ) ON DUPLICATE KEY UPDATE
                        file_name = VALUES(file_name),
                        video_path = VALUES(video_path),
                        tournament = VALUES(tournament),
                        player_ids = VALUES(player_ids),
                        datetime = VALUES(datetime),
                        date = VALUES(date),
                        time_of_day = VALUES(time_of_day),
                        no_of_faces = VALUES(no_of_faces),
                        video_summary = VALUES(video_summary),
                        caption = VALUES(caption),
                        keywords = VALUES(keywords),
                        transcribe = VALUES(transcribe),
                        action = VALUES(action),
                        mood = VALUES(mood),
                        event = VALUES(event),
                        status = VALUES(status),
                        error_message = VALUES(error_message)
                """, (
                    result.get('file_name'),
                    result.get('url'),
                    result.get('video_path'),
                    result.get('tournament'),
                    player_ids,
                    result.get('datetime'),
                    result.get('date'),
                    result.get('time_of_day'),
                    result.get('no_of_faces', 0),
                    result.get('video_summary'),
                    result.get('caption'),
                    result.get('keywords'),
                    result.get('transcribe'),
                    result.get('action'),
                    result.get('mood'),
                    result.get('event'),
                    result.get('status', 'completed'),
                    result.get('error_message')
                ))
                
                print(f"  ✓ SQL executed successfully for {result.get('file_name')}")
                
            except Exception as e:
                print(f"  ✗ SQL ERROR for {result.get('file_name')}: {e}")
                raise

            # Save to cache
            cursor.execute("""
                INSERT INTO processing_cache (url, file_name, file_type)
                VALUES (%s, %s, 'video')
                ON DUPLICATE KEY UPDATE file_name = VALUES(file_name), file_type = 'video'
            """, (result.get('url'), result.get('file_name')))

        conn.commit()
        cursor.close()
        conn.close()

    # -------------------------------------------------------------------
    # SAVE UNKNOWN FACES
    # -------------------------------------------------------------------
    def save_unknown_faces_batch(self, unknown_faces):
        """Save unknown faces to database"""
        if not unknown_faces:
            return

        conn = self.pool.get_connection()
        cursor = conn.cursor()

        for face in unknown_faces:
            cursor.execute("""
                INSERT INTO unknown_faces (file_name, url, player_name)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    file_name = VALUES(file_name),
                    player_name = VALUES(player_name)
            """, (
                face.get('file_name'),
                face.get('url'),
                face.get('Player Name', 'Unknown')
            ))

            cursor.execute("""
                INSERT INTO processing_cache (url, file_name, file_type)
                VALUES (%s, %s, 'image')
                ON DUPLICATE KEY UPDATE file_name = VALUES(file_name), file_type = 'image'
            """, (face.get('url'), face.get('file_name')))

        conn.commit()
        cursor.close()
        conn.close()

    # -------------------------------------------------------------------
    # SAVE UNKNOWN FACES VIDEO BATCH
    # -------------------------------------------------------------------
    def save_unknown_faces_video_batch(self, results):
        """Save batch of unknown faces video results to database"""
        if not results:
            return

        conn = self.pool.get_connection()
        cursor = conn.cursor()

        for result in results:
            # Player IDs - set to Unknown
            player_ids = None
            if result.get('player_names'):
                # If player_names is empty list or contains only Unknown, set to Unknown
                names = result['player_names']
                if not names or (len(names) == 1 and names[0].lower() == 'unknown'):
                    player_ids = self.get_or_create_player_id('Unknown')
                else:
                    ids = [self.get_or_create_player_id(name) for name in names]
                    player_ids = ','.join(ids)
            else:
                # No players detected - set to Unknown
                player_ids = self.get_or_create_player_id('Unknown')

            cursor.execute("""
                INSERT INTO unknown_faces_video (
                    file_name, url, video_path, tournament, player_ids, datetime, date,
                    time_of_day, no_of_faces, video_summary, caption, keywords,
                    transcribe, action, mood, event,
                    status, error_message
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                ) ON DUPLICATE KEY UPDATE
                    file_name = VALUES(file_name),
                    video_path = VALUES(video_path),
                    tournament = VALUES(tournament),
                    player_ids = VALUES(player_ids),
                    datetime = VALUES(datetime),
                    date = VALUES(date),
                    time_of_day = VALUES(time_of_day),
                    no_of_faces = VALUES(no_of_faces),
                    video_summary = VALUES(video_summary),
                    caption = VALUES(caption),
                    keywords = VALUES(keywords),
                    transcribe = VALUES(transcribe),
                    action = VALUES(action),
                    mood = VALUES(mood),
                    event = VALUES(event),
                    status = VALUES(status),
                    error_message = VALUES(error_message)
            """, (
                result.get('file_name'),
                result.get('url'),
                result.get('video_path'),
                result.get('tournament'),
                player_ids,
                result.get('datetime'),
                result.get('date'),
                result.get('time_of_day'),
                result.get('no_of_faces', 0),
                result.get('video_summary'),
                result.get('caption'),
                result.get('keywords'),
                result.get('transcribe'),
                result.get('action'),
                result.get('mood'),
                result.get('event'),
                result.get('status', 'completed'),
                result.get('error_message')
            ))

            # Save to cache
            cursor.execute("""
                INSERT INTO processing_cache (url, file_name, file_type)
                VALUES (%s, %s, 'video')
                ON DUPLICATE KEY UPDATE file_name = VALUES(file_name), file_type = 'video'
            """, (result.get('url'), result.get('file_name')))

        conn.commit()
        cursor.close()
        conn.close()

    # -------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------
    def close(self):
        """Close SSH tunnel and cleanup resources"""
        # Uncomment for production with SSH tunnel
        # if hasattr(self, 'tunnel') and self.tunnel:
        #     try:
        #         self.tunnel.stop()
        #         print("✓ SSH Tunnel closed")
        #     except Exception as e:
        #         print(f"⚠️ Error closing SSH tunnel: {e}")
        pass

    def __del__(self):
        """Destructor to ensure tunnel is closed"""
        try:
            self.close()
        except:
            pass