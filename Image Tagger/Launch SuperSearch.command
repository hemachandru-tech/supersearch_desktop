#!/bin/bash
# Opens Super Search. (Run "Install SuperSearch.command" once first.)
cd "$(dirname "$0")" || exit 1
APPDIR="$(pwd)"
if [ ! -x "$APPDIR/.venv/bin/python" ]; then
  echo "Super Search isn't set up yet."
  echo "Please double-click \"Install SuperSearch.command\" first."
  read -r -p "Press Return to close…" _
  exit 1
fi
exec "$APPDIR/.venv/bin/python" "$APPDIR/run_desktop.py"
