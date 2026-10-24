"""python -m nekostudio [--host 127.0.0.1] [--port 7860] [--open]"""
import argparse
import threading
import time
import webbrowser

import uvicorn


def main():
    ap = argparse.ArgumentParser(prog="nekostudio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--open", action="store_true", help="open the browser once the server is up")
    a = ap.parse_args()
    if a.open:
        url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '::') else a.host}:{a.port}"
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    uvicorn.run("nekostudio.server:app", host=a.host, port=a.port, log_level="info",
                # an open /api/events stream would otherwise keep the server (and its VRAM) alive after Ctrl+C
                timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
