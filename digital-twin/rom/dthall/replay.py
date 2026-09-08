"""Headless scripted scenarios — the regression harness for twin behaviour.

A scenario is a JSON file: a duration, a sample interval, and a list of commands
with the simulated time to apply them at. It runs with no wall clock and no
sockets, so it is fully deterministic, and it writes a CSV that can be diffed
between revisions.

    {
      "name": "west fan wall trips during a training run",
      "duration_s": 1800,
      "sample_s": 10,
      "mode": "auto",
      "seed": 7,
      "settle": true,
      "commands": [
        {"t": 600, "cmd": "set_unit", "unit": "W1", "on": false},
        {"t": 660, "cmd": "set_unit", "unit": "W2", "on": false},
        {"t": 1200, "cmd": "set_load", "target": "global", "kw": 20.0}
      ]
    }
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from . import telemetry
from .profiles import ProfileConfig
from .sim import SimEngine
from .topology import HallSpec

COLUMNS = [
    "t_sim",
    "mode",
    "phase",
    "verdict",
    "it_kw",
    "cooling_kw",
    "storage_kw",
    "balance_err",
    "supply_c",
    "hot_aisle_c",
    "return_c",
    "worst_rack",
    "worst_t_in_c",
    "worst_t_in_peak_c",
    "recirc_m3h",
    "modules_on",
]


def run_scenario(
    spec: HallSpec, script: Path, out: Path | None = None, quiet: bool = False
) -> int:
    scenario = json.loads(Path(script).read_text())
    dt = float(scenario.get("dt", 0.5))
    sample = float(scenario.get("sample_s", 10.0))
    duration = float(scenario["duration_s"])

    engine = SimEngine(
        spec,
        dt=dt,
        mode=scenario.get("mode", "auto"),
        seed=int(scenario.get("seed", 0)),
        profile_config=(
            ProfileConfig(**scenario["profile"]) if "profile" in scenario else None
        ),
    )
    if scenario.get("settle", True):
        engine.settle()

    pending = sorted(scenario.get("commands", []), key=lambda c: c["t"])
    t0 = engine.state.t
    rows = []
    next_sample = 0.0
    elapsed = 0.0

    while elapsed <= duration:
        while pending and pending[0]["t"] <= elapsed:
            spec_cmd = dict(pending.pop(0))
            spec_cmd.pop("t", None)
            command = telemetry.parse_command({"type": "cmd", **spec_cmd})
            telemetry.apply_command(engine, command)

        snap = engine.advance(dt)
        elapsed = snap.t - t0
        if elapsed >= next_sample:
            next_sample += sample
            rows.append(_row(snap, spec, elapsed))

    if out:
        with open(out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        if not quiet:
            print(f"wrote {out} ({len(rows)} samples)")
    elif not quiet:
        w = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    if not quiet:
        worst = max(rows, key=lambda r: r["worst_t_in_c"])
        verdicts = {r["verdict"] for r in rows}
        print(
            f"\n{scenario.get('name', script.stem)}: verdicts seen {sorted(verdicts)}; "
            f"worst rack intake {worst['worst_t_in_c']:.2f} C on {worst['worst_rack']} "
            f"at t={worst['t_sim']:.0f}s",
            file=sys.stderr,
        )
    return 0


def _row(snap, spec: HallSpec, elapsed: float) -> dict:
    frame = telemetry.encode_state(snap, spec)
    t = frame["totals"]
    return {
        "t_sim": round(elapsed, 2),
        "mode": frame["mode"],
        "phase": (frame.get("profile") or {}).get("phase", ""),
        "verdict": frame["verdict"],
        "it_kw": t["it_kw"],
        "cooling_kw": t["cooling_kw"],
        "storage_kw": t["storage_kw"],
        "balance_err": t["balance_err"],
        "supply_c": round(
            sum(u["t_supply"] for u in frame["supply"].values())
            / len(frame["supply"]),
            3,
        ),
        "hot_aisle_c": frame["hot_aisle"],
        "return_c": frame["return_air"],
        "worst_rack": t["worst_rack"],
        "worst_t_in_c": t["worst_t_in"],
        "worst_t_in_peak_c": t["worst_t_in_peak"],
        "recirc_m3h": t["recirc_m3h"],
        "modules_on": "".join(
            m.name if frame["supply"][m.name]["on"] else "-" for m in spec.modules
        ),
    }
