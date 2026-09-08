#!/usr/bin/env python3
"""
Per-cabinet results along the row: the headline chart for a 3D run.

Intake temperature (mean and peak) and airflow for every cabinet, against
position along the row, with the ASHRAE limits drawn on. This is what shows
end-of-row penalties, fan-failure shadows and load-imbalance effects - none of
which a single aggregate number or a centreline slice can reveal.

Usage:
    ./plot_row.py [CASE_DIR]

Writes <CASE_DIR>/row.png and prints the worst cabinet.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

KELVIN = 273.15
RECOMMENDED_MAX_C = 27.0
ALLOWABLE_MAX_C = 32.0


def final(case: Path, fo: str) -> float | None:
    files = sorted((case / "postProcessing" / fo).glob("*/*.dat"))
    if not files:
        return None
    rows = [l for l in files[-1].read_text().splitlines() if not l.startswith("#") and l.strip()]
    return float(rows[-1].split()[1]) if rows else None


def loads(case: Path, n: int) -> list[float]:
    """Per-cabinet kW, matching make_row_dicts.py."""
    default = 30.0
    for line in (case / "system" / "simulationParameters").read_text().splitlines():
        p = line.split()
        if len(p) >= 2 and p[0] == "heatLoad":
            default = float(p[1].rstrip(";")) / 1000.0
    out = [default] * n
    f = case / "row_loads.csv"
    if f.is_file():
        with f.open() as fh:
            for row in csv.DictReader(fh):
                try:
                    i, kw = int(row["index"]), float(row["kW"])
                except (KeyError, ValueError, TypeError):
                    continue
                if 0 <= i < n:
                    out[i] = kw
    return out


def main() -> int:
    case = Path(sys.argv[1] if len(sys.argv) > 1 else "case")

    idx, mean, peak, flow = [], [], [], []
    i = 0
    while True:
        t = final(case, f"cab{i:02d}_inletT")
        if t is None:
            break
        idx.append(i)
        mean.append(t - KELVIN)
        peak.append((final(case, f"cab{i:02d}_inletTmax") or t) - KELVIN)
        flow.append(abs(final(case, f"cab{i:02d}_flow") or 0.0))
        i += 1

    if not idx:
        raise SystemExit(
            f"no per-cabinet metrics in {case}/postProcessing.\n"
            "Run ./make_row_dicts.py and re-run the case.")

    kw = loads(case, len(idx))
    worst = max(idx, key=lambda j: peak[j])

    print()
    print(f"{'cab':>4}{'kW':>7}{'intake mean':>13}{'intake peak':>13}{'flow kg/s':>11}  verdict")
    print("-" * 62)
    for j in idx:
        v = ("PASS" if mean[j] <= RECOMMENDED_MAX_C and peak[j] <= ALLOWABLE_MAX_C
             else "MARGINAL" if mean[j] <= RECOMMENDED_MAX_C else "FAIL")
        print(f"{j:>4}{kw[j]:>7.0f}{mean[j]:>12.2f}C{peak[j]:>12.2f}C{flow[j]:>11.3f}  {v}")
    print("-" * 62)
    print(f"worst cabinet: {worst}  (peak intake {peak[worst]:.2f} degC)")
    spread = max(mean) - min(mean)
    print(f"spread across the row: {spread:.2f} K on the mean, "
          f"{max(peak)-min(peak):.2f} K on the peak")
    print()

    fig, axes = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True,
                             gridspec_kw=dict(height_ratios=[2, 1]))

    ax = axes[0]
    ax.axhspan(0, RECOMMENDED_MAX_C, color="tab:green", alpha=0.07)
    ax.plot(idx, mean, "o-", lw=2, ms=8, label="intake (mean)")
    ax.plot(idx, peak, "s--", lw=1.4, ms=6, color="tab:red", label="intake (peak)")
    ax.axhline(RECOMMENDED_MAX_C, color="darkorange", ls=":",
               label=f"ASHRAE recommended {RECOMMENDED_MAX_C:.0f} degC")
    ax.axhline(ALLOWABLE_MAX_C, color="crimson", ls=":",
               label=f"ASHRAE allowable {ALLOWABLE_MAX_C:.0f} degC")
    ax.annotate(f"worst: cabinet {worst}", (worst, peak[worst]),
                textcoords="offset points", xytext=(0, 14), ha="center",
                fontsize=9, fontweight="bold", color="crimson")
    ax.set_ylabel("server intake temperature [degC]")
    ax.set_title(f"Per-cabinet intake along the row - {case}")
    ax.legend(fontsize=8, loc="best")
    ax.grid(alpha=0.3)
    lo = min(18.0, min(mean) - 1)
    ax.set_ylim(lo, max(ALLOWABLE_MAX_C + 3, max(peak) + 3))

    ax = axes[1]
    ax.bar([j - 0.2 for j in idx], kw, width=0.4, label="load [kW]", color="0.55")
    ax.set_ylabel("load [kW]", color="0.35")
    ax.tick_params(axis="y", labelcolor="0.35")
    ax2 = ax.twinx()
    ax2.bar([j + 0.2 for j in idx], flow, width=0.4, color="tab:blue",
            label="airflow [kg/s]")
    ax2.set_ylabel("airflow [kg/s]", color="tab:blue")
    ax2.tick_params(axis="y", labelcolor="tab:blue")
    ax.set_xlabel("cabinet index along the row")
    ax.set_xticks(idx)
    ax.grid(alpha=0.3, axis="y")

    fig.tight_layout()
    out = case / "row.png"
    fig.savefig(out, dpi=140)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
