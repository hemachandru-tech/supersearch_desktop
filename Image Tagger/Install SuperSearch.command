#!/bin/bash
# =============================================================================
#  Super Search — one-click setup for macOS
#  Double-click this file. It installs Python + everything the app needs
#  (no admin password required) and then opens Super Search.
#  Run it once; after that use "Launch SuperSearch.command".
# =============================================================================
cd "$(dirname "$0")" || exit 1
APPDIR="$(pwd)"

echo "============================================================"
echo "   Super Search — Setup (macOS)"
echo "   App folder: $APPDIR"
echo "============================================================"

fail() { echo ""; echo "✗ $1"; echo ""; read -r -p "Press Return to close…" _; exit 1; }

# 1) Get 'uv' — a tiny self-contained tool that installs Python and packages.
UV="$APPDIR/bin/uv"
if [ ! -x "$UV" ]; then
  echo "→ Downloading the setup helper…"
  mkdir -p "$APPDIR/bin"
  curl -LsSf https://astral.sh/uv/install.sh \
     | env UV_INSTALL_DIR="$APPDIR/bin" INSTALLER_NO_MODIFY_PATH=1 sh \
     || fail "Could not download the setup helper. Check your internet connection and try again."
fi
[ -x "$UV" ] || UV="$(command -v uv)"
[ -n "$UV" ] || fail "Setup helper not found after install."

# 2) Install a private copy of Python 3.11 (does NOT touch your system Python).
echo "→ Installing Python (first time only)…"
"$UV" python install 3.11 || fail "Could not install Python."

# 3) Create the app's environment and install all dependencies.
echo "→ Creating environment…"
"$UV" venv --python 3.11 "$APPDIR/.venv" || fail "Could not create the environment."
echo "→ Installing dependencies — this can take several minutes the first time…"
"$UV" pip install --python "$APPDIR/.venv/bin/python" -r "$APPDIR/requirements_desktop.txt" \
  || fail "Could not install dependencies."

# 4) ExifTool (optional): enables tag-embedding for PNG/HEIC/RAW and videos.
#    JPEG photos and video Finder-tags already work without it on macOS.
if ! command -v exiftool >/dev/null 2>&1 && [ ! -x "$APPDIR/tools/exiftool" ]; then
  if command -v brew >/dev/null 2>&1; then
    echo "→ Installing ExifTool (for full format support)…"
    brew install exiftool || echo "  (skipped — ExifTool optional)"
  fi
fi

# 5) First-run config file.
[ -f "$APPDIR/.env" ] || cp "$APPDIR/.env.template" "$APPDIR/.env"

echo ""
echo "✓ Setup complete!"
if grep -q "YOUR_API_KEY_HERE" "$APPDIR/.env" 2>/dev/null; then
  echo ""
  echo "  ▸ Add your free Gemini API key: edit the .env file's GEMINI_API_KEYS line."
  echo "    Get a key at https://aistudio.google.com/apikey"
fi
echo ""
echo "→ Opening Super Search…"
exec "$APPDIR/.venv/bin/python" "$APPDIR/run_desktop.py"
