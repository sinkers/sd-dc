"""The power-sim service: the viewer's static files and a JSON API, on one port.

    GET  /healthz                      200 and a version
    GET  /api/components               every registered component: kind, role, ports, schema
    GET  /api/sims                     the simulations, by id and title
    GET  /api/sims/<id>                one simulation: its model, asset schemas, scenarios
    POST /api/sims/<id>/run            {"scenario": id, "params": {asset_id: {...}}} -> a day
    GET  /*                            static viewer assets

Why plain HTTP and not the WebSocket the twins use: the twins hold a running
model per visitor and stream it. Here a whole day solves in a few milliseconds,
so every slider change simply re-runs the day and returns it. The browser does
the playback. There is no session state to hold, so nothing to lose.

The standard library only, so a clean checkout runs with no install.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .components import REGISTRY
from .sims import SIMS

log = logging.getLogger("dtpower.server")

VIEWER_ROOT = Path(os.environ.get("DTPOWER_VIEWER_ROOT", Path(__file__).resolve().parents[2] / "viewer"))
MAX_BODY = 256 * 1024


def tidy(v, places: int = 3):
    """Round floats for the wire: a day is a few thousand numbers, not a few megabytes."""
    if isinstance(v, float):
        return round(v, places) if v == v and abs(v) != float("inf") else None
    if isinstance(v, dict):
        return {k: tidy(x, places) for k, x in v.items()}
    if isinstance(v, list):
        return [tidy(x, places) for x in v]
    return v


def components() -> dict:
    return {kind: {"label": c.label, "role": c.role, "ports": c.ports, "schema": getattr(c, "schema", []),
                   "kind_proposed": getattr(c, "kind_proposed", False)} for kind, c in REGISTRY.items()}


class Handler(BaseHTTPRequestHandler):
    server_version = f"dtpower/{__version__}"

    def log_message(self, fmt, *args):  # route through logging, not stderr
        log.info("%s %s", self.address_string(), fmt % args)

    def _json(self, body, status: int = 200) -> None:
        data = json.dumps(tidy(body), separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._json({"ok": True, "version": __version__})
        if path == "/api/components":
            return self._json(components())
        if path == "/api/sims":
            return self._json([{"id": s.ID, "title": s.TITLE, "description": s.DESCRIPTION} for s in SIMS.values()])
        if path.startswith("/api/sims/"):
            sim = SIMS.get(path.removeprefix("/api/sims/").strip("/"))
            return self._json(sim.describe()) if sim else self._error(404, "no such simulation")
        return self._static(path)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["api", "sims"] or parts[3] != "run":
            return self._error(404, "not found")
        sim = SIMS.get(parts[2])
        if sim is None:
            return self._error(404, "no such simulation")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._error(413, "request too large")
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
            result = sim.simulate(req.get("scenario") or sim.SCENARIOS[0]["id"], req.get("params") or {})
        except KeyError as e:
            return self._error(400, str(e).strip("'\""))
        except (ValueError, TypeError) as e:
            return self._error(400, str(e))
        self._json(result)

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (VIEWER_ROOT / rel).resolve()
        if VIEWER_ROOT.resolve() not in target.parents and target != VIEWER_ROOT.resolve():
            return self._error(404, "not found")
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self._error(404, "not found")
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "text/javascript"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def make_server(host: str = "127.0.0.1", port: int = 8780) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def serve(host: str = "127.0.0.1", port: int = 8780) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    httpd = make_server(host, port)
    print(f"power-sim -> http://{host}:{httpd.server_address[1]}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
