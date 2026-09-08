"""Ezystrut tray selection for a computed cable bundle.

Reads ../cable-tray-ezystrut/tray_catalogue.json, the sibling component's
structured product data, the same way cable_sizing reads ../cables. One source
of truth for the tray range rather than a second copy of it here.

The selection rule is deliberately narrow. These cables are single-core power
laid touching in ONE LAYER, which is what the AS/NZS 3008 unenclosed-touching
rating assumes, so the binding dimension is tray WIDTH, not fill depth. The
50% fill guidance in the tray component's GUIDELINES.md is for bunched cables
filling a tray's depth and does not apply to a single layer; applying it here
would double the tray width for no thermal reason and would contradict the
rating the cable was sized on.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
import tables

CATALOGUE_PATH = tables.path_for("ezystrut")

# A single layer of cables never fills the depth, so only width is checked.
# This is the working clearance left each side for cleats, hold-downs and the
# fact that nobody lays cable to the millimetre.
SIDE_CLEARANCE_MM = 25.0


def load(path=CATALOGUE_PATH):
    with open(path) as fh:
        return json.load(fh)


def rating_at_span(family, span_mm):
    """Published uniformly distributed load at a support span, kg/m.

    Spans between published points take the next SHORTER span's figure, which
    is the conservative direction, and spans beyond the longest published point
    return None rather than an extrapolation.
    """
    pts = sorted(family.get("load_ratings", []),
                 key=lambda p: p["span_mm"], reverse=True)
    if not pts:
        return None, None
    if span_mm > pts[0]["span_mm"]:
        return None, None
    for p in pts:
        if span_mm >= p["span_mm"]:
            return p["load_kg_per_m"], p["deflection_mm"]
    return pts[-1]["load_kg_per_m"], pts[-1]["deflection_mm"]


def select(cable_width_mm, cable_mass_kg_per_m, family_id="ET5",
           span_mm=3000.0, catalogue=None):
    """Smallest tray in a family that fits the bundle, plus its load check."""
    cat = catalogue or load()
    fam = cat["families"][family_id]
    need = cable_width_mm + 2 * SIDE_CLEARANCE_MM

    width = next((w for w in sorted(fam["widths_mm"]) if w >= need), None)
    if width is None:
        widest = max(fam["widths_mm"])
        return {"fits": False, "family": family_id,
                "required_width_mm": need, "widest_mm": widest,
                "reason": f"{need:.0f} mm needed, widest {family_id} is "
                          f"{widest} mm; split the run across two trays or use "
                          f"a wider family"}

    self_w = fam.get("self_weight_kg_per_m", {}).get(str(width))
    interpolated = str(width) in fam.get("self_weight_interpolated", [])
    limit, deflection = rating_at_span(fam, span_mm)
    total = cable_mass_kg_per_m + (self_w or 0.0)
    return {
        "fits": True,
        "family": family_id,
        "part": fam["part_pattern"].replace("{width}", str(width)),
        "width_mm": width,
        "overall_width_mm": width + fam.get("overall_width_allowance_mm", 0),
        "required_width_mm": need,
        "spare_width_mm": width - need,
        "cable_depth_mm": fam["cable_depth_mm"],
        "standard_length_mm": fam["standard_length_mm"],
        "self_weight_kg_per_m": self_w,
        "self_weight_interpolated": interpolated,
        "cable_mass_kg_per_m": cable_mass_kg_per_m,
        "total_load_kg_per_m": total,
        "span_mm": span_mm,
        "load_limit_kg_per_m": limit,
        "deflection_mm": deflection,
        "load_ok": None if limit is None else total <= limit,
        "load_utilisation_pct": None if not limit else 100.0 * total / limit,
    }
