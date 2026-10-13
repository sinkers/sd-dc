#!/usr/bin/env python3
"""REST front end for the pipe router.

  python3 server.py                    # http://127.0.0.1:8775
  python3 server.py --port 9000

Standard library only. All routing lives in `service.py`, which the MCP
servers also use. Routes are described at /openapi.json:

  GET  /api/health  /api/meta  /api/specs
  POST /api/route  /api/route/batch  /api/validate
  POST /api/render?format=svg|png|json   a review sheet of the routes
  POST /api/tray                          a cable tray run and its supports
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import openapi
import service
import tray_service
from core.render import svg_to_png

MAX_BODY = 1 << 20

GETS = {
    "/api/health": lambda: {"status": "ok", "version": service.VERSION},
    "/api/meta": service.meta,
    "/api/specs": service.specs,
    "/openapi.json": openapi.spec,
}
POSTS = {
    "/api/route": service.route,
    "/api/route/batch": service.route_batch,
    "/api/validate": service.validate,
    "/api/render": service.render,
    "/api/tray": tray_service.route_and_support,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"piping/{service.VERSION}"
    timeout = 30

    def log_message(self, fmt, *args):
        sys.stderr.write("[piping] %s %s\n" % (self.address_string(),
                                               fmt % args))

    def _json(self, code, obj):
        body = json.dumps(obj, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _raw(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _format(self):
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        for kv in q.split("&"):
            k, _, v = kv.partition("=")
            if k == "format":
                return v
        return "svg"

    def _path(self):
        return self.path.split("?", 1)[0].rstrip("/") or "/"

    def do_GET(self):
        fn = GETS.get(self._path())
        if fn is None:
            self._json(404, {"error": f"no route {self._path()}"})
            return
        self._json(200, fn())

    def do_POST(self):
        fn = POSTS.get(self._path())
        if fn is None:
            self._json(404, {"error": f"no route {self._path()}"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "bad Content-Length"})
            return
        if length > MAX_BODY:
            self._json(413, {"error": "request too large"})
            return
        try:
            req = json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"body is not JSON: {exc}"})
            return
        try:
            if fn is service.render:
                self._render(fn(req))
                return
            self._json(200, fn(req))
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:                           # pragma: no cover
            sys.stderr.write(traceback.format_exc())
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _render(self, result):
        fmt = self._format()
        if fmt == "json":
            self._json(200, result)
        elif fmt == "svg":
            self._raw(200, "image/svg+xml", result["svg"].encode())
        elif fmt == "png":
            png = svg_to_png(result["svg"])
            if png is None:
                self._json(501, {"error": "PNG needs rsvg-convert on the "
                                          "server; ask for format=svg"})
            else:
                self._raw(200, "image/png", png)
        else:
            self._json(400, {"error": f"format {fmt!r}: use svg, png or "
                                      f"json"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8775)
    args = ap.parse_args(argv)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    sys.stderr.write(f"[piping] {service.VERSION} on "
                     f"http://{args.host}:{args.port}\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
