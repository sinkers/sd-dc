#!/usr/bin/env python3
"""MCP server over stdio for the pipe router.

  python3 mcp_server.py

Standard library only, the same arrangement as cable-sizing/mcp_server.py:
JSON-RPC 2.0 as line-delimited JSON on stdin and stdout. Every tool calls
`service.py`, the same module behind the REST API.

Register it with Claude Code:

  claude mcp add piping -- python3 /ABS/PATH/TO/piping/mcp_server.py

What the tools do and do not do: they plan centrelines and check them. A route
that cannot be built is returned as data with a reason, the nozzle and
obstacle involved and a suggested fix, never as a route that looks fine and
is not. Solid geometry (STEP, glTF) is a separate job on the CAD host and is
not offered here yet.
"""
from __future__ import annotations

import json
import sys
import traceback

import openapi
import service

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "piping", "version": service.VERSION}

_UNITS = ("All positions in mm. A nozzle is {id, pos:[x,y,z], dir:[dx,dy,dz]} "
          "with dir pointing out of the equipment face, along an axis. "
          "Obstacles are boxes {id, min:[x,y,z], max:[x,y,z]}.")

TOOLS = [
    {
        "name": "piping_route_pipe",
        "title": "Route one pipe",
        "description": (
            "Route one pipe from an outlet nozzle to an inlet nozzle around "
            "box obstacles, with 90 degree long-radius elbows. Returns the "
            "corner points, the straights and elbows, lengths, a bill of "
            "materials, the validation result and an IndustroML connection "
            "to write into the model. If no buildable route exists, returns "
            "status 'failed' with a reason (blocked_nozzle, enclosed_inlet, "
            "enclosed_outlet, no_path, no_path_within_budget), the nozzle "
            "and obstacle involved, what was measured and suggested fixes. "
            + _UNITS),
        "inputSchema": service.ROUTE_SCHEMA,
    },
    {
        "name": "piping_route_network",
        "title": "Route several pipes",
        "description": (
            "Route a list of pipes in order. Each routed pipe becomes an "
            "obstacle for the ones after it, and pipes that meet at a shared "
            "nozzle (a tee) may run close there. One call for a whole loop, "
            "not one per pipe. A failed pipe does not stop the others; "
            "status is routed, partial or failed, with a combined bill of "
            "materials. Order matters: route the most constrained pipes "
            "first. " + _UNITS),
        "inputSchema": service.NETWORK_SCHEMA,
    },
    {
        "name": "piping_validate_route",
        "title": "Check a drawn route",
        "description": (
            "Check corner points you drew yourself against the routing "
            "rules: starts and ends on the nozzles, leaves and arrives along "
            "their axes, orthogonal runs, no 180 degree turns, runs long "
            "enough for their elbows, and clearance from obstacles. Returns "
            "each issue with a code and the run it is on. " + _UNITS),
        "inputSchema": service.VALIDATE_SCHEMA,
    },
    {
        "name": "piping_list_specs",
        "title": "List pipe sizes",
        "description": ("Pipe sizes held: DN, outside diameter, wall and "
                        "bend radius, Sch 10S, long-radius elbows."),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

RESOURCES = [
    {"uri": "piping://meta", "name": "Routing rules and limits",
     "description": "Rules, failure reasons, default options and limits.",
     "mimeType": "application/json"},
    {"uri": "piping://specs", "name": "Pipe sizes",
     "description": "DN, OD, wall and bend radius for every size held.",
     "mimeType": "application/json"},
    {"uri": "piping://openapi", "name": "REST API description",
     "description": "OpenAPI 3.1 description of the equivalent REST API.",
     "mimeType": "application/json"},
]

INSTRUCTIONS = (
    "Orthogonal pipe routing between equipment nozzles. Use "
    "piping_route_network for more than one pipe. A failed route is data: "
    "read reason, obstacle and suggest, change the layout or the order, and "
    "try again; do not draw your own route to get around a failure without "
    "checking it with piping_validate_route.")


def _text(obj):
    return {"content": [{"type": "text",
                         "text": json.dumps(obj, indent=1, allow_nan=False)}]}


def _error(message):
    return {"content": [{"type": "text", "text": message}], "isError": True}


def call_tool(name, args):
    args = args or {}
    if name == "piping_route_pipe":
        return _text(service.route(args))
    if name == "piping_route_network":
        return _text(service.route_batch(args))
    if name == "piping_validate_route":
        return _text(service.validate(args))
    if name == "piping_list_specs":
        return _text(service.specs())
    raise ValueError(f"unknown tool {name!r}, expected one of "
                     f"{[t['name'] for t in TOOLS]}")


def read_resource(uri):
    bodies = {"piping://meta": service.meta, "piping://specs": service.specs,
              "piping://openapi": openapi.spec}
    if uri not in bodies:
        raise ValueError(f"unknown resource {uri!r}")
    return {"contents": [{"uri": uri, "mimeType": "application/json",
                          "text": json.dumps(bodies[uri](), indent=1)}]}


def handle(req):
    """Dispatch one JSON-RPC request. Returns a response, or None for a notify."""
    method = req.get("method")
    params = req.get("params") or {}
    rid = req.get("id")
    if rid is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return ok({"protocolVersion": version,
                   "capabilities": {"tools": {}, "resources": {}},
                   "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "resources/list":
        return ok({"resources": RESOURCES})
    if method == "resources/read":
        try:
            return ok(read_resource(params.get("uri")))
        except ValueError as exc:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32602, "message": str(exc)}}
    if method == "tools/call":
        try:
            return ok(call_tool(params.get("name"), params.get("arguments")))
        except ValueError as exc:
            # A refusal the caller can act on, surfaced as a tool error so
            # the model can read it.
            return ok(_error(str(exc)))
        except Exception as exc:                       # pragma: no cover
            return ok(_error(f"{type(exc).__name__}: {exc}\n"
                             f"{traceback.format_exc()}"))
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                  "error": {"code": -32700,
                                            "message": f"parse error: {exc}"}}) + "\n")
            out.flush()
            continue
        resp = handle(req)
        if resp is not None:
            out.write(json.dumps(resp, allow_nan=False) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
