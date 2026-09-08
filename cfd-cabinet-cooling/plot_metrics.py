#!/usr/bin/env python3
"""
Read the OpenFOAM function-object output for a cabinet cooling run, decide
whether the setup cools the cabinet, and plot the convergence history.

Usage:
    ./plot_metrics.py [CASE_DIR]        # default: ./case

Writes  <CASE_DIR>/metrics.png  and prints a verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# ASHRAE TC9.9 class A1 thresholds for air entering the servers.
RECOMMENDED_MAX_C = 27.0
ALLOWABLE_MAX_C = 32.0

CP_AIR = 1005.0  # J/(kg K)
KELVIN = 273.15


def read_dat(case: Path, name: str) -> tuple[list[float], list[float]]:
    """Read the newest postProcessing .dat file for a function object."""
    root = case / "postProcessing" / name
    files = sorted(root.glob("*/*.dat")) if root.is_dir() else []
    if not files:
        raise SystemExit(f"no output found for '{name}' under {root}")

    times: list[float] = []
    values: list[float] = []
    # Later time directories (restarts) override earlier ones.
    for path in files:
        for line in path.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            t = float(parts[0])
            while times and times[-1] >= t:
                times.pop()
                values.pop()
            times.append(t)
            values.append(float(parts[1]))
    return times, values


def main() -> int:
    case = Path(sys.argv[1] if len(sys.argv) > 1 else "case")
    if not (case / "postProcessing").is_dir():
        raise SystemExit(f"{case}/postProcessing not found - has the case been run?")

    t_in, T_in = read_dat(case, "cabinetInletT")
    _, T_in_max = read_dat(case, "cabinetInletTmax")
    _, T_out = read_dat(case, "cabinetOutletT")
    _, m_cab = read_dat(case, "cabinetFlow")
    _, m_fan = read_dat(case, "fanWallFlow")

    # The containment gap zone is empty when the containment is sealed all the
    # way to the plenum floor, in which case there is no gap flow to report.
    try:
        _, m_gap = read_dat(case, "containmentGapFlow")
    except SystemExit:
        m_gap = [0.0] * len(t_in)

    try:
        _, T_ret = read_dat(case, "intakeT")
    except SystemExit:
        T_ret = None

    # Convert to degrees C; mass flows to magnitudes with a sign convention.
    T_in_c = [v - KELVIN for v in T_in]
    T_in_max_c = [v - KELVIN for v in T_in_max]
    T_out_c = [v - KELVIN for v in T_out]
    supply = [abs(v) for v in m_fan]  # fan wall inflow
    through = [abs(v) for v in m_cab]  # through the servers

    # Final converged values.
    Ti, Timax, To = T_in_c[-1], T_in_max_c[-1], T_out_c[-1]
    m_srv, m_sup, m_leak = through[-1], supply[-1], m_gap[-1]
    dT = To - Ti
    q_removed = m_srv * CP_AIR * dT / 1000.0  # kW
    ratio = m_sup / m_srv if m_srv else float("nan")

    # ---------------------------------------------------------------- verdict
    passed = Ti <= RECOMMENDED_MAX_C
    hotspot_ok = Timax <= ALLOWABLE_MAX_C

    print()
    print("=" * 68)
    print(f"  CABINET COOLING RESULT   ({case})")
    print("=" * 68)
    print(f"  iterations run                 {int(t_in[-1])}")
    print()
    print(f"  server intake temp  (mean)     {Ti:7.2f} degC   "
          f"limit {RECOMMENDED_MAX_C:.0f} degC")
    print(f"  server intake temp  (max)      {Timax:7.2f} degC   "
          f"limit {ALLOWABLE_MAX_C:.0f} degC")
    print(f"  server exhaust temp (mean)     {To:7.2f} degC")
    print(f"  rise across the cabinet        {dT:7.2f} K")
    if T_ret is not None:
        print(f"  air returning to the unit      {T_ret[-1] - KELVIN:7.2f} degC")
    print()
    print(f"  fan wall supply                {m_sup:7.3f} kg/s")
    print(f"  airflow through the servers    {m_srv:7.3f} kg/s")
    print(f"  supply / demand                {ratio:7.2f}")
    print(f"  heat removed by that airflow   {q_removed:7.1f} kW")
    print()
    if m_leak >= 0:
        print(f"  containment gap        {m_leak:+7.3f} kg/s  "
              f"cold air BYPASSING to the hot aisle")
    else:
        print(f"  containment gap        {m_leak:+7.3f} kg/s  "
              f"hot air RECIRCULATING to the cold aisle")
    print()
    print("-" * 68)
    if passed and hotspot_ok:
        print("  PASS - intake air is within the ASHRAE A1 recommended range.")
    elif passed:
        print("  PASS (marginal) - mean intake is fine but the worst-case")
        print(f"         intake of {Timax:.1f} degC exceeds the {ALLOWABLE_MAX_C:.0f} degC allowable limit.")
    else:
        print(f"  FAIL - mean intake air is {Ti:.1f} degC, above the "
              f"{RECOMMENDED_MAX_C:.0f} degC limit.")
        if m_leak < 0:
            print("         Cause: the fan wall is under-supplying, so the servers")
            print("         pull hot air back over the containment. Raise")
            print("         fanWallVelocity in case/system/simulationParameters.")
    print("=" * 68)
    print()

    # ------------------------------------------------------------------ plots
    fig, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=True)

    ax = axes[0]
    ax.plot(t_in, T_in_c, label="intake (mean)", lw=2)
    ax.plot(t_in, T_in_max_c, label="intake (max)", lw=1, ls="--")
    ax.plot(t_in, T_out_c, label="exhaust (mean)", lw=1.5, color="tab:red")
    ax.axhline(RECOMMENDED_MAX_C, color="darkorange", ls=":",
               label=f"ASHRAE recommended {RECOMMENDED_MAX_C:.0f} degC")
    ax.axhline(ALLOWABLE_MAX_C, color="crimson", ls=":",
               label=f"ASHRAE allowable {ALLOWABLE_MAX_C:.0f} degC")
    ax.set_ylabel("temperature [degC]")
    ax.set_title(f"Cabinet cooling convergence - {case}")
    ax.legend(fontsize=8, loc="best")
    ax.grid(alpha=0.3)

    ax = axes[1]
    ax.plot(t_in, supply, label="fan wall supply", lw=2)
    ax.plot(t_in, through, label="through servers", lw=2)
    ax.set_ylabel("mass flow [kg/s]")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[2]
    ax.plot(t_in, m_gap, lw=2, color="tab:purple")
    ax.axhline(0, color="k", lw=0.8)
    ax.fill_between(t_in, m_gap, 0, where=[v >= 0 for v in m_gap],
                    alpha=0.25, color="tab:blue", label="bypass (cold -> hot)")
    ax.fill_between(t_in, m_gap, 0, where=[v < 0 for v in m_gap],
                    alpha=0.25, color="tab:red", label="recirculation (hot -> cold)")
    ax.set_ylabel("containment gap [kg/s]")
    ax.set_xlabel("SIMPLE iteration")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    out = case / "metrics.png"
    fig.savefig(out, dpi=130)
    print(f"wrote {out}")

    return 0 if (passed and hotspot_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
