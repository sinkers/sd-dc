#!/usr/bin/env python3
"""MCP server over stdio for the cable sizing engine.

  python3 mcp_server.py

Standard library only: JSON-RPC 2.0 framed as line-delimited JSON on stdin and
stdout, which is what MCP stdio transport is. No SDK, so there is nothing to
install and nothing to keep in step with.

Every tool calls `service.py`, the same module behind the web UI and the REST
API, so an agent and a person asking the same question get the same answer.

Register it with Claude Code:

  claude mcp add cable-sizing -- python3 /ABS/PATH/TO/cable-sizing/mcp_server.py

or by hand in a client config:

  {"mcpServers": {"cable-sizing": {"command": "python3",
                                   "args": ["/ABS/PATH/mcp_server.py"]}}}

A note on what the tools will and will not do, because it is the whole point of
the design: `size_cable` selects a conductor and works only for AS/NZS 3008.1.1,
the one standard whose current-carrying capacity table is held here.
`check_cable_size` verifies a size the caller nominates against a rating the
caller supplies, and works under all four standards. Neither will invent an
ampacity, and an agent that asks for one gets an error explaining where to read
the real number.
"""
from __future__ import annotations

import json
import sys
import traceback

import install_diagrams
import service
import standards

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "cable-sizing", "version": service.VERSION}

_STD_IDS = sorted(standards.STANDARDS)
_METHOD_HINT = ("Installation method id, which differs by standard. Call "
                "list_standards to see the valid ids. Defaults to the "
                "standard's first method.")

_COMMON = {
    "rating_value": {"type": "number",
                     "description": "Load rating magnitude, e.g. 250."},
    "rating_kind": {"type": "string", "enum": ["kw", "kva", "amps"],
                    "default": "kw"},
    "power_factor": {"type": "number", "default": 0.9},
    "voltage_v": {"type": "number", "default": 415,
                  "description": "Nominal phase-to-phase voltage."},
    "phase_mode": {"type": "string",
                   "enum": ["3-phase", "1-phase", "DC", "2-phase-120",
                            "2-phase-180"], "default": "3-phase"},
    "route_length_m": {"type": "number", "default": 50},
    "fault_level_ka": {"type": "number", "default": 25},
    "clearing_time_s": {"type": "number", "default": 0.2},
    "standard": {"type": "string", "enum": _STD_IDS,
                 "default": standards.DEFAULT},
    "method": {"type": "string", "description": _METHOD_HINT},
    "formation": {
        "type": "string", "enum": ["trefoil", "flat_touching"],
        "description":
            "How single-core cables sit relative to each other. INDEPENDENT of "
            "`method`: trefoil on an unenclosed-touching tray is the common "
            "case. Trefoil has about 19 % less reactance than flat, so leaving "
            "it unstated makes the engine guess and warn, and the guess can "
            "push the selection a size larger than needed. Ignored for "
            "multicore. Defaults to trefoil for conduit and buried methods, "
            "flat_touching otherwise.",
    },
    "cable_type": {"type": "string", "default": "XLPE_SDI_CU",
                   "description": "Catalogue family. Call list_cable_types."},
    "ambient_c": {"type": "number",
                  "description": "Defaults to the standard's reference ambient."},
    "n_circuits": {"type": "integer", "default": 1,
                   "description": "Grouped circuits, for the grouping factor."},
    "harmonic_content_pct": {
        "type": "number", "default": 0,
        "description": "Third-and-higher-order harmonic current as a percentage "
                       "of phase current. At or above 40% the neutral is sized "
                       "on the neutral current instead of matching the active, "
                       "which matters for IT and VSD loads."},
    "max_voltage_drop_pct": {"type": "number",
                             "description": "Overrides the standard's limit."},
    "vd_supply": {"type": "string", "default": "public",
                  "description": "Supply arrangement row of the standard's "
                                 "voltage drop table."},
    "vd_use": {"type": "string", "enum": ["lighting", "other"],
               "default": "other"},
    "protection_type": {"type": "string", "enum": ["", "MCB"],
                        "description": "Set to MCB, with mcb_rating_a, to turn "
                                       "on the earth fault loop check."},
    "mcb_curve": {"type": "string", "enum": ["B", "C", "D"], "default": "C"},
    "mcb_rating_a": {"type": "number"},
}

_SIZE_SCHEMA = {
    "type": "object",
    "properties": {**_COMMON,
                   "max_parallel": {"type": "integer", "default": 4}},
    "required": ["rating_value"],
}

_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        **_COMMON,
        "area_mm2": {"type": "number",
                     "description": "The conductor size to check, in mm2."},
        "tabulated_rating_a": {
            "type": "number",
            "description": "Current-carrying capacity read from the standard's "
                           "own table for this size and method. Required for "
                           "every standard except AS/NZS, whose table is held "
                           "here."},
        "parallel": {"type": "integer", "default": 1},
    },
    "required": ["rating_value", "area_mm2"],
}

TOOLS = [
    {
        "name": "size_cable",
        "title": "Select a cable size",
        "description": (
            "Select the smallest conductor that passes current-carrying "
            "capacity, voltage drop, short-circuit withstand and, when a "
            "protective device is declared, earth fault loop impedance. "
            "Returns the active, neutral and earth sizes with every check and "
            "its margin, the full working, and matching manufacturer cables.\n\n"
            "AS/NZS 3008.1.1 only. The other three standards have no rating "
            "table here, so use check_cable_size for those; calling this with "
            "one returns an error saying which table to read."),
        "inputSchema": _SIZE_SCHEMA,
    },
    {
        "name": "check_cable_size",
        "title": "Check a nominated cable size",
        "description": (
            "Check a conductor size you nominate rather than selecting one. "
            "Works under AS/NZS 3008.1.1, IEC 60364-5-52, BS 7671 and the NEC. "
            "For anything but AS/NZS, supply tabulated_rating_a from that "
            "standard's own table; everything else -- design current, "
            "derating, operating temperature, voltage drop, the adiabatic "
            "short-circuit check, earth sizing and the loop impedance check -- "
            "runs on that standard's rules. Every check is returned with its "
            "margin whether it passes or fails."),
        "inputSchema": _CHECK_SCHEMA,
    },
    {
        "name": "list_standards",
        "title": "List cable sizing standards",
        "description": (
            "The four standard profiles: reference ambient and soil model, "
            "installation methods with their ids and diagram keys, voltage "
            "drop limits, the IEC voltage factor, units, and whether the "
            "profile can select a size or only check one."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_cable_types",
        "title": "List catalogue cable types",
        "description": ("Cable families in the catalogue with their conductor, "
                        "insulation, voltage, temperature rating and the sizes "
                        "held."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_installation_diagram",
        "title": "Get an installation diagram",
        "description": ("SVG diagram for an installation arrangement, showing "
                        "the geometry that sets the rating: spacing, the "
                        "surface, the enclosure, the soil and the depth. Keys "
                        "come from the `diagram` field of a method in "
                        "list_standards."),
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string",
                                   "enum": sorted(install_diagrams.DIAGRAMS),
                                   "description": "Diagram key."}},
            "required": ["key"],
        },
    },
]

RESOURCES = [
    {"uri": "cable-sizing://standards",
     "name": "Standard profiles",
     "description": "All four cable sizing standard profiles as JSON.",
     "mimeType": "application/json"},
    {"uri": "cable-sizing://cable-types",
     "name": "Cable catalogue",
     "description": "Catalogue cable families and the sizes held.",
     "mimeType": "application/json"},
    {"uri": "cable-sizing://openapi",
     "name": "REST API description",
     "description": "OpenAPI 3.1 description of the equivalent REST API.",
     "mimeType": "application/json"},
]


def _text(obj):
    return {"content": [{"type": "text",
                         "text": json.dumps(obj, indent=1, allow_nan=False)}]}


def _error(message):
    return {"content": [{"type": "text", "text": message}], "isError": True}


def call_tool(name, args):
    args = args or {}
    if name == "size_cable":
        return _text(service.size(args))
    if name == "check_cable_size":
        return _text(service.check(args))
    if name == "list_standards":
        return _text(service.list_standards())
    if name == "list_cable_types":
        return _text(service.list_cable_types())
    if name == "get_installation_diagram":
        key = args.get("key")
        if key not in install_diagrams.DIAGRAMS:
            raise ValueError(
                f"unknown diagram {key!r}, expected one of "
                f"{sorted(install_diagrams.DIAGRAMS)}")
        return {"content": [{"type": "text", "text": service.diagram(key)}]}
    raise ValueError(f"unknown tool {name!r}, expected one of "
                     f"{[t['name'] for t in TOOLS]}")


def read_resource(uri):
    import openapi
    bodies = {
        "cable-sizing://standards": service.list_standards,
        "cable-sizing://cable-types": service.list_cable_types,
        "cable-sizing://openapi": openapi.spec,
    }
    if uri not in bodies:
        raise ValueError(f"unknown resource {uri!r}")
    return {"contents": [{"uri": uri, "mimeType": "application/json",
                          "text": json.dumps(bodies[uri](), indent=1)}]}


def handle(req):
    """Dispatch one JSON-RPC request. Returns a response, or None for a notify."""
    method = req.get("method")
    params = req.get("params") or {}
    rid = req.get("id")

    # Notifications carry no id and must not be answered.
    if rid is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return ok({
            "protocolVersion": version,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Cable sizing to AS/NZS 3008.1.1, IEC 60364-5-52, BS 7671 and "
                "the NEC. size_cable selects a conductor and is AS/NZS only, "
                "because that is the only standard whose rating table is held "
                "here. check_cable_size verifies a size you nominate against a "
                "rating you supply and works under all four. No ampacity is "
                "ever derived for a standard whose table is absent."),
        })
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
        name = params.get("name")
        try:
            return ok(call_tool(name, params.get("arguments")))
        except ValueError as exc:
            # A refusal the caller can act on: surfaced as a tool error with the
            # message intact, not a protocol error, so the model can read it.
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
