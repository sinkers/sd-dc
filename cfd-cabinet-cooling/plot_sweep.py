#!/usr/bin/env python3
"""
Plot the optimisation curve from a sweep: server intake temperature and
containment gap flow against whatever parameter was swept.

Usage:
    ./plot_sweep.py [runs/results.csv]

Writes runs/sweep.png
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RECOMMENDED_MAX_C = 27.0
ALLOWABLE_MAX_C = 32.0

LABELS = {
    "fanWallVelocity": "fan wall face velocity [m/s]",
    "supplyTemp": "supply air temperature [K]",
    "containmentTopZ": "containment top height [m]",
    "heatLoad": "IT load [W]",
}


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/results.csv")
    if not path.is_file():
        raise SystemExit(f"{path} not found - run ./sweep.sh first")

    groups: dict[str, list[dict]] = defaultdict(list)
    with path.open() as fh:
        for row in csv.DictReader(fh):
            if row.get("verdict") in (None, "", "ERROR"):
                continue
            groups[row["param"]].append(row)

    if not groups:
        raise SystemExit(f"no usable rows in {path}")

    fig, axes = plt.subplots(len(groups), 2, figsize=(12, 4.4 * len(groups)),
                             squeeze=False)

    for r, (param, rows) in enumerate(sorted(groups.items())):
        rows.sort(key=lambda d: float(d["value"]))
        xs = [float(d["value"]) for d in rows]
        Ti = [float(d["inletT_C"]) for d in rows]
        Tix = [float(d["inletTmax_C"]) for d in rows]
        gap = [float(d["gap_kgs"]) for d in rows]

        ax = axes[r][0]
        ax.plot(xs, Ti, "o-", lw=2, ms=7, label="intake (mean)")
        ax.plot(xs, Tix, "s--", lw=1.2, ms=5, label="intake (max)")
        ax.axhline(RECOMMENDED_MAX_C, color="darkorange", ls=":",
                   label=f"recommended {RECOMMENDED_MAX_C:.0f} degC")
        ax.axhline(ALLOWABLE_MAX_C, color="crimson", ls=":",
                   label=f"allowable {ALLOWABLE_MAX_C:.0f} degC")
        ax.axhspan(0, RECOMMENDED_MAX_C, color="tab:green", alpha=0.07)
        for x, t, d in zip(xs, Ti, rows):
            ax.annotate(d["verdict"], (x, t), textcoords="offset points",
                        xytext=(0, 10), ha="center", fontsize=8,
                        color="tab:green" if d["verdict"] == "PASS" else "crimson",
                        fontweight="bold")
        ax.set_xlabel(LABELS.get(param, param))
        ax.set_ylabel("server intake temp [degC]")
        ax.set_title(f"Cooling sufficiency vs {param}")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

        ax = axes[r][1]
        colors = ["tab:blue" if g >= 0 else "tab:red" for g in gap]
        ax.bar([str(x) for x in xs], gap, color=colors, alpha=0.8)
        ax.axhline(0, color="k", lw=1)
        ax.set_xlabel(LABELS.get(param, param))
        ax.set_ylabel("containment gap flow [kg/s]")
        ax.set_title("blue = cold bypass   |   red = hot recirculation")
        ax.grid(alpha=0.3, axis="y")

    fig.tight_layout()
    out = path.parent / "sweep.png"
    fig.savefig(out, dpi=140)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
