#!/usr/bin/env python3
"""
Results for the two-row hall: per-rack intake temperature for both rows, and a
plan view of the cold aisles at rack mid-height.

    ./plot_hall.py [CASE_DIR]        # default case-hall

Writes <CASE_DIR>/hall_racks.png and <CASE_DIR>/hall_plan.png, and prints the
verdict against the ASHRAE A1 envelope.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.tri import Triangulation  # noqa: E402

KELVIN = 273.15
RECOMMENDED_C, ALLOWABLE_C = 27.0, 32.0   # overridden per case below
CP = 1005.0


def params(case: Path) -> dict:
    p = {}
    for line in (case / "system" / "hallParameters").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.replace("=", " ").split()
        if len(parts) >= 2:
            try:
                p[parts[0]] = float(parts[1])
            except ValueError:
                p[parts[0]] = parts[1]          # string parameter
    n = int(p["nRacksPerRow"])
    c = p["cellSize"]
    g = p.get("rearGap", 0.0) if str(p.get("intakeSide", "top")) == "rear" else 0.0
    nu = int(p.get("nUnitsPerEnd", 1))
    bank = nu * p["unitWidth"] + (nu - 1) * p.get("unitGap", 0.0)
    p["rearGap_eff"] = g
    p["podX0"] = g + p["unitDepth"] + p["clearance"]
    p["podX1"] = p["podX0"] + n * p["rackPitch"]
    p["Lx"] = p["podX1"] + p["clearance"] + p["unitDepth"] + g
    p["rowAy0"] = round(p["sideAisle"] / c) * c
    p["rowAy1"] = p["rowAy0"] + p["rackDepth"]
    p["hotY0"] = p["rowAy1"];     p["hotY1"] = p["hotY0"] + p["hotAisleWidth"]
    p["rowBy0"] = p["hotY1"];     p["rowBy1"] = p["rowBy0"] + p["rackDepth"]
    p["uy0"] = round(((p["hallWidth"] - bank) / 2) / c) * c
    p["uy1"] = p["uy0"] + bank
    return p


def unit_names(case: Path) -> list:
    """Per-module tags (A1, ..., B1, ...) present in postProcessing."""
    d = case / "postProcessing"
    tags = sorted(q.name[len("supply"):] for q in d.glob("supply*") if q.is_dir())
    return tags or ["A", "B"]           # pre-module-split runs


def final(case: Path, fo: str):
    d = case / "postProcessing" / fo
    files = sorted(d.glob("*/*.dat")) if d.is_dir() else []
    if not files:
        return None
    rows = [l for l in files[-1].read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    return float(rows[-1].split()[1]) if rows else None


def main() -> int:
    case = Path(sys.argv[1] if len(sys.argv) > 1 else "case-hall")
    p = params(case)
    n = int(p["nRacksPerRow"])
    global RECOMMENDED_C, ALLOWABLE_C
    ALLOWABLE_C = p.get("allowableMax_C", ALLOWABLE_C)
    RECOMMENDED_C = p.get("recommendedMax_C", RECOMMENDED_C)
    cls = {32.0: "A1", 35.0: "A2", 40.0: "A3", 45.0: "A4"}.get(ALLOWABLE_C, "custom")
    print(f"\n  thermal envelope: ASHRAE {cls}"
          f"  (allowable {ALLOWABLE_C:g} C, recommended {RECOMMENDED_C:g} C)")

    data = {}
    for row in ("A", "B"):
        mean, peak, flow = [], [], []
        for i in range(n):
            t = f"{row}{i:02d}"
            v = final(case, f"r{t}_inletT")
            if v is None:
                raise SystemExit(f"no metrics for rack {t} - has the case run?")
            mean.append(v - KELVIN)
            peak.append((final(case, f"r{t}_inletTmax") or v) - KELVIN)
            flow.append(abs(final(case, f"r{t}_flow") or 0.0))
        data[row] = dict(mean=mean, peak=peak, flow=flow)

    allm = data["A"]["mean"] + data["B"]["mean"]
    allp = data["A"]["peak"] + data["B"]["peak"]
    allf = data["A"]["flow"] + data["B"]["flow"]
    units = unit_names(case)
    sup = sum(abs(final(case, f"supply{u}") or 0) for u in units)
    retT = [final(case, f"returnT{u}") for u in units]
    retT = [v - KELVIN for v in retT if v is not None]

    load = 2 * n * p["rackLoad_kW"]
    offs = str(p.get("unitsOff", "")).replace(",", " ").split()
    nOn = max(len(units) - len(offs), 1)
    cap = nOn * p["unitCapacity_kW"] if len(units) > 2 else 2 * p["unitCapacity_kW"]

    print()
    print("=" * 68)
    print(f"  HALL COOLING RESULT   ({case})")
    print("=" * 68)
    print(f"  IT load                      {load:8.0f} kW"
          f"   ({2*n} racks x {p['rackLoad_kW']:g} kW)")
    print(f"  fan wall capacity            {cap:8.0f} kW   ({100*load/cap:.0f} % utilised)")
    print(f"  supply air                   {p['supplyTemp_C']:8.1f} degC")
    print()
    print(f"  rack intake, coldest rack    {min(allm):8.2f} degC")
    print(f"  rack intake, mean of racks   {np.mean(allm):8.2f} degC")
    print(f"  rack intake, hottest rack    {max(allm):8.2f} degC   "
          f"limit {ALLOWABLE_C:.0f} (allowable)")
    print(f"  worst peak on any rack face  {max(allp):8.2f} degC")
    print(f"  spread across the hall       {max(allm)-min(allm):8.2f} K")
    print()
    print(f"  total supply                 {sup:8.2f} kg/s")
    print(f"  total through racks          {sum(allf):8.2f} kg/s"
          f"   ({100*sum(allf)/sup:.0f} % of supply)")
    print(f"  airflow spread rack to rack  {100*(max(allf)-min(allf))/np.mean(allf):8.1f} %")
    if retT:
        print(f"  return air to the units       {np.mean(retT):8.2f} degC"
              f"   (rated RAT 37)")
    print()
    hot, hotpk = max(allm), max(allp)
    worst = int(np.argmax(allm)); worst_row = "A" if worst < n else "B"
    worst_pk = int(np.argmax(allp)); wpk_row = "A" if worst_pk < n else "B"
    print("-" * 68)
    if hot > ALLOWABLE_C:
        print(f"  FAIL - rack {worst_row}{worst % n:02d} mean intake is {hot:.2f} degC, above "
              f"the {ALLOWABLE_C:.0f} degC allowable limit.")
    elif hotpk > ALLOWABLE_C:
        # Same trap as every earlier model: the mean passes, a face does not.
        print(f"  MARGINAL - every rack passes on MEAN intake (worst {hot:.2f} degC,"
              f" {ALLOWABLE_C - hot:.2f} K headroom),")
        print(f"             but rack {wpk_row}{worst_pk % n:02d} has a face peak of "
              f"{hotpk:.2f} degC, above the {ALLOWABLE_C:.0f} degC")
        print(f"             allowable limit. A local hot spot, not a hall-wide failure.")
    elif hot <= RECOMMENDED_C:
        print(f"  PASS - every rack is inside the ASHRAE {cls} RECOMMENDED range.")
    else:
        print(f"  PASS - every rack is within the ASHRAE {cls} allowable range on both")
        print(f"         mean and peak. Headroom to allowable: "
              f"{ALLOWABLE_C - hotpk:.2f} K on the worst face.")
    if p["supplyTemp_C"] > RECOMMENDED_C:
        print(f"         Note: the {p['supplyTemp_C']:.0f} degC supply is itself above the "
              f"{RECOMMENDED_C:.0f} degC recommended")
        print(f"         limit, so this design uses the allowable envelope by choice.")
    print("=" * 68)
    print()
    print(f"  {'rack':>6}{'mean C':>9}{'peak C':>9}{'flow kg/s':>11}   "
          f"{'rack':>6}{'mean C':>9}{'peak C':>9}{'flow kg/s':>11}")
    for i in range(n):
        a, b = data["A"], data["B"]
        print(f"  {'A'+format(i,'02d'):>6}{a['mean'][i]:>9.2f}{a['peak'][i]:>9.2f}"
              f"{a['flow'][i]:>11.3f}   "
              f"{'B'+format(i,'02d'):>6}{b['mean'][i]:>9.2f}{b['peak'][i]:>9.2f}"
              f"{b['flow'][i]:>11.3f}")
    dT = load * 1000.0 / (sum(allf) * CP)
    print()
    print(f"  achieved rack dT {dT:.2f} K (nameplate {p['serverDeltaT_K']:g} K) -> "
          f"exhaust {p['supplyTemp_C'] + dT:.1f} degC")
    print()

    # ---------------- per-rack chart ----------------
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                             gridspec_kw=dict(height_ratios=[2, 1]))
    idx = list(range(n))
    ax = axes[0]
    ax.axhspan(0, RECOMMENDED_C, color="tab:green", alpha=0.07)
    ax.axhspan(RECOMMENDED_C, ALLOWABLE_C, color="tab:orange", alpha=0.07)
    for row, col in (("A", "tab:blue"), ("B", "tab:purple")):
        ax.plot(idx, data[row]["mean"], "o-", color=col, lw=2, ms=6,
                label=f"row {row} intake (mean)")
        ax.plot(idx, data[row]["peak"], "s--", color=col, lw=1, ms=4, alpha=0.6,
                label=f"row {row} intake (peak)")
    ax.axhline(RECOMMENDED_C, color="darkorange", ls=":",
               label=f"ASHRAE recommended {RECOMMENDED_C:.0f}")
    ax.axhline(ALLOWABLE_C, color="crimson", ls=":",
               label=f"ASHRAE allowable {ALLOWABLE_C:.0f}")
    ax.axhline(p["supplyTemp_C"], color="0.4", ls="-", lw=1,
               label=f"supply {p['supplyTemp_C']:.0f}")
    ax.set_ylabel("rack intake temperature [degC]")
    ax.set_title(f"Per-rack intake along the hall - {case}\n"
                 f"{2*n} x {p['rackLoad_kW']:g} kW = {load:g} kW against "
                 f"{cap:g} kW of fan wall")
    ax.legend(fontsize=8, ncol=2, loc="best")
    ax.grid(alpha=0.3)
    ax.set_ylim(min(p["supplyTemp_C"] - 2, min(allm) - 1), max(ALLOWABLE_C + 2, max(allp) + 2))

    ax = axes[1]
    w = 0.4
    ax.bar([i - w/2 for i in idx], data["A"]["flow"], width=w, label="row A", color="tab:blue")
    ax.bar([i + w/2 for i in idx], data["B"]["flow"], width=w, label="row B", color="tab:purple")
    ax.set_ylabel("rack airflow [kg/s]")
    ax.set_xlabel("rack index along the row  (fan wall A at 0, fan wall B beyond 11)")
    ax.set_xticks(idx)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    out1 = case / "hall_racks.png"
    fig.savefig(out1, dpi=140)
    print(f"wrote {out1}")

    # ---------------- plan view ----------------
    sdir = case / "postProcessing" / "slices"
    if sdir.is_dir():
        times = sorted(sdir.iterdir(), key=lambda q: float(q.name))
        f = times[-1] / "T_coldAisleA.raw"
        if f.is_file():
            rows = [[float(v) for v in l.split()]
                    for l in f.read_text().splitlines()
                    if l.strip() and not l.startswith("#")]
            a = np.asarray(rows)
            x, y, T = a[:, 0], a[:, 1], a[:, 3] - KELVIN
            fig, ax = plt.subplots(figsize=(14, 6.4))
            lo, hi = p["supplyTemp_C"] - 2, ALLOWABLE_C + 8
            cf = ax.tricontourf(Triangulation(x, y), np.clip(T, lo, hi),
                                levels=np.linspace(lo, hi, 40), cmap="turbo", extend="both")
            cb = fig.colorbar(cf, ax=ax, pad=0.012, fraction=0.03)
            cb.set_label("air temperature [degC]")
            ax.tricontour(Triangulation(x, y), T, levels=[ALLOWABLE_C],
                          colors="white", linewidths=1.6, linestyles="--")
            for y0, y1, lbl in ((p["rowAy0"], p["rowAy1"], "ROW A"),
                                (p["rowBy0"], p["rowBy1"], "ROW B")):
                ax.add_patch(Rectangle((p["podX0"], y0), p["podX1"] - p["podX0"], y1 - y0,
                                       facecolor="0.18", edgecolor="k", zorder=5))
                ax.text((p["podX0"] + p["podX1"]) / 2, (y0 + y1) / 2, lbl, color="w",
                        ha="center", va="center", fontweight="bold", zorder=6)
            g = p["rearGap_eff"]
            for x0, x1, lbl in ((g, g + p["unitDepth"], "FW-A"),
                                (p["Lx"] - g - p["unitDepth"], p["Lx"] - g, "FW-B")):
                ax.add_patch(Rectangle((x0, p["uy0"]), x1 - x0, p["uy1"] - p["uy0"],
                                       facecolor="#3c4650", edgecolor="k", zorder=5))
                ax.text((x0 + x1) / 2, (p["uy0"] + p["uy1"]) / 2, lbl, color="w",
                        rotation=90, ha="center", va="center", fontweight="bold", zorder=6)
            ax.set_xlim(0, p["Lx"]); ax.set_ylim(0, p["hallWidth"])
            ax.set_aspect("equal"); ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
            ax.set_title(f"Plan view at rack mid-height ({p['rackHeight']/2:.2f} m) - {case}"
                         f"   (white dashed = {ALLOWABLE_C:.0f} degC allowable limit)")
            fig.tight_layout()
            out2 = case / "hall_plan.png"
            fig.savefig(out2, dpi=140)
            print(f"wrote {out2}")
    return 0 if max(allm) <= ALLOWABLE_C else 1


if __name__ == "__main__":
    sys.exit(main())
