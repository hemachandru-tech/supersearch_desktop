"""
run_desktop.py  ===>  THIS IS THE FILE YOU RUN.

    python run_desktop.py

It starts the local backend and opens "Super Search Desktop" as a clean app window.

How the window is opened (in order, whichever works first):
  1. APP_MODE=desktop (default): a chromeless Edge/Chrome "app window" - looks like a
     real desktop program (no tabs, no address bar) and is very reliable on Windows.
  2. PyWebView, if Edge/Chrome can't be found.
  3. A normal browser tab, as a last resort.
You can force a mode in .env:  APP_MODE=desktop | pywebview | browser
"""

import ssl  # noqa: F401  - load OpenSSL first (see note in local_pipeline.py)
import os
import sys
import time
import shutil
import logging
import threading
import socket
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # so "modules", "server", etc. import correctly
os.chdir(HERE)            # so relative model paths (models/...) always resolve

from dotenv import load_dotenv
from modules import paths
# .env is read-only from app resources (bundled key when packaged; project .env in dev).
load_dotenv(paths.env_path())

HOST = "127.0.0.1"
PORT = int(os.getenv("APP_PORT", "8765"))
URL = f"http://{HOST}:{PORT}"
APP_MODE = os.getenv("APP_MODE", "desktop").strip().lower()


# -------------------------------------------------------------------------
# backend server in a background thread
# -------------------------------------------------------------------------
def start_server(port):
    import uvicorn
    from server import app
    uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_level="warning")).run()


def port_is_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def find_free_port(start_port):
    """Return start_port if free, else the next free port (so a leftover instance
    on the default port never blocks a new launch)."""
    for p in range(start_port, start_port + 25):
        if port_is_free(p):
            return p
    return start_port  # give up; let the bind error surface


def wait_for_server(port, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((HOST, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


# -------------------------------------------------------------------------
# find Edge or Chrome for the chromeless "app window"
# -------------------------------------------------------------------------
def find_chromium():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        shutil.which("msedge"),
        shutil.which("chrome"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def open_app_window(browser_exe):
    """Open a dedicated, chromeless app window and wait until the user closes it."""
    profile_dir = paths.appwindow_profile()  # own profile = own process lifetime (writable)
    args = [
        browser_exe,
        f"--app={URL}",
        f"--user-data-dir={profile_dir}",
        "--window-size=1280,880",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    print(f" Opening app window using: {os.path.basename(browser_exe)}")
    start_time = time.time()
    proc = subprocess.Popen(args)
    print(" Super Search Desktop is open. Close the app window to quit.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    
    # If the process exited very quickly (less than 3 seconds), it likely delegated
    # to an existing Chrome instance and detached. In this case, we must keep
    # the backend server alive so the opened window can connect to it.
    duration = time.time() - start_time
    if duration < 3.0:
        print("\n Browser process detached/delegated to existing instance.")
        print(" Keeping backend server alive. Press Ctrl+C in this Terminal to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    print("\n App window closed. Shutting down.")


def open_browser_tab():
    import webbrowser
    print("\n Opening Super Search Desktop in your web browser...")
    webbrowser.open(URL)
    print(f" Running at: {URL}")
    print(" Keep THIS window open while you use the app. Press Ctrl+C to quit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n Shutting down. Bye!")


def open_pywebview():
    import webview
    # Silence the Windows accessibility-error flood that can freeze the window.
    logging.getLogger("pywebview").setLevel(logging.CRITICAL)
    logging.getLogger("pywebview").propagate = False
    webview.create_window("Super Search Desktop", URL, width=1280, height=880, min_size=(900, 600))
    print(" Opening desktop window...")
    webview.start()


def main():
    global PORT, URL
    print("=" * 64)
    print(" Super Search Desktop - starting local engine...")
    print("=" * 64)

    # Pick a free port so a leftover/old instance can't block this launch.
    chosen = find_free_port(PORT)
    if chosen != PORT:
        print(f" Port {PORT} busy (another instance?) - using {chosen} instead.")
    PORT, URL = chosen, f"http://{HOST}:{chosen}"

    threading.Thread(target=lambda: start_server(PORT), daemon=True).start()
    if not wait_for_server(PORT):
        print("ERROR: backend did not start. See messages above.")
        sys.exit(1)
    print(f" Backend ready at {URL}")

    if APP_MODE == "browser":
        open_browser_tab(); return

    if APP_MODE == "pywebview":
        try:
            open_pywebview(); return
        except Exception as e:
            print(f" PyWebView failed ({e}); falling back.");

    # default: desktop app window via Edge/Chrome
    browser_exe = find_chromium()
    if browser_exe:
        try:
            open_app_window(browser_exe); return
        except Exception as e:
            print(f" App window failed ({e}); trying other options.")

    try:
        open_pywebview(); return
    except Exception:
        pass

    open_browser_tab()


if __name__ == "__main__":
    main()
