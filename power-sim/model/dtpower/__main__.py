"""dtpower command line.

    python3 -m dtpower serve [--port 8780]
    python3 -m dtpower run bess-dr --scenario nsw-spike [--set BESS-1.capacity_kwh=800 ...]
    python3 -m dtpower model bess-dr          # the IndustroML model, as JSON
    python3 -m dtpower scenarios bess-dr
"""

from __future__ import annotations

import argparse
import json
import sys

from .server import serve, tidy
from .sims import SIMS


def _value(s: str):
    for conv in (int, float):
        try:
            return conv(s)
        except ValueError:
            pass
    return {"true": True, "false": False}.get(s.lower(), s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dtpower")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8780)
    r = sub.add_parser("run")
    r.add_argument("sim", choices=SIMS)
    r.add_argument("--scenario")
    r.add_argument("--set", action="append", default=[], metavar="ASSET.KEY=VALUE")
    r.add_argument("--rows", action="store_true", help="include every time step, not just the summary")
    for name in ("model", "scenarios"):
        sub.add_parser(name).add_argument("sim", choices=SIMS)
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        serve(a.host, a.port)
        return 0
    sim = SIMS[a.sim]
    if a.cmd == "model":
        print(json.dumps(sim.model(), indent=1))
    elif a.cmd == "scenarios":
        for sc in sim.SCENARIOS:
            print(f"{sc['id']:22s} {sc['label']}")
    else:
        params: dict = {}
        for item in a.set:
            key, _, val = item.partition("=")
            asset, _, field = key.partition(".")
            if not field:
                ap.error(f"--set wants ASSET.KEY=VALUE, got {item!r}")
            params.setdefault(asset, {})[field] = _value(val)
        out = sim.simulate(a.scenario or sim.SCENARIOS[0]["id"], params)
        if not a.rows:
            out = {"scenario": out["scenario"]["label"], "summary": out["summary"]}
        json.dump(tidy(out, 2), sys.stdout, indent=1)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
