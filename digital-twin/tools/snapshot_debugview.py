#!/usr/bin/env python3
"""Render the debug dashboard headlessly from a simulated run.

Same drawing code the live view uses, fed the same telemetry frames, so this
doubles as proof the dashboard works and as a way to put a picture of the twin
in a doc without screen-recording a window.

    ./tools/snapshot_debugview.py --scenario scenarios/west_fanwall_trip.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rom"))

from dthall import telemetry, topology  # noqa: E402
from dthall.debugview import DebugView  # noqa: E402
from dthall.profiles import ProfileConfig  # noqa: E402
from dthall.sim import SimEngine  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "debugview.png")
    ap.add_argument("--until", type=float, default=None, help="stop at this sim time")
    ap.add_argument("--sample-s", type=float, default=5.0)
    args = ap.parse_args(argv)

    spec = topology.from_cfd_export()
    scenario = json.loads(args.scenario.read_text()) if args.scenario else {}
    engine = SimEngine(
        spec,
        mode=scenario.get("mode", "auto"),
        seed=int(scenario.get("seed", 0)),
        profile_config=(
            ProfileConfig(**scenario["profile"]) if "profile" in scenario else None
        ),
    )
    engine.settle()

    view = DebugView()
    view.hello = telemetry.encode_hello(spec, engine.dt, 10.0)

    duration = args.until or float(scenario.get("duration_s", 1800.0))
    pending = sorted(scenario.get("commands", []), key=lambda c: c["t"])
    t0 = engine.state.t
    elapsed = next_sample = 0.0

    while elapsed <= duration:
        while pending and pending[0]["t"] <= elapsed:
            cmd = dict(pending.pop(0))
            cmd.pop("t", None)
            telemetry.apply_command(
                engine, telemetry.parse_command({"type": "cmd", **cmd})
            )
        snap = engine.advance(engine.dt)
        elapsed = snap.t - t0
        if elapsed >= next_sample:
            next_sample += args.sample_s
            view._record(telemetry.encode_state(snap, spec))

    fig, axes = view.make_figure()
    view.draw(fig, axes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=90)
    last = view.latest
    print(
        f"wrote {args.out}\n"
        f"  t={last['t_sim']:.0f}s mode={last['mode']} verdict={last['verdict']}\n"
        f"  IT {last['totals']['it_kw']:.0f} kW, cooling {last['totals']['cooling_kw']:.0f} kW, "
        f"storage {last['totals']['storage_kw']:+.0f} kW\n"
        f"  worst rack {last['totals']['worst_rack']} at {last['totals']['worst_t_in']:.2f} C"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
