"""Reader for the CFD results the ROM is calibrated against.

Reads OpenFOAM `postProcessing/<functionObject>/<time>/surfaceFieldValue.dat`
straight out of `cfd-cabinet-cooling/case-hall`, so calibration tracks the case
rather than a transcription of its printed summary.

One thing this module insists on: **windowed statistics, never last values.**
The hall CFD does not fully converge — p_rgh plateaus around 0.077 at the
4000-iteration cap (MODEL-REVIEW.md). Over the last 500 iterations the rack
means wander +/-0.05..0.3 K and the flows +/-0.05..0.27 kg/s, but the face
peaks swing +/-0.85..1.4 K. Fitting to a single final iteration would be
fitting to the phase of an oscillating plume. So means are averaged over the
window and peaks are taken as the window maximum, which is what a thermal
design engineer would read off the trace.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .constants import to_celsius

DEFAULT_CASE_HALL = (
    Path(__file__).resolve().parents[3] / "cfd-cabinet-cooling" / "case-hall"
)

# 25 rows at writeInterval 20 = the last 500 iterations.
WINDOW_ROWS = 25


def read_channel(case: str | Path, tag: str) -> np.ndarray:
    """(n, 2) array of [iteration, value] for one function object."""
    pattern = str(Path(case) / "postProcessing" / tag / "*" / "*.dat")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"no postProcessing data for {tag!r} under {case}")
    rows: list[tuple[float, float]] = []
    for fn in files:
        with open(fn) as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    rows.append((float(parts[0]), float(parts[1])))
    arr = np.array(rows)
    return arr[np.argsort(arr[:, 0])]


def windowed(
    case: str | Path, tag: str, rows: int = WINDOW_ROWS, op: str = "mean"
) -> float:
    """Windowed statistic over the last `rows` samples. `op` is "mean" or "max"."""
    values = read_channel(case, tag)[-rows:, 1]
    return float(values.mean() if op == "mean" else values.max())


@dataclass
class CfdReference:
    """One converged (or as-converged-as-it-gets) CFD operating point."""

    name: str
    case: Path
    rack_names: list[str]
    inlet_mean_c: np.ndarray
    inlet_peak_c: np.ndarray
    rack_flow_kgs: np.ndarray
    supply_flow_kgs: float
    return_flow_kgs: float
    return_temp_area_c: float
    supply_temp_c: float
    it_load_kw: float

    @property
    def total_rack_flow_kgs(self) -> float:
        return float(self.rack_flow_kgs.sum())

    @property
    def return_temp_enthalpy_c(self) -> float:
        """Mass-weighted (enthalpy) mean return temperature.

        The CFD's `returnT*` channels are `areaAverage(T)` over the intake patch,
        which is NOT the enthalpy mean when velocity varies across the patch —
        here the two differ by about 1 K (37.2 vs 38.1 C), which is exactly why
        the v4 summary and MODEL-REVIEW's energy-closure check quote different
        return temperatures for the same run.

        A lumped model's return node carries a well-mixed enthalpy temperature,
        so this is the quantity to compare it against. It is the value the CFD's
        own mass flow and imposed load require:  T_sup + Q / (m_dot * cp).
        """
        from .constants import CP

        return self.supply_temp_c + self.it_load_kw * 1000.0 / (
            self.supply_flow_kgs * CP
        )

    def summary(self) -> str:
        return (
            f"{self.name}: {self.it_load_kw:.0f} kW, supply {self.supply_flow_kgs:.2f} kg/s, "
            f"through racks {self.total_rack_flow_kgs:.2f} kg/s, intake mean "
            f"{self.inlet_mean_c.mean():.2f} C (min {self.inlet_mean_c.min():.2f}, "
            f"max {self.inlet_mean_c.max():.2f}), worst peak {self.inlet_peak_c.max():.2f} C, "
            f"return {self.return_temp_enthalpy_c:.2f} C enthalpy-mean / "
            f"{self.return_temp_area_c:.2f} C area-mean"
        )


def load_case_hall(
    case: str | Path = DEFAULT_CASE_HALL,
    rack_names: list[str] | None = None,
    it_load_kw: float | None = None,
) -> CfdReference:
    """Load the case-hall reference point.

    Note this run predates the fan-wall module split, so its supply/return
    channels are tagged per END (`supplyA`/`supplyB`) rather than per module.
    Supply flow is reported negative by OpenFOAM's inflow convention; the
    magnitude is what matters here.
    """
    case = Path(case)
    from .topology import from_hall_parameters

    spec = from_hall_parameters(case / "system" / "hallParameters")
    if rack_names is None:
        rack_names = spec.rack_names
    if it_load_kw is None:
        it_load_kw = spec.design_load_kw

    inlet_mean = np.array(
        [to_celsius(windowed(case, f"{n}_inletT")) for n in rack_names]
    )
    inlet_peak = np.array(
        [to_celsius(windowed(case, f"{n}_inletTmax", op="max")) for n in rack_names]
    )
    flows = np.array([windowed(case, f"{n}_flow") for n in rack_names])

    ends = _end_tags(case)
    supply = sum(abs(windowed(case, f"supply{e}")) for e in ends)
    ret = sum(abs(windowed(case, f"return{e}")) for e in ends)
    ret_t = float(
        np.mean([to_celsius(windowed(case, f"returnT{e}")) for e in ends])
    )

    return CfdReference(
        name=case.name,
        case=case,
        rack_names=list(rack_names),
        inlet_mean_c=inlet_mean,
        inlet_peak_c=inlet_peak,
        rack_flow_kgs=flows,
        supply_flow_kgs=supply,
        return_flow_kgs=ret,
        return_temp_area_c=ret_t,
        supply_temp_c=spec.supply_temp_c,
        it_load_kw=float(it_load_kw),
    )


def _end_tags(case: Path) -> list[str]:
    """Discover the supply channel tags actually present (A/B, or A1/A2/B1/B2)."""
    found = sorted(
        p.name[len("supply") :]
        for p in (case / "postProcessing").glob("supply*")
        if p.is_dir()
    )
    if not found:
        raise FileNotFoundError(f"no supply* channels under {case}/postProcessing")
    return found


# ---------------------------------------------------------------------------
# The single-cabinet fan wall sweep
# ---------------------------------------------------------------------------

DEFAULT_RESULTS_MD = (
    Path(__file__).resolve().parents[3] / "cfd-cabinet-cooling" / "RESULTS.md"
)


@dataclass
class SweepPoint:
    """One converged point of the fan wall airflow sweep."""

    discharge_ms: float
    percent_demand: float
    inlet_mean_c: float
    inlet_peak_c: float
    exhaust_c: float
    supply_kgs: float
    through_kgs: float
    gap_kgs: float  # negative = hot air recirculating into the cold aisle
    verdict: str

    @property
    def deficit_fraction(self) -> float:
        """Share of the servers' airflow the fan wall failed to supply."""
        return max(0.0, -self.gap_kgs) / self.through_kgs

    def recirc_fraction(self, supply_c: float) -> float:
        """Recirculated fraction implied by the measured intake temperature:
        T_in = (1-phi)*T_supply + phi*T_exhaust."""
        span = self.exhaust_c - supply_c
        if span <= 0:
            return 0.0
        return (self.inlet_mean_c - supply_c) / span

    def peak_recirc_fraction(self, supply_c: float) -> float:
        span = self.exhaust_c - supply_c
        if span <= 0:
            return 0.0
        return (self.inlet_peak_c - supply_c) / span


def load_cabinet_sweep(
    path: str | Path = DEFAULT_RESULTS_MD, supply_c: float = 20.0
) -> tuple[list[SweepPoint], float]:
    """Parse the fan wall sweep table out of RESULTS.md.

    This is the only airflow sweep in the repo, and it is exactly the experiment
    needed to calibrate how a supply deficit turns into recirculation: six
    converged points walking from 68% to 127% of server demand, straight through
    the balance point where gap flow changes sign.

    Read from the markdown rather than transcribed here, so the numbers cannot
    drift from the write-up. Returns (points, supply_temp_c).
    """
    rows: list[SweepPoint] = []
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip().strip("*") for c in s.strip("|").split("|")]
        if len(cells) != 9:
            continue
        try:
            # minus signs in the table are U+2212, not ASCII hyphen
            nums = [
                float(c.replace("−", "-").replace("%", "").strip())
                for c in cells[:8]
            ]
        except ValueError:
            continue  # header or separator row
        rows.append(
            SweepPoint(
                discharge_ms=nums[0],
                percent_demand=nums[1],
                inlet_mean_c=nums[2],
                inlet_peak_c=nums[3],
                exhaust_c=nums[4],
                supply_kgs=nums[5],
                through_kgs=nums[6],
                gap_kgs=nums[7],
                verdict=cells[8],
            )
        )
    if not rows:
        raise ValueError(f"no sweep table found in {path}")
    return rows, supply_c
