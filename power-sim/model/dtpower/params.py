"""Parameter schemas.

Every component declares its knobs as a flat list of fields. The model resolves
its values through that list and the viewer builds its controls from the same
list, served as JSON. A component dropped into a new simulation therefore brings
its own sliders, toggles and drop-downs with it.

A field is a plain dict, so it serialises without help::

    {"key", "label", "kind": "range" | "toggle" | "select", "default",
     "unit"?, "min"?, "max"?, "step"?, "options"?: [{"value", "label"}],
     "help"?, "advanced"?}
"""

from __future__ import annotations

import math
from typing import Any

Schema = list[dict[str, Any]]


def field(key: str, label: str, kind: str = "range", default: Any = None, **extra: Any) -> dict:
    return {"key": key, "label": label, "kind": kind, "default": default, **extra}


def resolve(schema: Schema, overrides: dict | None = None) -> dict:
    """Fill in defaults and clamp every value to what its field allows.

    Unknown keys are ignored rather than rejected: a composite passes its whole
    parameter dict down to each part, and each part takes what it knows.
    """
    overrides = overrides or {}
    out = {}
    for f in schema:
        v = overrides.get(f["key"], f["default"])
        kind = f["kind"]
        if kind == "range":
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = f["default"]
            if not math.isfinite(v):
                v = f["default"]
            if f.get("min") is not None:
                v = max(f["min"], v)
            if f.get("max") is not None:
                v = min(f["max"], v)
        elif kind == "toggle":
            v = bool(v)
        elif kind == "select":
            if v not in [o["value"] for o in f["options"]]:
                v = f["default"]
        out[f["key"]] = v
    return out


def defaults(schema: Schema) -> dict:
    return resolve(schema, {})


def override(schema: Schema, changes: dict | None = None, omit: tuple = ()) -> Schema:
    """Reuse another component's schema with some fields changed.

    A UPS battery is a Battery with a small capacity and a high C-rate, not a
    new schema::

        override(Battery.schema, {"capacity_kwh": {"default": 45}})
    """
    changes = changes or {}
    return [{**f, **changes.get(f["key"], {})} for f in schema if f["key"] not in omit]


def prefixed(schema: Schema, prefix: str) -> Schema:
    """Namespace a part's schema inside a composite: rated_kw -> pcs_rated_kw."""
    return [{**f, "key": f"{prefix}_{f['key']}"} for f in schema]


def unprefix(params: dict, prefix: str) -> dict:
    """The inverse of prefixed(): pull a part's parameters back out."""
    p = prefix + "_"
    return {k[len(p):]: v for k, v in params.items() if k.startswith(p)}
