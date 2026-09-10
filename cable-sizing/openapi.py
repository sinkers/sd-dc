"""OpenAPI 3.1 description of the cable sizing REST API.

Hand-written rather than generated, because the interesting part of this API is
not its field types but which operation is legitimate under which standard:
`/api/size` selects a size and only works where we hold a rating table,
`/api/check` verifies a size you nominate and works everywhere. The spec says so
in the descriptions so a client, human or agent, does not have to find out by
getting a 400.
"""
from __future__ import annotations

import service
import standards

_STD_IDS = sorted(standards.STANDARDS)

_LOAD_SUPPLY_PROPS = {
    "source_name": {"type": "string", "default": "Source"},
    "load_name": {"type": "string", "default": "Load"},
    "rating_value": {"type": "number", "description": "Load rating magnitude.",
                     "example": 250},
    "rating_kind": {"type": "string", "enum": ["kw", "kva", "amps"],
                    "default": "kw"},
    "power_factor": {"type": "number", "default": 0.9, "minimum": 0,
                     "maximum": 1, "example": 0.95},
    "voltage_v": {"type": "number", "default": 415,
                  "description": "Nominal phase-to-phase voltage."},
    "phase_mode": {"type": "string",
                   "enum": ["3-phase", "1-phase", "DC", "2-phase-120",
                            "2-phase-180"],
                   "default": "3-phase"},
    "route_length_m": {"type": "number", "default": 50, "example": 85},
    "fault_level_ka": {"type": "number", "default": 25,
                       "description": "Prospective fault level at the source."},
    "clearing_time_s": {"type": "number", "default": 0.2},
    "harmonic_content_pct": {
        "type": "number", "default": 0,
        "description": "Third-and-higher-order harmonic current as a percentage "
                       "of phase current. At or above 40% the neutral is sized "
                       "on the neutral current, not matched to the active."},
    "out_of_balance_pct": {"type": "number", "default": 100},
    "max_voltage_drop_pct": {
        "type": "number", "nullable": True,
        "description": "Overrides the standard's own limit when given."},
    "standard": {"type": "string", "enum": _STD_IDS,
                 "default": standards.DEFAULT},
    "method": {"type": "string",
               "description": "Installation method id, which is specific to the "
                              "standard. GET /api/standards lists the valid ids "
                              "and their diagrams."},
    "formation": {"type": "string", "enum": ["trefoil", "flat_touching"],
                  "nullable": True,
                  "description": "Single-core formation, independent of "
                                 "`method`. Trefoil carries about 19 % less "
                                 "reactance than flat touching. Unset, it is "
                                 "guessed from the method and a warning is "
                                 "raised."},
    "cable_type": {"type": "string", "default": "XLPE_SDI_CU"},
    "ambient_c": {"type": "number", "nullable": True,
                  "description": "Defaults to the standard's reference ambient."},
    "n_circuits": {"type": "integer", "default": 1, "minimum": 1},
    "max_parallel": {"type": "integer", "default": 4, "minimum": 1},
    "circuit_use": {"type": "string", "default": "other_circuits"},
    "dedicated_onsite_substation": {
        "type": "boolean", "default": False,
        "description": "AS/NZS 3000 clause 3.6.2 exception, raising the voltage "
                       "drop limit to 7%."},
    "vd_supply": {"type": "string", "enum": ["public", "private", "substation",
                                             "branch", "feeder_and_branch"],
                  "default": "public"},
    "vd_use": {"type": "string", "enum": ["lighting", "other"],
               "default": "other"},
    "protection_type": {"type": "string", "enum": ["", "MCB"], "default": "",
                        "description": "Declaring a device turns on the earth "
                                       "fault loop impedance check."},
    "mcb_curve": {"type": "string", "enum": ["B", "C", "D"], "default": "C"},
    "mcb_rating_a": {"type": "number", "nullable": True},
    "tabulated_rating_a": {
        "type": "number", "nullable": True,
        "description": "Current-carrying capacity read from the standard's own "
                       "table. Required for every standard except AS/NZS, "
                       "where it comes from the catalogue."},
}

_CHECK_PROPS = dict(_LOAD_SUPPLY_PROPS)
_CHECK_PROPS["area_mm2"] = {
    "type": "number",
    "description": "The conductor size to check, in mm2.", "example": 185}
_CHECK_PROPS["parallel"] = {"type": "integer", "default": 1, "minimum": 1}

_CHECK_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string",
                 "example": "current capacity"},
        "passed": {"type": "boolean"},
        "detail": {"type": "string"},
        "margin_pct": {"type": "number",
                       "description": "How far the candidate clears the "
                                      "requirement. Negative means it fails."},
    },
}

_RESULT = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["select", "check"]},
        "passed": {"type": "boolean"},
        "failure_reason": {"type": "string", "nullable": True},
        "standard": {"type": "object"},
        "installation": {
            "type": "object",
            "description": "The resolved method, including the `diagram` key "
                           "to fetch from /api/diagrams/{key}."},
        "inputs": {"type": "object"},
        "sizes": {
            "type": "object",
            "properties": {
                "active_mm2": {"type": "number", "nullable": True},
                "neutral_mm2": {
                    "type": "number", "nullable": True,
                    "description": "Null where harmonics require a larger "
                                   "neutral but the standard's ratings are "
                                   "user-supplied, so it could not be sized. "
                                   "The warnings say so."},
                "earth_mm2": {"type": "number", "nullable": True},
                "parallel_runs": {"type": "integer"},
            }},
        "currents": {"type": "object"},
        "derating": {"type": "object"},
        "voltage_drop": {"type": "object"},
        "fault": {"type": "object"},
        "thermal": {"type": "object"},
        "geometry": {"type": "object"},
        "max_loop_length_m": {"type": "number", "nullable": True},
        "checks": {"type": "array", "items": _CHECK_ITEM},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "summary_text": {"type": "string", "nullable": True},
        "manufacturers": {
            "type": "object",
            "description": "Nexans carries per-size ratings and drives sizing. "
                           "Tricab is a construction match only: its per-size "
                           "electrical data is behind a trade login and none is "
                           "held here."},
    },
}

_ERROR = {"type": "object",
          "properties": {"error": {"type": "string"}}}


def _json_body(schema_ref, required):
    return {"required": True,
            "content": {"application/json": {
                "schema": {"$ref": schema_ref},
            }}}


def spec(base_url=None):
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Cable Sizing API",
            "version": service.VERSION,
            "summary": "Low-voltage cable sizing to AS/NZS 3008.1.1, "
                       "IEC 60364-5-52, BS 7671 and the NEC.",
            "description": (
                "Two operations, and which one applies depends on the "
                "standard.\n\n"
                "**`POST /api/size` selects** the smallest conductor that "
                "passes current-carrying capacity, voltage drop, "
                "short-circuit withstand and earth fault loop impedance. It "
                "needs a current-carrying capacity table, and the only one "
                "held here is Nexans Australia data on the AS/NZS basis, so "
                "this operation is AS/NZS only.\n\n"
                "**`POST /api/check` verifies** a size you nominate against a "
                "`tabulated_rating_a` you read out of your standard's table, "
                "and runs every other calculation on that standard's rules. "
                "It works under all four.\n\n"
                "No ampacity is ever derived for a standard whose table we do "
                "not hold. Re-referencing the AS/NZS figures to a 30 C basis "
                "with the ambient closed form runs optimistic by up to 6.5%, "
                "and an optimistic factor undersizes cable, so the API asks "
                "for the number instead of inventing it."),
            "license": {"name": "Internal use"},
        },
        "servers": [{"url": base_url or "http://127.0.0.1:8765"}],
        "tags": [
            {"name": "sizing", "description": "Select or check a conductor."},
            {"name": "reference",
             "description": "Standards, cable types and installation diagrams."},
        ],
        "paths": {
            "/api/health": {"get": {
                "tags": ["reference"], "operationId": "health",
                "summary": "Liveness and loaded-data summary.",
                "responses": {"200": {"description": "Service is up",
                                      "content": {"application/json": {
                                          "schema": {"type": "object"}}}}}}},
            "/api/meta": {"get": {
                "tags": ["reference"], "operationId": "getMeta",
                "summary": "Everything the UI needs in one call.",
                "responses": {"200": {"description": "Metadata",
                                      "content": {"application/json": {
                                          "schema": {"type": "object"}}}}}}},
            "/api/standards": {"get": {
                "tags": ["reference"], "operationId": "listStandards",
                "summary": "All four standard profiles.",
                "description": "Each profile carries its reference ambient, "
                               "soil model, installation methods with diagram "
                               "keys, voltage drop limits, IEC voltage factor "
                               "and whether it can select a size.",
                "responses": {"200": {"description": "Profiles",
                                      "content": {"application/json": {
                                          "schema": {"type": "object"}}}}}}},
            "/api/standards/{standardId}": {"get": {
                "tags": ["reference"], "operationId": "getStandard",
                "summary": "One standard profile.",
                "parameters": [{"name": "standardId", "in": "path",
                                "required": True,
                                "schema": {"type": "string",
                                           "enum": _STD_IDS}}],
                "responses": {
                    "200": {"description": "Profile",
                            "content": {"application/json": {
                                "schema": {"type": "object"}}}},
                    "404": {"description": "Unknown standard",
                            "content": {"application/json": {
                                "schema": _ERROR}}}}}},
            "/api/cable-types": {"get": {
                "tags": ["reference"], "operationId": "listCableTypes",
                "summary": "Catalogue cable families and their sizes.",
                "responses": {"200": {"description": "Cable types",
                                      "content": {"application/json": {
                                          "schema": {"type": "object"}}}}}}},
            "/api/diagrams": {"get": {
                "tags": ["reference"], "operationId": "listDiagrams",
                "summary": "Every installation diagram as inline SVG.",
                "description": "Keyed by diagram id. Each installation method "
                               "in a standard profile names one of these keys. "
                               "Pair with the `diagram_css` field from "
                               "/api/meta for theme-aware colours.",
                "responses": {"200": {"description": "SVG markup by key",
                                      "content": {"application/json": {
                                          "schema": {"type": "object"}}}}}}},
            "/api/diagrams/{key}": {"get": {
                "tags": ["reference"], "operationId": "getDiagram",
                "summary": "One installation diagram as an SVG image.",
                "parameters": [{"name": "key", "in": "path", "required": True,
                                "schema": {"type": "string"}}],
                "responses": {"200": {
                    "description": "SVG",
                    "content": {"image/svg+xml": {
                        "schema": {"type": "string"}}}}}}},
            "/api/size": {"post": {
                "tags": ["sizing"], "operationId": "sizeFeeder",
                "summary": "Select the smallest conductor that passes.",
                "description": "AS/NZS 3008.1.1 only, because it is the only "
                               "standard whose rating table is held here. "
                               "Returns 400 for the others, naming "
                               "/api/check as the way to proceed.",
                "requestBody": _json_body("#/components/schemas/SizeRequest",
                                          True),
                "responses": {
                    "200": {"description": "Sizing result. Check `passed`: a "
                                           "200 with passed=false means no "
                                           "catalogue size satisfies the "
                                           "inputs.",
                            "content": {"application/json": {
                                "schema": {"$ref":
                                           "#/components/schemas/Result"}}}},
                    "400": {"description": "Invalid input, or a standard that "
                                           "cannot select",
                            "content": {"application/json": {
                                "schema": _ERROR}}}}}},
            "/api/check": {"post": {
                "tags": ["sizing"], "operationId": "checkFeeder",
                "summary": "Check a conductor size you nominate.",
                "description": "Works under all four standards. Supply "
                               "`area_mm2` and, for anything but AS/NZS, the "
                               "`tabulated_rating_a` from that standard's "
                               "table. Every check is returned with its "
                               "margin whether it passes or fails.",
                "requestBody": _json_body("#/components/schemas/CheckRequest",
                                          True),
                "responses": {
                    "200": {"description": "Check result",
                            "content": {"application/json": {
                                "schema": {"$ref":
                                           "#/components/schemas/Result"}}}},
                    "400": {"description": "Invalid input",
                            "content": {"application/json": {
                                "schema": _ERROR}}}}}},
        },
        "components": {"schemas": {
            "SizeRequest": {"type": "object", "properties": _LOAD_SUPPLY_PROPS,
                            "required": ["rating_value"]},
            "CheckRequest": {"type": "object", "properties": _CHECK_PROPS,
                             "required": ["rating_value", "area_mm2"]},
            "Result": _RESULT,
            "Error": _ERROR,
        }},
    }
