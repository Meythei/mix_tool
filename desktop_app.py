"""Native desktop entry point: runs the FastAPI backend in a background
thread and shows it in a pywebview window (no browser chrome/tabs/URL bar).
This is what PyInstaller freezes into DJMixStudio.exe."""
import os
import sys
import threading
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
os.environ["DJ_MIX_STUDIO_APP_ROOT"] = BASE_DIR
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)

HOST = "127.0.0.1"
PORT = int(os.environ.get("DJ_MIX_STUDIO_PORT", "8791"))
URL = f"http://{HOST}:{PORT}/"


def _run_server():
    import asyncio
    import uvicorn
    if sys.platform == "win32":
        # ProactorEventLoop's IOCP-based accept() is flaky when the loop
        # isn't on the main thread (WinError 64 "network name no longer
        # available"); the selector loop doesn't hit this.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("main:app", host=HOST, port=PORT, log_level="warning")


def _wait_for_server(timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{URL}api/health", timeout=1.0)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    threading.Thread(target=_run_server, daemon=True).start()
    _wait_for_server()

    import webview
    webview.create_window(
        "DJ Mix Studio", URL,
        width=1480, height=920, min_size=(1080, 680),
        background_color="#121218",
    )
    webview.start()


if __name__ == "__main__":
    main()
