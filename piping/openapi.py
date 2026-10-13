"""OpenAPI 3.1 description of the REST API in server.py.

Request schemas are the ones the MCP tools publish (service.py), so the two
interfaces cannot describe different inputs.
"""
from __future__ import annotations

import service


def _post(summary, schema, description):
    return {"post": {
        "summary": summary, "description": description,
        "requestBody": {"required": True, "content": {
            "application/json": {"schema": schema}}},
        "responses": {
            "200": {"description": "Result. A route that cannot be built is "
                                   "a 200 with status 'failed' and a "
                                   "reason, not an error.",
                    "content": {"application/json": {"schema": {
                        "type": "object"}}}},
            "400": {"description": "The request could not be read; the body "
                                   "says why.",
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {"error": {"type": "string"}}}}}},
        }}}


def _get(summary):
    return {"get": {"summary": summary, "responses": {"200": {
        "description": "OK", "content": {"application/json": {
            "schema": {"type": "object"}}}}}}}


def _render():
    op = _post("Draw routes for review", service.RENDER_SCHEMA,
               "Routes the pipes (or checks the points given) and draws "
               "plan, elevation and isometric views. ?format=svg (default), "
               "png (needs rsvg-convert on the server) or json (the result "
               "with the SVG in it).")
    op["post"]["parameters"] = [{
        "name": "format", "in": "query", "required": False,
        "schema": {"enum": ["svg", "png", "json"], "default": "svg"}}]
    op["post"]["responses"]["200"] = {"description": "The sheet.", "content": {
        "image/svg+xml": {"schema": {"type": "string"}},
        "image/png": {"schema": {"type": "string", "format": "binary"}},
        "application/json": {"schema": {"type": "object"}}}}
    op["post"]["responses"]["501"] = {"description": "PNG asked for and "
                                                     "rsvg-convert absent."}
    return op


def spec():
    return {
        "openapi": "3.1.0",
        "info": {"title": "sd-dc piping", "version": service.VERSION,
                 "description": "Orthogonal pipe routing between equipment "
                                "nozzles. Units are mm."},
        "paths": {
            "/api/health": _get("Liveness"),
            "/api/meta": _get("Rules, failure reasons, defaults and limits"),
            "/api/specs": _get("Pipe sizes held"),
            "/api/route": _post("Route one pipe", service.ROUTE_SCHEMA,
                                "Outlet nozzle to inlet nozzle around box "
                                "obstacles."),
            "/api/route/batch": _post("Route several pipes in order",
                                      service.NETWORK_SCHEMA,
                                      "Each routed pipe is an obstacle for "
                                      "the rest."),
            "/api/validate": _post("Check drawn corner points",
                                   service.VALIDATE_SCHEMA,
                                   "Returns each rule broken, with the run "
                                   "it is on."),
            "/api/render": _render(),
        },
    }
