#!/usr/bin/env python3
"""HTTP front end: the browser UI, the REST API, OpenAPI and Swagger UI.

  python3 server.py                    # http://127.0.0.1:8765
  python3 server.py --port 9000

Standard library only, so there is no install step. All calculation lives in
`service.py`, which `mcp_server.py` also uses, so the browser, a REST client and
an agent cannot get different answers to the same question.

Routes:
  /                       the calculator UI
  /docs                   Swagger UI over the OpenAPI description
  /openapi.json           OpenAPI 3.1 description
  /api/...                see openapi.py
"""
from __future__ import annotations

import argparse
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import install_diagrams
import openapi
import service
import standards

HERE = os.path.dirname(os.path.abspath(__file__))

# Swagger UI is loaded from a pinned jsdelivr build rather than vendored, to
# keep the repo free of a megabyte of third-party JS. It is the one thing here
# that needs the network; every API route and the calculator UI work offline.
SWAGGER_VERSION = "5.17.14"
SWAGGER_BASE = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_VERSION}"

DOCS_PAGE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cable Sizing API</title>
<link rel="stylesheet" href="{SWAGGER_BASE}/swagger-ui.css">
<style>
 body{{margin:0}}
 .topbar{{display:none}}
 #offline{{display:none;margin:40px auto;max-width:640px;padding:18px 20px;
   border:1px solid #dde1e7;border-left:3px solid #8a5a00;border-radius:0 8px 8px 0;
   font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
   background:#fffaf0;color:#14181f}}
 #offline code{{background:#eef1f5;padding:1px 5px;border-radius:4px;
   font:13px ui-monospace,Menlo,monospace}}
</style></head><body>
<div id="offline">
  <strong>Swagger UI could not load.</strong>
  <p>It is served from a CDN, so this page needs network access. The API itself
     does not: the description is at <code>/openapi.json</code> and every route
     works offline. Point any OpenAPI client at that URL.</p>
</div>
<div id="swagger"></div>
<script src="{SWAGGER_BASE}/swagger-ui-bundle.js"
        onerror="document.getElementById('offline').style.display='block'"></script>
<script>
 window.addEventListener("load", function(){{
   if(!window.SwaggerUIBundle){{
     document.getElementById("offline").style.display = "block";
     return;
   }}
   SwaggerUIBundle({{
     url: "/openapi.json",
     dom_id: "#swagger",
     deepLinking: true,
     tryItOutEnabled: true,
     defaultModelsExpandDepth: 0,
     displayRequestDuration: true,
   }});
 }});
</script></body></html>
"""


def _page():
    """The calculator UI, read from disk so it can be edited without a restart."""
    with open(os.path.join(HERE, "ui.html"), encoding="utf-8") as fh:
        return fh.read()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"cable-sizing/{service.VERSION}"

    def log_message(self, fmt, *args):
        pass

    # ------------------------------------------------------------- plumbing

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, allow_nan=False), "application/json")

    def _err(self, code, message, trace=None):
        body = {"error": message}
        if trace:
            body["trace"] = trace
        self._json(code, body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _base_url(self):
        host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_port}"
        return f"http://{host}"

    # ------------------------------------------------------------------ GET

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/":
                return self._send(200, _page(), "text/html; charset=utf-8")
            if path == "/docs":
                return self._send(200, DOCS_PAGE, "text/html; charset=utf-8")
            if path == "/openapi.json":
                return self._json(200, openapi.spec(self._base_url()))
            if path == "/api/health":
                return self._json(200, service.health())
            if path == "/api/meta":
                return self._json(200, service.meta())
            if path == "/api/standards":
                return self._json(200, service.list_standards())
            if path.startswith("/api/standards/"):
                sid = path.rsplit("/", 1)[1]
                if sid not in standards.STANDARDS:
                    return self._err(404, f"unknown standard {sid!r}")
                return self._json(200, standards.as_dict(standards.get(sid)))
            if path == "/api/cable-types":
                return self._json(200, service.list_cable_types())
            if path == "/api/diagrams":
                return self._json(200, service.list_diagrams())
            if path.startswith("/api/diagrams/"):
                key = path.rsplit("/", 1)[1]
                if key not in install_diagrams.DIAGRAMS:
                    return self._err(404, f"unknown diagram {key!r}")
                return self._send(200, service.diagram(key),
                                  "image/svg+xml; charset=utf-8")
            if path == "/diagrams.css":
                return self._send(200, install_diagrams.CSS,
                                  "text/css; charset=utf-8")
            return self._err(404, "not found")
        except Exception as exc:                       # pragma: no cover
            return self._err(500, str(exc), traceback.format_exc())

    def do_HEAD(self):
        self.do_GET()

    # ----------------------------------------------------------------- POST

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        ops = {"/api/size": service.size, "/api/check": service.check}
        if path not in ops:
            return self._err(404, "not found")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(payload, dict):
                return self._err(400, "body must be a JSON object")
        except (ValueError, json.JSONDecodeError) as exc:
            return self._err(400, f"invalid JSON body: {exc}")
        try:
            return self._json(200, ops[path](payload))
        except ValueError as exc:
            # Every deliberate refusal in the engine and the service layer is a
            # ValueError with an actionable message, so it is a 400 and the
            # message goes straight through.
            return self._err(400, str(exc))
        except Exception as exc:                       # pragma: no cover
            return self._err(500, str(exc), traceback.format_exc())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"cable sizing on http://{a.host}:{a.port}")
    print(f"  UI          http://{a.host}:{a.port}/")
    print(f"  Swagger UI  http://{a.host}:{a.port}/docs")
    print(f"  OpenAPI     http://{a.host}:{a.port}/openapi.json")
    print(f"  catalogue   {service.CATALOG.get('source')}")
    print(f"  standards   " + ", ".join(
        s.name + ("" if s.selects_size else " (check only)")
        for s in standards.STANDARDS.values()))
    print(f"  tricab      {len(service.TRICAB.get('families', []))} public "
          f"families, no per-size data (login gated)")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
