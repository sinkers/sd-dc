#!/usr/bin/env python3
"""MCP over Streamable HTTP, so a remote client can reach the cable sizer.

  python3 http_mcp_server.py                 # http://127.0.0.1:8766/mcp
  python3 http_mcp_server.py --port 9000
  MCP_TOKEN=secret python3 http_mcp_server.py    # require a bearer token

`mcp_server.py` speaks JSON-RPC over stdio, which only works when the client
can spawn the process. A hosted client cannot, so it needs the same protocol
over HTTP. Dispatch is `mcp_server.handle`, unchanged and untouched: stdio and
HTTP cannot answer the same question differently because there is only one
implementation of the answer.

Standard library only, matching the rest of this package.

Transport
---------
One endpoint, `/mcp`, per the MCP Streamable HTTP transport.

  POST    a JSON-RPC request  -> a JSON-RPC response
          a JSON-RPC notify   -> 202 with no body
          a batch (JSON array) -> an array of the responses that have ids
  GET     405. Server-initiated streams are not offered; this server has no
          unsolicited messages to push, and saying so is honest where an empty
          SSE stream would leave a client waiting.
  DELETE  200. Ends a session.

`Mcp-Session-Id` is issued on initialize and echoed back afterwards. It is a
correlation handle for logs, not a security boundary -- state lives in the
tables, and every request is independently answerable.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mcp_server

#: Bearer token. Unset means no authentication, which is only appropriate on a
#: private network. Set MCP_TOKEN to require `Authorization: Bearer <token>`.
TOKEN = os.environ.get("MCP_TOKEN") or None

#: Cap the request body. The largest legitimate call here is a few kilobytes.
MAX_BODY = 1 << 20

PROTOCOL_HEADER = "MCP-Protocol-Version"


def _jsonrpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


class Handler(BaseHTTPRequestHandler):
    server_version = "cable-sizing-mcp/" + mcp_server.SERVER_INFO["version"]
    protocol_version = "HTTP/1.1"
    #: A slow client would otherwise hold a thread for as long as it likes,
    #: which ThreadingHTTPServer will happily keep spawning. Caddy fronts this
    #: in the deployed arrangement and would shed such a connection first, but
    #: the server should not depend on the proxy to stay up.
    timeout = 30

    # ------------------------------------------------------------------ util
    def _cors(self):
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         f"Content-Type, Authorization, Mcp-Session-Id, {PROTOCOL_HEADER}")
        self.send_header("Access-Control-Expose-Headers",
                         f"Mcp-Session-Id, {PROTOCOL_HEADER}")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send(self, status, payload=None, session_id=None, extra=None):
        body = b"" if payload is None else json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        if body:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self._cors()
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _authorised(self):
        if TOKEN is None:
            return True
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not supplied.startswith(prefix):
            return False
        # Constant-time: a token check that leaks length or prefix by timing is
        # a token check worth skipping.
        return secrets.compare_digest(supplied[len(prefix):], TOKEN)

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Bearer realm="cable-sizing"')
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    # --------------------------------------------------------------- methods
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/healthz":
            # Deliberately unauthenticated, even when MCP_TOKEN is set: a health
            # check that needs a credential is one the orchestrator cannot make.
            # It returns names and versions, never table data.
            self._send(200, {
                "status": "ok",
                "server": mcp_server.SERVER_INFO,
                "tools": [t["name"] for t in mcp_server.TOOLS],
                "resources": [r["uri"] for r in mcp_server.RESOURCES],
                "auth": "bearer" if TOKEN else "none",
            })
            return
        if path == "/mcp":
            # No server-initiated stream. Allow tells the client what is here.
            self._send(405, {"error": "this server does not offer a server-initiated "
                                      "stream; POST JSON-RPC to /mcp"},
                       extra={"Allow": "POST, DELETE, OPTIONS"})
            return
        self._send(404, {"error": f"no route {path}"})

    def do_DELETE(self):
        if not self._authorised():
            self._deny()
            return
        self._send(200, {"ok": True})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/mcp":
            self._send(404, {"error": f"no route {path}; POST JSON-RPC to /mcp"})
            return
        if not self._authorised():
            self._deny()
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, _jsonrpc_error(None, -32700, "bad Content-Length"))
            return
        if length > MAX_BODY:
            self._send(413, _jsonrpc_error(None, -32600, "request too large"))
            return
        raw = self.rfile.read(length) if length else b""

        try:
            message = json.loads(raw or b"null")
        except json.JSONDecodeError as exc:
            self._send(400, _jsonrpc_error(None, -32700, f"parse error: {exc}"))
            return

        try:
            if isinstance(message, list):
                responses = [r for r in (mcp_server.handle(m) for m in message)
                             if r is not None]
                if not responses:
                    self._send(202)
                    return
                self._send(200, responses, session_id=self._session_for(message))
                return

            if not isinstance(message, dict):
                self._send(400, _jsonrpc_error(None, -32600,
                                               "expected a JSON-RPC object or array"))
                return

            response = mcp_server.handle(message)
            if response is None:
                # A notification. Nothing to say, and saying nothing is correct.
                self._send(202)
                return
            self._send(200, response, session_id=self._session_for([message]))
        except Exception as exc:                                # pragma: no cover
            sys.stderr.write(traceback.format_exc())
            rid = message.get("id") if isinstance(message, dict) else None
            self._send(500, _jsonrpc_error(rid, -32603,
                                           f"{type(exc).__name__}: {exc}"))

    def _session_for(self, messages):
        """Issue a session id on initialize, otherwise echo what came in."""
        for m in messages:
            if isinstance(m, dict) and m.get("method") == "initialize":
                return secrets.token_urlsafe(16)
        return self.headers.get("Mcp-Session-Id")

    def log_message(self, fmt, *args):
        sys.stderr.write("[mcp-http] %s %s\n" % (self.address_string(), fmt % args))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default loopback; a reverse proxy "
                         "should be the only route in)")
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args(argv)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    sys.stderr.write(
        f"[mcp-http] cable-sizing {mcp_server.SERVER_INFO['version']} on "
        f"http://{args.host}:{args.port}/mcp "
        f"({'bearer token required' if TOKEN else 'no auth'})\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
