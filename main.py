"""Entry point — boots the FastAPI backend then opens a pywebview window.

Usage:
    uv run python main.py

What happens:
    1. uvicorn starts FastAPI on http://127.0.0.1:8765 (in a daemon thread).
    2. We poll /api/ping until it responds (max 5s) so the WebView is
       handed a URL that already serves content.
    3. A pywebview native window opens against that URL. The window uses
       the OS-supplied WebView (Edge WebView2 on Windows, WKWebView on
       macOS, GTK WebKit on Linux) — no extra runtime to install.
    4. On window close, we shut down the kernel cleanly.

Port fallback: if 8765 is taken we try 8766, 8767, ... up to +10.
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
import webview

from backend.api import app as fastapi_app
from backend.deps import get_kernel

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_PORT = 8765
PORT_RETRY = 10


def _configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _pick_free_port(start: int = DEFAULT_PORT, retries: int = PORT_RETRY) -> int:
    for offset in range(retries + 1):
        port = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"no free port in [{start}, {start + retries}]")


def _serve(port: int) -> None:
    uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="warning")


def _wait_until_ready(url: str, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def main() -> int:
    _configure_logging()
    port = _pick_free_port()
    url = f"http://127.0.0.1:{port}"
    logging.info("serving FastAPI on %s", url)

    server_thread = threading.Thread(target=_serve, args=(port,), daemon=True)
    server_thread.start()

    if not _wait_until_ready(f"{url}/api/ping"):
        logging.error("backend did not become ready in time")
        return 1

    # Warm up the kernel in the background so the user's first Submit
    # doesn't pay the cold-start cost.
    threading.Thread(target=get_kernel, daemon=True).start()

    webview.create_window(
        title="Study Python for Finance",
        url=url,
        width=1280,
        height=820,
        min_size=(1100, 700),
    )
    webview.start(debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
