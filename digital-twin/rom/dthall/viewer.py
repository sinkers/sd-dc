"""Serve the 3D viewer and the twin together, so one command gets you a picture.

The viewer is static files (`digital-twin/viewer/`) plus a WebSocket. Rather than
make you run two servers, this starts both: a threaded HTTP server for the assets
and the usual `TwinServer` for telemetry, then opens a browser at the right URL.

The browser talks to `ws://<host>:<ws_port>` — the same endpoint, same schema, that
the Unreal scene will use. Nothing here is viewer-specific on the solver side.
"""

from __future__ import annotations

import asyncio
import http.server
import logging
import socketserver
import threading
import webbrowser
from pathlib import Path

from .params import RomParams
from .server import ServerConfig, TwinServer
from .topology import HallSpec, from_cfd_export

log = logging.getLogger("dthall.viewer")

VIEWER_ROOT = Path(__file__).resolve().parents[2] / "viewer"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(VIEWER_ROOT), **kwargs)

    def log_message(self, fmt, *args):  # keep the console readable
        log.debug("http: " + fmt, *args)

    def end_headers(self):
        # The geometry bundle changes whenever prepare_geometry.py runs; caching it
        # is the difference between "my edit did nothing" and a five-minute detour.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _ThreadedHTTP(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def check_geometry() -> str | None:
    """Return a problem description if the viewer cannot possibly render."""
    if not VIEWER_ROOT.is_dir():
        return f"viewer directory missing at {VIEWER_ROOT}"
    missing = [
        str(p.relative_to(VIEWER_ROOT))
        for p in (
            VIEWER_ROOT / "index.html",
            VIEWER_ROOT / "app.js",
            VIEWER_ROOT / "geometry" / "manifest.json",
            VIEWER_ROOT / "geometry" / "geometry.bin",
            VIEWER_ROOT / "vendor" / "three.module.js",
        )
        if not p.exists()
    ]
    if missing:
        hint = ""
        if any("geometry" in m for m in missing):
            hint = "\n  run: python3 viewer/prepare_geometry.py"
        return f"viewer assets missing: {', '.join(missing)}{hint}"
    return None


def run(
    spec: HallSpec | None = None,
    params: RomParams | None = None,
    http_port: int = 8080,
    ws_port: int = 8765,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    **twin_kwargs,
) -> None:
    problem = check_geometry()
    if problem:
        raise SystemExit(problem)

    # The service serves its own static assets now (server.py process_request), so
    # this threaded HTTP server exists only for the legacy two-port layout. Kept
    # because it is occasionally handy to serve the viewer from a different port
    # than the solver while debugging.
    httpd = _ThreadedHTTP((host, http_port), _Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    url = f"http://{host}:{port}/index.html"
    if ws_port != 8765:
        url += f"?ws=ws://{host}:{ws_port}"
    log.info("viewer at %s", url)

    server = TwinServer(
        spec=spec or from_cfd_export(),
        params=params,
        config=ServerConfig(host=host, port=ws_port, **twin_kwargs),
    )

    if open_browser:
        # Give the solver a moment to settle before the page connects, so the
        # first frame the viewer draws is an equilibrium hall rather than a
        # cold-start transient.
        threading.Timer(2.5, lambda: webbrowser.open(url)).start()

    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        httpd.shutdown()
