"""
metadata_writer.py
==================
Embeds the AI/face tags DIRECTLY INTO each image file's metadata, so the tags
travel with the image and show up in:

    Windows  ->  right-click image -> Properties -> Details tab
                 (Tags, Title, Subject, Comments, Authors)

HOW WINDOWS SHOWS TAGS (important background)
  Windows Explorer's "Details" pane only displays a FIXED set of fields, and it
  reads them from specific metadata locations. We write to all of them:

    Windows field   <-  what we put there                <- metadata tag(s)
    -------------       --------------------------------    --------------------------
    "Tags"          <-  player, event, mood, action ...   <- XPKeywords / IPTC Keywords / XMP dc:subject
    "Title"         <-  the caption                       <- XPTitle / XMP dc:title
    "Subject"       <-  short summary                     <- XPSubject / XMP dc:description
    "Comments"      <-  full readable tag breakdown       <- XPComment / EXIF UserComment
    "Authors"       <-  photographer                      <- XPAuthor / EXIF Artist

TWO BACKENDS (chosen automatically)
  1. ExifTool  (PREFERRED) - one portable .exe, handles JPEG, TIFF, PNG, HEIC,
                             RAW/ARW/DNG. Writes the cleanest, most-compatible
                             metadata. See SETUP_GUIDE for the 1-minute install.
  2. piexif    (FALLBACK)  - already installed with pip. Works for JPEG/TIFF only,
                             but is enough to make the Windows "Tags/Title/Comments"
                             fields appear for your JPEG photos with zero extra setup.

For formats Windows cannot display in Properties (PNG, HEIC, most RAW), the tags
are still embedded (recoverable by photo tools) AND indexed in SQLite for search.
"""

import os
import sys
import shutil
import subprocess
import json
import plistlib

# Formats that piexif can write to (EXIF-capable, simple).
_PIEXIF_OK = {".jpg", ".jpeg", ".tif", ".tiff"}

# Formats where Windows Explorer reliably shows the tags in Properties.
WINDOWS_VISIBLE = {".jpg", ".jpeg", ".tif", ".tiff"}

# Video containers we embed tags into (via ExifTool's QuickTime/XMP support).
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


# -------------------------------------------------------------------------
# locate exiftool once
# -------------------------------------------------------------------------
def _find_exiftool():
    """Return path to exiftool, or None.
    Order: PATH → common Homebrew locations (GUI apps launch with a minimal PATH that
    often omits these) → the bundled copy in ./tools (exiftool.exe on Windows, the perl
    'exiftool' on macOS) so it works even with no Homebrew/PATH at all."""
    found = shutil.which("exiftool")
    if found:
        return found
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        "/opt/homebrew/bin/exiftool",          # Apple-Silicon Homebrew
        "/usr/local/bin/exiftool",             # Intel Homebrew / manual install
        os.path.join(here, "tools", "exiftool.exe"),
        os.path.join(here, "tools", "exiftool"),
        os.path.join(here, "exiftool.exe"),
    ):
        if os.path.exists(cand):
            return cand
    return None


EXIFTOOL_PATH = _find_exiftool()


def get_original_orientation(file_path: str) -> int:
    """Read the Orientation tag from a file using ExifTool, returning 1-8 or 1 if not found."""
    if not EXIFTOOL_PATH:
        return 1
    try:
        proc = subprocess.run(
            [EXIFTOOL_PATH, "-Orientation", "-S", "-n", file_path],
            capture_output=True, text=True, timeout=5,
            creationflags=_no_window_flag()
        )
        if proc.returncode == 0 and proc.stdout:
            parts = proc.stdout.strip().split(":")
            if len(parts) == 2:
                return int(parts[1].strip())
    except Exception:
        pass
    return 1


def rotate_image_by_orientation(im, orientation: int):
    """Rotate a PIL Image based on the EXIF orientation code (1-8)."""
    if orientation == 2:
        return im.transpose(im.FLIP_LEFT_RIGHT)
    elif orientation == 3:
        return im.rotate(180, expand=True)
    elif orientation == 4:
        return im.transpose(im.FLIP_TOP_BOTTOM)
    elif orientation == 5:
        return im.rotate(270, expand=True).transpose(im.FLIP_LEFT_RIGHT)
    elif orientation == 6:
        return im.rotate(270, expand=True)  # 90 degrees CW
    elif orientation == 7:
        return im.rotate(90, expand=True).transpose(im.FLIP_LEFT_RIGHT)
    elif orientation == 8:
        return im.rotate(90, expand=True)   # 90 degrees CCW
    return im


def read_raw_exif_tags(file_path: str) -> dict:
    """Query EXIF tags from a RAW file using ExifTool."""
    if not EXIFTOOL_PATH:
        return {}
    try:
        proc = subprocess.run(
            [EXIFTOOL_PATH, "-j", "-Artist", "-Copyright", "-DateTimeOriginal", "-Make", "-Model", file_path],
            capture_output=True, text=True, timeout=10,
            creationflags=_no_window_flag()
        )
        if proc.returncode == 0 and proc.stdout:
            data = json.loads(proc.stdout)[0] if proc.stdout.strip() else {}
            return {
                "Photographer": data.get("Artist"),
                "Copyright": data.get("Copyright"),
                "DateTimeOriginal": data.get("DateTimeOriginal"),
                "Camera Make": data.get("Make"),
                "Camera Model": data.get("Model"),
            }
    except Exception:
        pass
    return {}


def backend_name():
    """Tell the rest of the app which backend is active (for logs / UI)."""
    if EXIFTOOL_PATH:
        return f"exiftool ({EXIFTOOL_PATH})"
    return "piexif (JPEG/TIFF only - install ExifTool for full format support)"


# -------------------------------------------------------------------------
# turn a tag dict into the pieces we embed
# -------------------------------------------------------------------------
_PLACEHOLDERS = ("", "none", "unknown", "not visible", "null", "n/a")


def build_fields(tags: dict):
    """
    Build the human-readable metadata fields from the pipeline's tag dict.
    Returns (keywords:list[str], title:str, subject:str, description:str, author:str).

    Field policy:
      - Title       : short "<Player Name> - <Action>" (concise, human-scannable)
      - Description : ONLY the Gemini-generated caption (no metadata breakdown)
      - Comment     : intentionally NOT produced — callers must not embed a comment
      - Keywords    : unchanged (player, apparel, event, mood, action, tournament)
    """
    keywords = []

    def add(value):
        if not value:
            return
        for piece in str(value).split(","):
            piece = piece.strip()
            if piece and piece.lower() not in ("none", "unknown", "not visible", "null", "n/a"):
                if piece not in keywords:
                    keywords.append(piece)

    # First tag focus: Player name
    add(tags.get("player_names"))
    # Second tag focus: Practice match or not (Kit/Apparel: Practice Jersey vs Match Jersey)
    add(tags.get("apparel"))
    # Third tag focus: Event (IPL, Event type)
    add(tags.get("event_type"))
    # Fourth tag focus: Mood and Action
    add(tags.get("mood"))
    add(tags.get("action"))
    # Tournament/league (from your TOURNAMENT_NAME setting, e.g. "IPL 2026") as a real,
    # searchable tag — so the correct league is always present in the file's keywords.
    add(tags.get("tournament"))

    caption = (tags.get("caption") or "").strip()

    # ---- TITLE: short "<Player Name> - <Action>" ----
    player = (tags.get("player_names") or "").strip()
    action = (tags.get("action") or "").strip()
    if player.lower() in _PLACEHOLDERS:
        player = ""
    if action.lower() in _PLACEHOLDERS:
        action = ""
    if player and action:
        title = f"{player} - {action}"
    else:
        # Graceful fallback if either piece is missing: whichever we have, else the caption.
        title = player or action or caption

    # ---- DESCRIPTION: ONLY the Gemini caption (no breakdown lines) ----
    description = caption

    # ---- COMMENT: removed — we no longer build or embed a comment field ----

    subject = caption[:120] if caption else (tags.get("event_type") or "")
    author = tags.get("photographer") or ""

    return keywords, title, subject, description, author


def _write_macos_metadata(file_path, keywords, description):
    """
    Write Finder Tags and the caption (as the Finder Comment) as macOS extended
    attributes (xattr). This makes tags + the description visible in Finder and
    searchable in Spotlight. The Finder Comment is the only macOS-indexed slot for
    free text, so the Gemini caption lives there (it is NOT the EXIF/XMP Comment,
    which we no longer write).
    """
    if sys.platform != 'darwin':
        return True

    ok = True
    # 1. Write Finder Tags
    if keywords:
        try:
            # macOS expects a binary plist of an array of strings
            tags_plist = plistlib.dumps(keywords, fmt=plistlib.FMT_BINARY)
            subprocess.run(
                ['xattr', '-wx', 'com.apple.metadata:_kMDItemUserTags', tags_plist.hex(), file_path],
                capture_output=True, check=True
            )
        except Exception as e:
            print(f"[MACOS METADATA] Failed to write Finder Tags to {file_path}: {e}")
            ok = False

    # 2. Write the caption into the Finder Comment (for Finder display + Spotlight search)
    if description:
        try:
            comment_plist = plistlib.dumps(description, fmt=plistlib.FMT_BINARY)
            subprocess.run(
                ['xattr', '-wx', 'com.apple.metadata:kMDItemFinderComment', comment_plist.hex(), file_path],
                capture_output=True, check=True
            )
        except Exception as e:
            print(f"[MACOS METADATA] Failed to write Finder Comment to {file_path}: {e}")
            ok = False
            
    return ok


# -------------------------------------------------------------------------
# public entry point
# -------------------------------------------------------------------------
def write_metadata(file_path: str, tags: dict):
    """
    Embed tags into the image file.
    Returns dict: {ok: bool, backend: str, windows_visible: bool, note: str}
    """
    ext = os.path.splitext(file_path)[1].lower()
    keywords, title, subject, description, author = build_fields(tags)

    # ---- VIDEO: embed into the video container ----
    if ext in VIDEO_EXTS:
        if EXIFTOOL_PATH:
            ok, note = _write_video_with_exiftool(file_path, keywords, title, description, author)
            backend = "exiftool(video)"
        else:
            # No ExifTool (the usual case on Windows): embed with the BUNDLED ffmpeg.
            # This is what makes video tagging work on Windows without any extra install.
            ok, note = _write_video_with_ffmpeg(file_path, keywords, title, description, author)
            backend = "ffmpeg(video)"
        # macOS: also mirror into Finder tags + the caption so they show in Finder + Spotlight.
        if sys.platform == "darwin":
            mac_ok = _write_macos_metadata(file_path, keywords, description)
            if mac_ok:
                note += " + macOS Finder attributes"
                ok = ok or mac_ok
        return {"ok": ok, "backend": backend, "windows_visible": False, "note": note}

    if EXIFTOOL_PATH:
        ok, note = _write_with_exiftool(file_path, keywords, title, subject, description, author)
        backend = "exiftool"
    elif ext in _PIEXIF_OK:
        ok, note = _write_with_piexif(file_path, keywords, title, subject, description, author)
        backend = "piexif"
    else:
        # On macOS, we can still write to macOS Finder Tags/Comments even if ExifTool is not installed!
        if sys.platform == 'darwin':
            mac_ok = _write_macos_metadata(file_path, keywords, description)
            if mac_ok:
                return {
                    "ok": True,
                    "backend": "macos_xattr",
                    "windows_visible": False,
                    "note": "embedded into macOS Finder tags (no ExifTool)",
                }
        return {
            "ok": False, "backend": "none", "windows_visible": False,
            "note": f"{ext} needs ExifTool to embed tags (install it - see SETUP_GUIDE). "
                    f"Tags are still saved in the search database.",
        }

    # Write to macOS Finder tags + caption if running on macOS
    if sys.platform == 'darwin':
        mac_ok = _write_macos_metadata(file_path, keywords, description)
        if mac_ok:
            note += " + macOS Finder attributes"

    return {
        "ok": ok,
        "backend": backend,
        "windows_visible": ext in WINDOWS_VISIBLE,
        "note": note,
    }


# -------------------------------------------------------------------------
# ExifTool backend
# -------------------------------------------------------------------------
def _write_with_exiftool(file_path, keywords, title, subject, description, author):
    args = [
        EXIFTOOL_PATH,
        "-overwrite_original",
        "-codedcharacterset=utf8",
        "-charset", "iptc=UTF8",
    ]
    # Clear old keywords first so re-tagging doesn't pile up duplicates.
    args += ["-Keywords=", "-Subject=", "-XPKeywords="]
    # Comment is no longer written. Clear any legacy comment fields so re-tagging a
    # previously-tagged file removes the old comment instead of leaving it stale.
    args += ["-XPComment=", "-Comment=", "-EXIF:UserComment="]
    for kw in keywords:
        args += [f"-Keywords+={kw}", f"-Subject+={kw}"]
    if keywords:
        args += [f"-XPKeywords={';'.join(keywords)}"]
    if title:
        args += [f"-Title={title}", f"-XPTitle={title}", f"-XMP-dc:Title={title}"]
    if subject:
        args += [f"-XPSubject={subject}"]
    if description:
        # Description = the Gemini caption only (no breakdown, no comment).
        args += [f"-XMP-dc:Description={description}", f"-ImageDescription={description}"]
    if author:
        args += [f"-XPAuthor={author}", f"-Artist={author}", f"-XMP-dc:Creator={author}"]
    args.append(file_path)

    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=60,
            creationflags=_no_window_flag(),
        )
        if proc.returncode == 0:
            return True, "embedded with exiftool"
        return False, f"exiftool error: {proc.stderr.strip()[:200]}"
    except Exception as e:
        return False, f"exiftool failed: {e}"


# -------------------------------------------------------------------------
# ExifTool backend for VIDEO (mp4/mov/...) - QuickTime + XMP tags
# -------------------------------------------------------------------------
def _write_video_with_exiftool(file_path, keywords, title, description, author):
    """Embed tags into a video container. Videos don't have EXIF/XP* tags, so we write
    the QuickTime 'Keys'/'ItemList' atoms (what macOS Finder/QuickTime read) AND XMP
    (what most pro tools + Windows 'Properties' read). '-m' ignores tags a particular
    container can't hold (e.g. .webm) instead of failing the whole write."""
    kwflat = "; ".join(keywords)
    args = [
        EXIFTOOL_PATH,
        "-overwrite_original",
        "-m",                       # ignore minor "tag not supported for this format" warnings
        "-charset", "iptc=UTF8",
    ]
    # Keywords: XMP subject list (+ flat copies in the QuickTime atoms)
    args += ["-XMP-dc:Subject="]
    # Comment is no longer written. Clear any legacy comment so re-tagging removes it.
    args += ["-Comment="]
    for kw in keywords:
        args += [f"-XMP-dc:Subject+={kw}"]
    if keywords:
        args += [f"-Keys:Keywords={kwflat}", f"-ItemList:Keyword={kwflat}", f"-Keywords={kwflat}"]
    if title:
        args += [f"-XMP-dc:Title={title}", f"-Keys:Title={title}", f"-ItemList:Title={title}", f"-Title={title}"]
    if description:
        # Description = the Gemini caption only (no comment).
        args += [f"-XMP-dc:Description={description}", f"-Keys:Description={description}",
                 f"-ItemList:Description={description}", f"-Description={description}"]
    if author:
        args += [f"-XMP-dc:Creator={author}", f"-Keys:Author={author}",
                 f"-ItemList:Artist={author}", f"-Artist={author}"]
    args.append(file_path)

    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=120,
            creationflags=_no_window_flag(),
        )
        if proc.returncode == 0:
            return True, "embedded into video (QuickTime/XMP)"
        return False, f"exiftool(video) error: {proc.stderr.strip()[:200]}"
    except Exception as e:
        return False, f"exiftool(video) failed: {e}"


def _ffmpeg_exe():
    """Locate ffmpeg: prefer the pip-bundled one (imageio-ffmpeg), else system PATH."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _write_video_with_ffmpeg(file_path, keywords, title, description, author):
    """Embed tags into a video using ffmpeg (no ExifTool needed — works on Windows out of
    the box via the bundled imageio-ffmpeg). ffmpeg can't edit in place, so we stream-copy
    to a temp file with the metadata set, then atomically replace the original. '-c copy'
    means no re-encoding (fast, lossless)."""
    ff = _ffmpeg_exe()
    if not ff:
        return False, "no ffmpeg available to tag video (install imageio-ffmpeg)"
    ext = os.path.splitext(file_path)[1].lower()
    tmp = file_path + ".sstag" + ext
    md = []
    if title:
        md += ["-metadata", f"title={title}"]
    if description:
        # Description = the Gemini caption only. Comment is intentionally omitted.
        md += ["-metadata", f"description={description}"]
    if author:
        md += ["-metadata", f"artist={author}", "-metadata", f"author={author}"]
    if keywords:
        md += ["-metadata", f"keywords={'; '.join(keywords)}"]
    args = [ff, "-y", "-i", file_path, "-map", "0", "-c", "copy",
            "-movflags", "use_metadata_tags", *md, tmp]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=300,
            creationflags=_no_window_flag(),
        )
        if proc.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, file_path)
            return True, "embedded into video (ffmpeg)"
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False, f"ffmpeg(video) error: {proc.stderr.strip()[-200:]}"
    except Exception as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False, f"ffmpeg(video) failed: {e}"


# -------------------------------------------------------------------------
# piexif backend (JPEG/TIFF) - writes the Windows XP* tags
# -------------------------------------------------------------------------
def _write_with_piexif(file_path, keywords, title, subject, description, author):
    import piexif

    def xp(text):
        # Windows XP* tags are UTF-16LE byte sequences, null-terminated.
        return text.encode("utf-16le") + b"\x00\x00"

    try:
        try:
            exif_dict = piexif.load(file_path)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "1st": {}, "GPS": {}, "Interop": {}}

        zeroth = exif_dict.setdefault("0th", {})

        if keywords:
            zeroth[piexif.ImageIFD.XPKeywords] = xp(";".join(keywords))
        if title:
            zeroth[piexif.ImageIFD.XPTitle] = xp(title)
        # Description = the Gemini caption only, stored in the standard EXIF
        # ImageDescription field (Windows "Title" still reads XPTitle, set above).
        if description:
            zeroth[piexif.ImageIFD.ImageDescription] = description.encode("utf-8", "ignore")
        if subject:
            zeroth[piexif.ImageIFD.XPSubject] = xp(subject)
        # Comment is no longer written. Drop any existing XPComment so re-tagging
        # clears the stale comment rather than leaving it behind.
        zeroth.pop(piexif.ImageIFD.XPComment, None)
        if author:
            zeroth[piexif.ImageIFD.XPAuthor] = xp(author)
            zeroth[piexif.ImageIFD.Artist] = author.encode("utf-8", "ignore")

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, file_path)
        return True, "embedded with piexif (Windows XP tags)"
    except Exception as e:
        return False, f"piexif failed: {e}"


# -------------------------------------------------------------------------
# read back what's embedded (used to VERIFY and to show in the UI)
# -------------------------------------------------------------------------
def read_metadata(file_path: str):
    """Return a small dict of the tag-bearing fields currently in the file."""
    if EXIFTOOL_PATH:
        try:
            proc = subprocess.run(
                [EXIFTOOL_PATH, "-j", "-Keywords", "-Subject", "-Title",
                 "-XPKeywords", "-XPTitle", "-XPComment", "-XPSubject", "-Artist",
                 "-Comment", "-Description", file_path],
                capture_output=True, text=True, timeout=30, creationflags=_no_window_flag(),
            )
            data = json.loads(proc.stdout)[0] if proc.stdout.strip() else {}
            return {
                "Tags": data.get("Keywords") or data.get("XPKeywords"),
                "Title": data.get("Title") or data.get("XPTitle"),
                "Subject": data.get("Subject") or data.get("XPSubject"),
                "Comments": data.get("Comment") or data.get("XPComment") or data.get("Description"),
                "Authors": data.get("Artist"),
            }
        except Exception as e:
            return {"error": str(e)}

    # piexif read-back (JPEG/TIFF)
    try:
        import piexif
        d = piexif.load(file_path)
        z = d.get("0th", {})

        def rd(tag):
            v = z.get(tag)
            # piexif returns XP* tags as a tuple/list of ints (UTF-16LE bytes).
            if isinstance(v, (tuple, list)):
                v = bytes(v)
            if isinstance(v, bytes):
                return v.decode("utf-16le", "ignore").rstrip("\x00")
            return v

        return {
            "Tags": rd(piexif.ImageIFD.XPKeywords),
            "Title": rd(piexif.ImageIFD.XPTitle),
            "Subject": rd(piexif.ImageIFD.XPSubject),
            "Comments": rd(piexif.ImageIFD.XPComment),
            "Authors": rd(piexif.ImageIFD.XPAuthor),
        }
    except Exception as e:
        return {"error": str(e)}


def has_embedded_tags(file_path: str):
    """
    True if the image has ANY tag keywords embedded.
    Returns (has_tags: bool, existing: dict).
    """
    md = read_metadata(file_path)
    if not isinstance(md, dict):
        return False, {}
    tags = md.get("Tags")
    has = bool(tags and str(tags).strip())
    return has, md


def tag_completeness(file_path: str):
    """
    Decide whether an image is ALREADY FULLY TAGGED (so it can be safely skipped).

    "Fully tagged" means the file's own metadata contains BOTH of:
      - keywords (the "Tags" field), AND
      - a title  (the "Title" field, e.g. "MS Dhoni - Batting")

    (We no longer embed the labelled "Event:/Mood:/Action:" breakdown, so a file
    that carries keywords + a title is considered complete.)

    This means:
      - untagged photos              -> NOT complete -> they get tagged
      - photos where the AI failed   -> NOT complete -> they get re-tagged later
      - photos you partly emptied     -> NOT complete -> they get re-filled
      - fully tagged photos          -> complete      -> skipped (left untouched)

    Returns (is_complete: bool, metadata: dict).
    """
    md = read_metadata(file_path)
    if not isinstance(md, dict):
        return False, {}

    tags = str(md.get("Tags") or "").strip()
    title = str(md.get("Title") or "").strip()

    complete = bool(tags) and bool(title)
    return complete, md


def _no_window_flag():
    """Hide the console window when calling exiftool on Windows."""
    if os.name == "nt":
        return 0x08000000  # CREATE_NO_WINDOW
    return 0
