"""Entry point: `python run.py` starts the server and prints the local URL."""
import os
import sys
import webbrowser
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)

HOST = "127.0.0.1"
PORT = int(os.environ.get("DJ_MIX_STUDIO_PORT", "8790"))


def _open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}/")


if __name__ == "__main__":
    import uvicorn

    threading.Timer(1.2, _open_browser).start()
    print(f"DJ Mix Studio -> http://{HOST}:{PORT}/")
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
