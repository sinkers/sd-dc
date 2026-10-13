#!/usr/bin/env python3
"""Route the Rev B pipes from their ports and compare with the hand routes.

  python3 tools/bench_revb.py [private/revb_chw.json] [--network] [--json out]

For each pipe: does the router find a route, how long is it and how many
elbows does it have, against the hand-drawn route between the same ports.
The hand route is also run through the validator against the same
obstacles, so a disagreement can be told apart from a modelling gap.

--network routes all 34 in schedule order with each routed pipe becoming an
obstacle for the next, which is how the service routes a batch.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core import (Box, Nozzle, RouteOptions, route_network, route_pipe,  # noqa: E402
                  spec_for, validate_route)

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "private", "revb_chw.json")


def length(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def load(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    obstacles = [Box(o["id"], tuple(o["min"]), tuple(o["max"]))
                 for o in data["obstacles"]]
    items = []
    for p in data["pipes"]:
        a, b = data["ports"][p["from"]], data["ports"][p["to"]]
        items.append((p, spec_for(p["dn"]),
                      Nozzle(p["from"], tuple(a["pos"]), tuple(a["dir"])),
                      Nozzle(p["to"], tuple(b["pos"]), tuple(b["dir"]))))
    return data, obstacles, items


def run(path, network=False, opts=None):
    data, obstacles, items = load(path)
    opts = opts or RouteOptions()
    if network:
        results = dict(route_network([(p["id"], s, a, b) for p, s, a, b in items],
                                     obstacles, opts))
    rows = []
    for p, spec, a, b in items:
        res = results[p["id"]] if network else route_pipe(spec, a, b,
                                                          obstacles, opts)
        hand = [tuple(x) for x in p["points"]]
        hand_issues = validate_route(hand, spec, a, b, obstacles,
                                     opts.clearance_mm)
        row = {"id": p["id"], "dn": p["dn"],
               "hand_m": round(length(hand) / 1000, 2),
               "hand_elbows": len(hand) - 2,
               "hand_issues": [i["code"] for i in hand_issues],
               "ok": res.ok, "ms": round(res.ms)}
        if res.ok:
            row.update(router_m=round(length(res.points) / 1000, 2),
                       router_elbows=len(res.points) - 2,
                       router_issues=[i["code"] for i in validate_route(
                           res.points, spec, a, b, obstacles,
                           opts.clearance_mm)])
        else:
            row["failure"] = res.failure
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=DEFAULT)
    ap.add_argument("--network", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args()
    if not os.path.exists(args.path):
        print(f"no benchmark at {args.path}; run tools/extract_revb.py first")
        return 2
    rows = run(args.path, args.network)
    print(f"{'pipe':8} {'DN':>4} {'hand m':>7} {'elb':>3}  {'router m':>8} "
          f"{'elb':>3} {'ms':>6}  notes")
    for r in rows:
        if r["ok"]:
            print(f"{r['id']:8} {r['dn']:>4} {r['hand_m']:>7} "
                  f"{r['hand_elbows']:>3}  {r['router_m']:>8} "
                  f"{r['router_elbows']:>3} {r['ms']:>6}  "
                  f"{' '.join(r['hand_issues']) and 'hand: ' + ','.join(r['hand_issues'])}")
        else:
            print(f"{r['id']:8} {r['dn']:>4} {r['hand_m']:>7} "
                  f"{r['hand_elbows']:>3}  {'FAILED':>8} {'':>3} {r['ms']:>6}  "
                  f"{r['failure']['reason']}: {r['failure'].get('detail', '')}")
    ok = [r for r in rows if r["ok"]]
    print(f"\nrouted {len(ok)}/{len(rows)}")
    if ok:
        hm = sum(r["hand_m"] for r in ok)
        rm = sum(r["router_m"] for r in ok)
        he = sum(r["hand_elbows"] for r in ok)
        re_ = sum(r["router_elbows"] for r in ok)
        worse = [r["id"] for r in ok if r["router_m"] > r["hand_m"] + 0.01
                 or r["router_elbows"] > r["hand_elbows"]]
        print(f"length  hand {hm:.1f} m, router {rm:.1f} m")
        print(f"elbows  hand {he}, router {re_}")
        print(f"router longer or more elbows on: {', '.join(worse) or 'none'}")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(rows, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
