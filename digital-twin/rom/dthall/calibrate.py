"""Fit the ROM's coefficients to the CFD, and score it against them.

## What is fitted, and what is not

The calibration reference is `case-hall` at its v4 configuration (50 mm cells,
8.35 m hall) — the one hall run with per-rack results on disk, and the one whose
`system/hallParameters` still describes the case that produced them. Six
coefficients are identifiable from it:

    module_flow_multiplier   <- total supply mass flow
    fan_flow_multiplier      <- total flow through the racks
    recirc_baseline[end]     <- the end-of-row intake temperatures
    recirc_baseline[next]        "
    recirc_baseline[mid]         "
    peak_multiplier          <- the inletTmax channels

Three groups are deliberately *not* fitted:

  * `supply_reach` and `zone_coupling` are unidentifiable from this point. It is
    symmetric (all four modules running, uniform load) and comfortably
    oversupplied, so no zone is starved and nothing in the data responds to how
    supply is distributed or migrates. They keep their priors. Identifying them
    needs an asymmetric run — `unitsOff A1` — which is a boundary-condition-only
    change to the CFD: same mesh, restart from the converged field. That is the
    single highest-value CFD run to add next.
  * `unitAirflow_m3h` turndown would identify the recirculation *gain* (how a
    deficit converts to recirculation) as opposed to its baseline. Also BC-only.
  * Thermal masses, the coil time constant and the return mixing factor are
    transient parameters, and steady CFD carries no information about them at
    all. They are physical estimates.

The earlier hall variants (v1 baseline, v2 bulkhead sealed, v3 1500 hot aisle)
are *geometry* variants whose parameters are no longer recoverable from the
repo — only their printed summaries survive, and `hallParameters` has since
moved on to v4. They are not used as references, because reconstructing their
specs would mean guessing at the geometry that produced them.

So: the quantitative fit rests on one operating point, and the model's response
to *changes* rests on physics plus priors. `docs/ROM.md` records this, and the
validation gate below only claims what one reference point can support.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from . import cfddata, topology
from .cfddata import CfdReference
from .model import HallModel, Inputs, Observables
from .params import RomParams
from .topology import HallSpec

# --- validation gate ------------------------------------------------------
# Tolerances are set by what the reference data can actually support. The CFD's
# own face peaks swing +/-0.85..1.4 K over the averaging window, so demanding
# better than ~2.5 K agreement on peaks would be fitting noise.
GATE = {
    "mean_within_1k_min_racks": 22,  # of 24
    "mean_abs_max_k": 1.5,
    "peak_abs_max_k": 2.5,
    "supply_flow_rel": 0.02,
    "rack_flow_rel": 0.03,
    "return_temp_k": 1.0,
    "energy_closure_rel": 1e-3,
}

FREE_PARAMETERS = (
    "module_flow_multiplier",
    "fan_flow_multiplier",
    "recirc_end",
    "recirc_next",
    "recirc_mid",
    "peak_multiplier",
)

BOUNDS = {
    "module_flow_multiplier": (0.8, 1.3),
    "fan_flow_multiplier": (0.8, 2.0),
    "recirc_end": (0.0, 0.6),
    "recirc_next": (0.0, 0.6),
    "recirc_mid": (0.0, 0.6),
    "peak_multiplier": (1.0, 20.0),
}


def to_vector(params: RomParams) -> np.ndarray:
    return np.array(
        [
            params.module_flow_multiplier,
            params.fan_flow_multiplier,
            params.recirc_baseline["end"],
            params.recirc_baseline["next"],
            params.recirc_baseline["mid"],
            params.peak_multiplier,
        ]
    )


def from_vector(params: RomParams, x: np.ndarray) -> RomParams:
    return replace(
        params,
        module_flow_multiplier=float(x[0]),
        fan_flow_multiplier=float(x[1]),
        recirc_baseline={
            "end": float(x[2]),
            "next": float(x[3]),
            "mid": float(x[4]),
        },
        peak_multiplier=float(x[5]),
    )


@dataclass
class Scorecard:
    reference: str
    rack_names: list[str]
    mean_cfd: np.ndarray
    mean_rom: np.ndarray
    peak_cfd: np.ndarray
    peak_rom: np.ndarray
    supply_cfd: float
    supply_rom: float
    rack_flow_cfd: float
    rack_flow_rom: float
    return_cfd: float  # enthalpy mean — the like-for-like comparison
    return_cfd_area: float  # area mean, as the CFD patch reports it
    return_rom: float
    energy_closure: float
    converged: bool

    @property
    def mean_err(self) -> np.ndarray:
        return self.mean_rom - self.mean_cfd

    @property
    def peak_err(self) -> np.ndarray:
        return self.peak_rom - self.peak_cfd

    @property
    def checks(self) -> dict[str, tuple[bool, str]]:
        me, pe = np.abs(self.mean_err), np.abs(self.peak_err)
        within = int((me <= 1.0).sum())
        return {
            "rack mean intake within 1.0 K": (
                within >= GATE["mean_within_1k_min_racks"],
                f"{within}/{len(me)} racks (need >= {GATE['mean_within_1k_min_racks']})",
            ),
            "rack mean intake worst error": (
                me.max() <= GATE["mean_abs_max_k"],
                f"{me.max():.2f} K (limit {GATE['mean_abs_max_k']})",
            ),
            "rack peak intake worst error": (
                pe.max() <= GATE["peak_abs_max_k"],
                f"{pe.max():.2f} K (limit {GATE['peak_abs_max_k']})",
            ),
            "total supply flow": (
                abs(self.supply_rom / self.supply_cfd - 1) <= GATE["supply_flow_rel"],
                f"{self.supply_rom:.2f} vs {self.supply_cfd:.2f} kg/s "
                f"({100 * (self.supply_rom / self.supply_cfd - 1):+.1f}%)",
            ),
            "total flow through racks": (
                abs(self.rack_flow_rom / self.rack_flow_cfd - 1)
                <= GATE["rack_flow_rel"],
                f"{self.rack_flow_rom:.2f} vs {self.rack_flow_cfd:.2f} kg/s "
                f"({100 * (self.rack_flow_rom / self.rack_flow_cfd - 1):+.1f}%)",
            ),
            "return air temp (enthalpy mean)": (
                abs(self.return_rom - self.return_cfd) <= GATE["return_temp_k"],
                f"{self.return_rom:.2f} vs {self.return_cfd:.2f} C "
                f"(CFD patch area-mean reads {self.return_cfd_area:.2f} C)",
            ),
            "energy closure": (
                self.energy_closure <= GATE["energy_closure_rel"],
                f"{self.energy_closure:.2%}",
            ),
            "reached steady state": (self.converged, str(self.converged)),
        }

    @property
    def passed(self) -> bool:
        return all(ok for ok, _ in self.checks.values())

    def report(self) -> str:
        lines = [
            "=" * 68,
            f"  ROM VALIDATION vs {self.reference}",
            "=" * 68,
            "",
            f"  {'rack':>6} {'CFD mean':>9} {'ROM mean':>9} {'err':>7}   "
            f"{'CFD peak':>9} {'ROM peak':>9} {'err':>7}",
        ]
        for i, n in enumerate(self.rack_names):
            lines.append(
                f"  {n:>6} {self.mean_cfd[i]:9.2f} {self.mean_rom[i]:9.2f} "
                f"{self.mean_err[i]:+7.2f}   {self.peak_cfd[i]:9.2f} "
                f"{self.peak_rom[i]:9.2f} {self.peak_err[i]:+7.2f}"
            )
        lines += ["", "-" * 68, "  GATE", "-" * 68]
        for name, (ok, detail) in self.checks.items():
            lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name:<32} {detail}")
        lines += [
            "-" * 68,
            f"  OVERALL: {'PASS' if self.passed else 'FAIL'}",
            "=" * 68,
        ]
        return "\n".join(lines)


def _solve(
    model: HallModel, inputs: Inputs, warm: dict
) -> tuple[Observables, object]:
    state, obs = model.steady_state(
        inputs, dt=1.0, tol=1e-5, max_time=4000.0, state=warm.get("state")
    )
    warm["state"] = state
    return obs, state


def residuals(
    x: np.ndarray,
    reference: CfdReference,
    spec: HallSpec,
    base: RomParams,
    warm: dict,
) -> np.ndarray:
    """Weighted residual vector. Weights are the uncertainty of each target:
    tight on flows and rack means, loose on peaks because the CFD's own peaks
    oscillate by more than a kelvin."""
    params = from_vector(base, x)
    model = HallModel(spec, params)
    obs, state = _solve(model, Inputs.design(spec), warm)
    from .constants import to_celsius

    mean_rom = to_celsius(obs.rack_inlet_k)
    peak_rom = to_celsius(obs.rack_inlet_peak_k)
    ret_rom = to_celsius(state.T_ret)

    return np.concatenate(
        [
            (mean_rom - reference.inlet_mean_c) / 0.3,
            (peak_rom - reference.inlet_peak_c) / 1.5,
            [(float(obs.module_flow.sum()) - reference.supply_flow_kgs) / 0.5],
            [(float(obs.rack_flow.sum()) - reference.total_rack_flow_kgs) / 0.5],
            [(ret_rom - reference.return_temp_enthalpy_c) / 0.5],
        ]
    )


def fit(
    reference: CfdReference | None = None,
    spec: HallSpec | None = None,
    base: RomParams | None = None,
    verbose: bool = True,
) -> tuple[RomParams, Scorecard]:
    """Least-squares fit of the identifiable coefficients, then score the result."""
    from scipy.optimize import least_squares

    reference = reference or cfddata.load_case_hall()
    spec = spec or topology.from_hall_parameters()
    base = base or RomParams()

    x0 = to_vector(base)
    lo = np.array([BOUNDS[k][0] for k in FREE_PARAMETERS])
    hi = np.array([BOUNDS[k][1] for k in FREE_PARAMETERS])
    warm: dict = {}

    result = least_squares(
        residuals,
        x0,
        bounds=(lo, hi),
        args=(reference, spec, base, warm),
        xtol=1e-8,
        ftol=1e-8,
        diff_step=1e-3,
        verbose=2 if verbose else 0,
    )
    fitted = from_vector(base, result.x)
    card = validate(reference=reference, spec=spec, params=fitted)
    return fitted, card


def validate(
    reference: CfdReference | None = None,
    spec: HallSpec | None = None,
    params: RomParams | None = None,
) -> Scorecard:
    reference = reference or cfddata.load_case_hall()
    spec = spec or topology.from_hall_parameters()
    params = params or RomParams.load()
    model = HallModel(spec, params)
    inputs = Inputs.design(spec)
    state, obs = model.steady_state(inputs, dt=1.0, tol=1e-5)
    from .constants import to_celsius

    return Scorecard(
        reference=reference.name,
        rack_names=reference.rack_names,
        mean_cfd=reference.inlet_mean_c,
        mean_rom=to_celsius(obs.rack_inlet_k),
        peak_cfd=reference.inlet_peak_c,
        peak_rom=to_celsius(obs.rack_inlet_peak_k),
        supply_cfd=reference.supply_flow_kgs,
        supply_rom=float(obs.module_flow.sum()),
        rack_flow_cfd=reference.total_rack_flow_kgs,
        rack_flow_rom=float(obs.rack_flow.sum()),
        return_cfd=reference.return_temp_enthalpy_c,
        return_cfd_area=reference.return_temp_area_c,
        return_rom=to_celsius(state.T_ret),
        energy_closure=abs(obs.cooling_kw - obs.it_load_kw) / max(obs.it_load_kw, 1e-9),
        converged=bool(obs.extras["converged"]),
    )


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Fit the ROM against the hall CFD")
    ap.add_argument("--out", type=Path, help="write fitted params here")
    args = ap.parse_args(argv)

    reference = cfddata.load_case_hall()
    print(reference.summary())
    print()
    fitted, card = fit(reference)
    print()
    print(card.report())
    if args.out:
        fitted.to_json(args.out)
        print(f"\nwrote {args.out}")
    return 0 if card.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# Gap-closure gain, from the single-cabinet fan wall sweep
# ---------------------------------------------------------------------------


def fit_gap_closure(path=None, verbose: bool = True) -> dict:
    """Fit `recirc_gain` against the fan wall airflow sweep in RESULTS.md.

    Why this matters for the fan-speed lever: turning the fan wall down is the one
    control whose effect runs entirely through `recirc_gain` — the coefficient that
    converts a zone-level supply deficit into rack-level recirculation. The
    case-hall reference cannot identify it (that run is symmetric and comfortably
    oversupplied, so there is no deficit for the gain to act on), and until now it
    sat at a prior of 1.0.

    The single-cabinet sweep IS this experiment: six converged points walking from
    68% to 127% of server demand, straight through the balance point where gap flow
    changes sign. Deriving the recirculated fraction from each point's measured
    intake temperature gives a direct (deficit, phi) dataset:

        phi = baseline + gain * deficit_fraction

    CAVEAT, and it is not a small one: this is single-cabinet geometry — one
    30 kW cabinet with symmetry planes and a defined 0.2 m containment gap, not
    the hall's open-top aisle. It constrains the *closure law's* gain, which is a
    ratio of flows and largely geometry-independent, but it is being applied to a
    different containment scheme. It is a great deal better than an unfitted prior
    and a great deal worse than a hall-scale airflow sweep, which is BC-only on
    case-hall and costs about a dollar.
    """
    import numpy as np

    from . import cfddata

    points, supply_c = cfddata.load_cabinet_sweep(path or cfddata.DEFAULT_RESULTS_MD)
    deficit = np.array([p.deficit_fraction for p in points])
    phi = np.array([p.recirc_fraction(supply_c) for p in points])

    # baseline from the oversupplied points, gain from the starved ones
    over = deficit <= 1e-9
    baseline = float(phi[over].mean()) if over.any() else 0.0
    starved = ~over
    if starved.sum() < 2:
        raise ValueError("need at least two starved points to fit a gain")

    # Fit gain and exponent together. A linear closure (exponent 1) misses the
    # saturation the sweep shows and is optimistic near the balance point.
    from scipy.optimize import least_squares

    def residual(x):
        return baseline + x[0] * deficit[starved] ** x[1] - phi[starved]

    fit = least_squares(residual, [1.0, 1.0], bounds=([0.05, 0.2], [5.0, 2.0]))
    gain, exponent = float(fit.x[0]), float(fit.x[1])

    predicted = baseline + gain * deficit**exponent
    residual = phi - predicted
    per_point_gain = (phi[starved] - baseline) / deficit[starved]

    result = {
        "recirc_gain": gain,
        "recirc_exponent": exponent,
        "baseline_when_oversupplied": baseline,
        "n_points": len(points),
        "rms_phi_error": float(np.sqrt((residual**2).mean())),
        "per_point_gain": per_point_gain.tolist(),
        "verdict_crossing_reproduced": bool(
            all(p.gap_kgs < 0 for p in points if p.verdict in ("FAIL", "MARGINAL"))
            and all(p.gap_kgs > 0 for p in points if p.verdict == "PASS")
        ),
    }

    if verbose:
        print("gap closure fitted against the single-cabinet fan wall sweep")
        print(f"  points                     {result['n_points']}")
        print(f"  baseline (oversupplied)    {baseline:.4f}")
        print(f"  recirc_gain                {gain:.3f}")
        print(f"  recirc_exponent            {exponent:.3f}   (1.0 would be linear)")
        print(f"  per-point gain             "
              f"{', '.join(f'{g:.2f}' for g in per_point_gain)}")
        print(f"  rms error in phi           {result['rms_phi_error']:.4f}")
        print(f"  verdict flips with gap sign {result['verdict_crossing_reproduced']}")
        print()
        print(f"  {'m/s':>5} {'%dem':>5} {'deficit':>8} {'phi CFD':>8} {'phi fit':>8} {'err':>7}")
        for i, p in enumerate(points):
            print(f"  {p.discharge_ms:5.2f} {p.percent_demand:5.0f} {deficit[i]:8.4f} "
                  f"{phi[i]:8.4f} {predicted[i]:8.4f} {residual[i]:+7.4f}")
        # The peak channel is a known weakness, so say so rather than bury it.
        peak = np.array([p.peak_recirc_fraction(supply_c) for p in points])
        print()
        print("  peak intake, for reference (NOT fitted here):")
        print(f"  {'m/s':>5} {'peak C':>8} {'exhaust':>8} {'phi_peak':>9}")
        for i, p in enumerate(points):
            print(f"  {p.discharge_ms:5.2f} {p.inlet_peak_c:8.1f} {p.exhaust_c:8.1f} "
                  f"{peak[i]:9.4f}")
        print("  Absolute peak barely moves (37.7 -> 36.6 C) while exhaust falls")
        print("  48.0 -> 38.4 C: the peak tracks the recirculating layer, not the")
        print("  deficit. The linear peak_multiplier model does not capture that")
        print("  saturation and overpredicts peaks in deep deficit. See docs/ROM.md.")
    return result
