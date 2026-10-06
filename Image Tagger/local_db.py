"""
local_db.py
================
Local SQLite database for Super Search Desktop (replaces the old MySQL backend).

WHY SQLITE INSTEAD OF MYSQL?
  - No server to install or run. The whole database is ONE file (tags.db).
  - Portable: copy tags.db anywhere and the search still works.
  - Plenty fast for a single-desktop image archive.

WHAT THIS STORES
  - One row per image, holding every tag the pipeline produced
    (player names, event, mood, action, jersey colour, caption, etc.).
  - A full-text search index (FTS5) so the search box is instant.

NOTE: The tags are ALSO written into each image file's metadata
      (see metadata_writer.py). This database is the fast *search index*;
      the image files remain the source of truth and stay searchable even
      if this database is deleted (you can re-scan to rebuild it).
"""

import os
import sqlite3
import threading
from datetime import datetime

# Every column we keep for an image. Order matters for inserts.
IMAGE_COLUMNS = [
    "file_path",          # absolute path on disk (UNIQUE key)
    "file_name",
    "folder",
    "file_hash",          # md5 of the file, used to detect changes
    "player_names",       # comma-separated, from the face-recognition model
    "event_type",         # from Gemini
    "mood",               # from Gemini
    "action",             # from Gemini
    "location",           # from Gemini
    "jersey_color",       # from Gemini
    "apparel",            # from the jersey classifier (Match/Practice/Off-field)
    "apparels_seen",      # from Gemini (list of kit items)
    "crowd_present",      # from Gemini (Yes/No)
    "caption",            # from Gemini (one descriptive sentence)
    "embedded_tags",      # tags read back from images that were ALREADY tagged before
    "logos_branding",     # from Gemini
    "shot_type",          # from face/EXIF heuristic
    "focus",              # solo / group / null
    "no_of_faces",
    "tournament",
    "photographer",
    "copyright",
    "camera_make",
    "camera_model",
    "date_time_original",
    "date",
    "time_of_day",
    "width",
    "height",
    "metadata_written",   # 1 if tags were embedded into the file successfully
    "status",             # completed / error
    "error_message",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "processing_time",
    "api_key_used",
    "faces_json",
]

# Columns that the search box searches across (full text).

PLAYER_COLUMNS = [
    "name",
    "team",
    "status",
    "aliases"
]

TRAINING_SAMPLE_COLUMNS = [
    "player_id",
    "source_file",
    "face_bbox",
    "embedding",
    "league",
    "season",
    "team",
    "source_type",
    "embedding_model"
]

MODEL_COLUMNS = [
    "version_name",
    "players_count",
    "samples_count",
    "model_path",
    "metrics",
    "status"
]

FTS_COLUMNS = [
    "file_name", "player_names", "event_type", "mood", "action",
    "location", "jersey_color", "apparel", "apparels_seen",
    "crowd_present", "caption", "embedded_tags", "logos_branding",
    "shot_type", "tournament",
]


class LocalDB:
    """Thread-safe-ish SQLite wrapper. We use a lock + one connection per call."""

    def __init__(self, db_path="tags.db"):
        self.db_path = os.path.abspath(db_path)
        self._lock = threading.Lock()
        self.fts_enabled = False
        print(f"\n[DB] Using SQLite database file: {self.db_path}")
        self._init_schema()

    # ---------------------------------------------------------------
    # connection helper
    # ---------------------------------------------------------------
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ---------------------------------------------------------------
    # schema creation
    # ---------------------------------------------------------------
    def _init_schema(self):
        with self._lock, self._connect() as conn:
            cols_sql = ",\n                ".join(
                f"{c} TEXT" if c not in (
                    "no_of_faces", "width", "height", "metadata_written",
                    "input_tokens", "output_tokens", "total_tokens"
                ) else f"{c} INTEGER"
                for c in IMAGE_COLUMNS
            )
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    {cols_sql},
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(file_path)
                )
            """)
            # Migration: add any columns that are missing in an older tags.db.
            existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(images)").fetchall()}
            for c in IMAGE_COLUMNS:
                if c not in existing_cols:
                    col_type = "INTEGER" if c in (
                        "no_of_faces", "width", "height", "metadata_written",
                        "input_tokens", "output_tokens", "total_tokens"
                    ) else "TEXT"
                    conn.execute(f"ALTER TABLE images ADD COLUMN {c} {col_type}")
                    print(f"[DB] Added missing column: {c}")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_player ON images(player_names)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event ON images(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON images(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_folder ON images(folder)")

            # Create players table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    team TEXT,
                    status TEXT DEFAULT 'Active',
                    aliases TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            existing_player_cols = {r[1] for r in conn.execute("PRAGMA table_info(players)").fetchall()}
            for c in PLAYER_COLUMNS:
                if c not in existing_player_cols:
                    conn.execute(f"ALTER TABLE players ADD COLUMN {c} TEXT")
                    print(f"[DB] Added missing column to players: {c}")

            # Create training_samples table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS training_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER,
                    source_file TEXT,
                    face_bbox TEXT,
                    embedding BLOB,
                    league TEXT,
                    season TEXT,
                    team TEXT,
                    source_type TEXT,
                    embedding_model TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(player_id) REFERENCES players(id)
                )
            ''')
            existing_sample_cols = {r[1] for r in conn.execute("PRAGMA table_info(training_samples)").fetchall()}
            for c in TRAINING_SAMPLE_COLUMNS:
                if c not in existing_sample_cols:
                    col_type = "BLOB" if c == "embedding" else ("INTEGER" if c == "player_id" else "TEXT")
                    conn.execute(f"ALTER TABLE training_samples ADD COLUMN {c} {col_type}")
                    print(f"[DB] Added missing column to training_samples: {c}")

            # Migration: Backfill team from players table if team is null
            conn.execute('''
                UPDATE training_samples
                SET team = (SELECT team FROM players WHERE players.id = training_samples.player_id)
                WHERE team IS NULL
            ''')

            # Create models table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_name TEXT UNIQUE,
                    players_count INTEGER,
                    samples_count INTEGER,
                    model_path TEXT,
                    metrics TEXT,
                    status TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            ''')
            existing_model_cols = {r[1] for r in conn.execute("PRAGMA table_info(models)").fetchall()}
            for c in MODEL_COLUMNS:
                if c not in existing_model_cols:
                    col_type = "INTEGER" if c in ("players_count", "samples_count") else "TEXT"
                    conn.execute(f"ALTER TABLE models ADD COLUMN {c} {col_type}")
                    print(f"[DB] Added missing column to models: {c}")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_player ON training_samples(player_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_season ON training_samples(season)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_league ON training_samples(league)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_models_status ON models(status)")



            # Full-text search index (FTS5). Falls back to plain LIKE if unavailable.
            # We drop & recreate it every start so it always matches FTS_COLUMNS,
            # then rebuild it from the images table - cheap at desktop scale.
            try:
                for trg in ("images_ai", "images_ad", "images_au"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {trg}")
                conn.execute("DROP TABLE IF EXISTS images_fts")
                fts_cols = ", ".join(FTS_COLUMNS)
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS images_fts
                    USING fts5({fts_cols}, content='images', content_rowid='id')
                """)
                # Keep the FTS index in sync with the images table via triggers.
                col_inserts = ", ".join(FTS_COLUMNS)
                col_values = ", ".join(f"new.{c}" for c in FTS_COLUMNS)
                old_values = ", ".join(f"old.{c}" for c in FTS_COLUMNS)
                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS images_ai AFTER INSERT ON images BEGIN
                        INSERT INTO images_fts(rowid, {col_inserts}) VALUES (new.id, {col_values});
                    END
                """)
                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS images_ad AFTER DELETE ON images BEGIN
                        INSERT INTO images_fts(images_fts, rowid, {col_inserts})
                        VALUES('delete', old.id, {old_values});
                    END
                """)
                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS images_au AFTER UPDATE ON images BEGIN
                        INSERT INTO images_fts(images_fts, rowid, {col_inserts})
                        VALUES('delete', old.id, {old_values});
                        INSERT INTO images_fts(rowid, {col_inserts}) VALUES (new.id, {col_values});
                    END
                """)
                # Repopulate the freshly (re)created FTS index from existing rows.
                conn.execute("INSERT INTO images_fts(images_fts) VALUES('rebuild')")
                self.fts_enabled = True
                print("[DB] Full-text search (FTS5) enabled.")
            except sqlite3.OperationalError as e:
                self.fts_enabled = False
                print(f"[DB] FTS5 not available, using basic search instead ({e}).")
        print("[DB] Schema ready.")

    # ---------------------------------------------------------------
    # has this file already been processed (and is it unchanged)?
    # ---------------------------------------------------------------
    def get_existing(self, file_path):
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT file_hash, status FROM images WHERE file_path = ?",
                (os.path.abspath(file_path),),
            ).fetchone()
            return dict(row) if row else None

    # ---------------------------------------------------------------
    # insert or update one image's tags
    # ---------------------------------------------------------------
    def upsert_image(self, record: dict):
        record = dict(record)
        record["file_path"] = os.path.abspath(record["file_path"])
        values = [record.get(c) for c in IMAGE_COLUMNS]
        placeholders = ", ".join("?" for _ in IMAGE_COLUMNS)
        col_list = ", ".join(IMAGE_COLUMNS)
        update_set = ", ".join(f"{c}=excluded.{c}" for c in IMAGE_COLUMNS)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO images ({col_list}) VALUES ({placeholders})
                ON CONFLICT(file_path) DO UPDATE SET
                    {update_set},
                    updated_at = datetime('now')
                """,
                values,
            )

    # ---------------------------------------------------------------
    # update only the editable tag fields (used by the "Edit Tags" UI)
    # ---------------------------------------------------------------
    def update_tags(self, image_id: int, fields: dict):
        allowed = set(IMAGE_COLUMNS)
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            return None
        params.append(image_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE images SET {', '.join(sets)}, updated_at = datetime('now') WHERE id = ?",
                params,
            )
            row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
            return dict(row) if row else None

    def get_image(self, image_id: int):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
            return dict(row) if row else None

    # ---------------------------------------------------------------
    # Refresh Library helpers (sync the index with what's on disk)
    # ---------------------------------------------------------------
    def all_image_paths(self):
        """Return [(id, file_path), ...] for every indexed image (used by Refresh)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT id, file_path FROM images").fetchall()
            return [(r[0], r[1]) for r in rows]

    def distinct_folders(self):
        """Return the distinct source folders currently represented in the index.
        Unlike distinct_values(), this does NOT split on commas (folder paths are atomic)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT folder FROM images WHERE folder IS NOT NULL AND folder != ''"
            ).fetchall()
            return [r[0] for r in rows]

    def delete_images(self, image_ids):
        """Delete rows by id. Returns the number of rows removed. The FTS index is kept
        in sync automatically by the AFTER DELETE trigger created in _init_schema()."""
        ids = [int(i) for i in (image_ids or [])]
        if not ids:
            return 0
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM images WHERE id IN ({','.join('?' for _ in ids)})", ids
            )
            return cur.rowcount

    # ---------------------------------------------------------------
    # search
    # ---------------------------------------------------------------
    def search(self, query="", filters=None, limit=200, offset=0):
        """
        query   : free text typed in the search box (matches any tag)
        filters : dict of exact-ish filters, e.g. {"player_names": "Dhoni"}
        """
        filters = filters or {}
        where, params = [], []

        # Free-text part
        if query and query.strip():
            q = query.strip()
            if self.fts_enabled:
                # FTS5 MATCH. Build a forgiving query: each word is a prefix match.
                terms = [t for t in _tokenize(q)]
                if terms:
                    match_expr = " OR ".join(f'"{t}"*' for t in terms)
                    ids = self._fts_ids(match_expr)
                    if not ids:
                        return []
                    where.append(f"id IN ({','.join('?' for _ in ids)})")
                    params.extend(ids)
            else:
                like = f"%{q}%"
                or_parts = " OR ".join(f"{c} LIKE ?" for c in FTS_COLUMNS)
                where.append(f"({or_parts})")
                params.extend([like] * len(FTS_COLUMNS))

        # Structured filters
        for col, val in filters.items():
            if col in IMAGE_COLUMNS and val not in (None, "", "All"):
                where.append(f"{col} LIKE ?")
                params.append(f"%{val}%")

        sql = "SELECT * FROM images"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def _fts_ids(self, match_expr):
        with self._lock, self._connect() as conn:
            try:
                rows = conn.execute(
                    "SELECT rowid FROM images_fts WHERE images_fts MATCH ?",
                    (match_expr,),
                ).fetchall()
                return [r[0] for r in rows]
            except sqlite3.OperationalError:
                return []

    # ---------------------------------------------------------------
    # distinct values for the filter dropdowns
    # ---------------------------------------------------------------
    def distinct_values(self, column):
        if column not in IMAGE_COLUMNS:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT {column} FROM images WHERE {column} IS NOT NULL AND {column} != ''"
            ).fetchall()
        # player_names / events can be comma lists -> split them
        values = set()
        for r in rows:
            for piece in str(r[0]).split(","):
                piece = piece.strip()
                if piece:
                    values.add(piece)
        return sorted(values)

    def stats(self):
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
            done = conn.execute("SELECT COUNT(*) FROM images WHERE status='completed'").fetchone()[0]
            errors = conn.execute("SELECT COUNT(*) FROM images WHERE status='error'").fetchone()[0]
            embedded = conn.execute("SELECT COUNT(*) FROM images WHERE metadata_written=1").fetchone()[0]
        return {"total": total, "completed": done, "errors": errors, "metadata_written": embedded}


    # ---------------------------------------------------------------
    # Player Management Operations
    # ---------------------------------------------------------------
    def get_players(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute('''
                SELECT p.*, COUNT(ts.id) as sample_count 
                FROM players p 
                LEFT JOIN training_samples ts ON p.id = ts.player_id 
                GROUP BY p.id 
                ORDER BY p.name
            ''').fetchall()
            return [dict(r) for r in rows]


    def get_player(self, player_id: int):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            return dict(row) if row else None

    def add_player(self, name: str, team: str, aliases: str = ""):
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO players (name, team, aliases) VALUES (?, ?, ?)", (name, team, aliases))
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_player(self, player_id: int, name: str, team: str, status: str, aliases: str):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE players SET name=?, team=?, status=?, aliases=?, updated_at=datetime('now') WHERE id=?", 
                (name, team, status, aliases, player_id)
            )

    def get_all_training_samples(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute('''
                SELECT ts.id, ts.player_id, p.name as player_name, ts.embedding 
                FROM training_samples ts
                JOIN players p ON ts.player_id = p.id
                WHERE p.status = 'Active'
            ''').fetchall()
            return [dict(r) for r in rows]

    def get_training_samples(self, player_id: int):
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT id, player_id, source_file, face_bbox, league, season, team, source_type, created_at, embedding_model FROM training_samples WHERE player_id = ? ORDER BY created_at DESC", (player_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_training_sample_embedding(self, sample_id: int):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT embedding FROM training_samples WHERE id = ?", (sample_id,)).fetchone()
            return row["embedding"] if row else None

    def add_training_sample(self, player_id: int, source_file: str, face_bbox: str, embedding: bytes, league: str, season: str, team: str, source_type: str, embedding_model: str):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO training_samples (player_id, source_file, face_bbox, embedding, league, season, team, source_type, embedding_model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (player_id, source_file, face_bbox, embedding, league, season, team, source_type, embedding_model)
            )
            
    def delete_training_sample(self, sample_id: int):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM training_samples WHERE id = ?", (sample_id,))

    def get_models(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]
            
    def add_model(self, version_name: str, players_count: int, samples_count: int, model_path: str, metrics: str, status: str):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO models (version_name, players_count, samples_count, model_path, metrics, status) VALUES (?, ?, ?, ?, ?, ?)",
                (version_name, players_count, samples_count, model_path, metrics, status)
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def activate_model(self, model_id: int):
        with self._lock, self._connect() as conn:
            try:
                conn.execute("BEGIN TRANSACTION")
                conn.execute("UPDATE models SET status = 'PREVIOUS' WHERE status = 'ACTIVE'")
                conn.execute("UPDATE models SET status = 'ACTIVE' WHERE id = ?", (model_id,))
                conn.execute("COMMIT")
                return True
            except Exception as e:
                conn.execute("ROLLBACK")
                print(f"[DB] Error activating model: {e}")
                return False
                
    def get_active_model_path(self):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT model_path FROM models WHERE status = 'ACTIVE'").fetchone()
            return row["model_path"] if row else None



def _tokenize(text):

    import re
    return [t for t in re.split(r"[^A-Za-z0-9]+", text) if len(t) >= 2]


