"""Windows desktop launcher; it serves the same Smart Study web application."""
import threading
import time
import uvicorn
from backend.config import settings

def run_server():
    uvicorn.run("backend.app:app", host=settings.host, port=settings.port, log_level="warning")

if __name__ == "__main__":
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("Install dependencies first: pip install -r requirements.txt") from exc
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    time.sleep(1)
    webview.create_window("Smart Study", f"http://{settings.host}:{settings.port}", min_size=(1024, 700))
    webview.start()
