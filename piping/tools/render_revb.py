#!/usr/bin/env python3
"""Draw the Rev B chilled-water routes for review.

  python3 tools/render_revb.py [private/revb_chw.json] [--out private/renders]

Writes, as SVG and (when rsvg-convert is installed) PNG:
  revb_router  the router's batch routes, hand routes dashed underneath
  revb_hand    the hand routes on their own, with any rule they break
Output goes under private/, which is not committed: it is project data.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import service  # noqa: E402
from core.render import render_sheet, svg_to_png  # noqa: E402
from bench_revb import DEFAULT, load  # noqa: E402


def _length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=DEFAULT)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "private",
                                                  "renders"))
    args = ap.parse_args()
    data, _, items = load(args.path)
    os.makedirs(args.out, exist_ok=True)
    ports = data["ports"]

    def nozzle(pid):
        return {"id": pid, "pos": ports[pid]["pos"], "dir": ports[pid]["dir"]}

    req = {"pipes": [{"id": p["id"], "dn": p["dn"], "from": nozzle(p["from"]),
                      "to": nozzle(p["to"])} for p, *_ in items],
           "obstacles": data["obstacles"]}
    batch = service.route_batch(req)
    by_id = {p["id"]: p for p, *_ in items}

    def drawn(r):
        p = by_id[r["id"]]
        base = {"id": r["id"], "od": r["spec"]["od"],
                "bend_radius": r["spec"]["bend_radius"],
                "service": p.get("service"),
                "from_pos": ports[p["from"]]["pos"],
                "to_pos": ports[p["to"]]["pos"]}
        if r["status"] == "routed":
            return {**base, "points": r["points"],
                    "issues": r["validation"]["issues"]}
        return {**base, "reason": r["reason"]}

    router = [drawn(r) for r in batch["results"]]
    hand = []
    for p, spec, a, b in items:
        v = service.validate({"dn": p["dn"], "points": p["points"],
                              "from": nozzle(p["from"]), "to": nozzle(p["to"]),
                              "obstacles": data["obstacles"]})
        hand.append({"id": p["id"], "od": spec.od,
                     "bend_radius": spec.bend_radius,
                     "service": p.get("service"), "points": p["points"],
                     "from_pos": a.pos, "to_pos": b.pos,
                     "issues": v["issues"]})

    rl = sum(_length(r["points"]) for r in router if r.get("points")) / 1000
    hl = sum(_length(h["points"]) for h in hand) / 1000
    re_ = sum(len(r["points"]) - 2 for r in router if r.get("points"))
    he = sum(len(h["points"]) - 2 for h in hand)
    caveat = ("Obstacles are the ones the build script places (skids, "
              "headers, tanks). Chillers, fan walls and the building are not "
              "in this scene.")
    sheets = {
        "revb_router": render_sheet(
            data["obstacles"], router, ("plan", "front", "iso"),
            title="Rev B chilled water: router (batch), hand routes dashed",
            notes=[f"{batch['routed']}/{len(router)} routed, {rl:.1f} m, "
                   f"{re_} elbows (hand: {hl:.1f} m, {he} elbows). "
                   f"sd-dc piping {service.VERSION}, request "
                   f"{batch['request_sha256'][:12]}", caveat],
            ghosts=hand),
        "revb_hand": render_sheet(
            data["obstacles"], hand, ("plan", "front", "iso"),
            title="Rev B chilled water: hand routes",
            notes=[f"{len(hand)} pipes, {hl:.1f} m, {he} elbows. Red marks "
                   f"a run that breaks a routing rule.", caveat]),
    }
    # The two plant rooms are tens of metres apart; at site scale the
    # detail is lost, so each also gets a sheet of its own.
    for side, prefix in (("west", "P-W-"), ("east", "P-E-")):
        mine = [r for r in router if r["id"].startswith(prefix)]
        pts = [q for r in mine for q in (r.get("points") or [])]
        pts += [r[k] for r in mine for k in ("from_pos", "to_pos")]
        if not pts:
            continue
        focus = ([min(q[i] for q in pts) - 1500 for i in range(3)],
                 [max(q[i] for q in pts) + 1500 for i in range(3)])
        focus[0][2] = min(focus[0][2], 0)
        sheets[f"revb_router_{side}"] = render_sheet(
            data["obstacles"], mine, ("plan", "front", "side", "iso"),
            title=f"Rev B chilled water, {side} plant: router (batch), "
                  f"hand routes dashed",
            notes=[caveat],
            ghosts=[h for h in hand if h["id"].startswith(prefix)],
            focus=focus)
    for name, svg in sheets.items():
        path = os.path.join(args.out, name)
        with open(path + ".svg", "w", encoding="utf-8") as fh:
            fh.write(svg)
        png = svg_to_png(svg)
        if png:
            with open(path + ".png", "wb") as fh:
                fh.write(png)
        print(path + (".png" if png else ".svg"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
