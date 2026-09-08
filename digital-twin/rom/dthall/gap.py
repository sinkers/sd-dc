"""Containment-gap closure — the governing law of the whole model.

From the CFD sweep (cfd-cabinet-cooling/RESULTS.md): the racks move their own
airflow regardless of what the fan wall delivers, and any shortfall is made up
the only way it can be — by pulling hot exhaust back over the containment into
the cold aisle. The verdict flips exactly where the gap flow crosses zero:

    supply > demand  ->  surplus cold air spills into the hot aisle (safe, but
                         you are paying to move air that removes no heat)
    supply < demand  ->  hot air recirculates into the rack intakes, and intake
                         temperature climbs toward exhaust temperature

AU01's hot aisle is open-topped, so this is not a leak around imperfect
panels — it is the design's intended return path, and the balance is the whole
question.

Two refinements over the single-number version:

  * zone coupling — a starved zone first draws surplus from a neighbouring zone
    before it resorts to the hot aisle, so a single module tripping does not
    instantly starve its own half.
  * baseline recirculation — aisle-end racks entrain some hot air even when the
    hall is comfortably oversupplied. The CFD shows this plainly: in
    verification/hall_v4, supply exceeds rack demand by 15% yet the four
    end-of-row racks still ingest ~1.3 K above the middle of the row.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .params import RomParams
from .topology import HallSpec

EPS = 1e-9


@dataclass
class GapSolution:
    """Airflow bookkeeping for one instant. All flows in kg/s."""

    zone_supply: np.ndarray  # after zone-to-zone migration
    zone_supply_direct: np.ndarray  # before migration
    zone_demand: np.ndarray
    zone_net: np.ndarray  # supply - demand; sign is the verdict
    zone_recirc_fraction: np.ndarray
    zone_spill: np.ndarray  # cold air passing over into the hot aisle
    rack_recirc_fraction: np.ndarray
    recirc_total: float  # hot air drawn back into intakes
    spill_total: float

    @property
    def starved(self) -> np.ndarray:
        return self.zone_net < 0.0


def distribution_matrix(spec: HallSpec, params: RomParams) -> np.ndarray:
    """(n_modules, n_zones) fraction of each module's discharge reaching each zone.

    A module throws `supply_reach` of its air into the near half of the pod and
    the rest to the far half, split equally between the two rows (the hall is
    symmetric about the hot aisle).
    """
    zones = spec.zones
    rows = sorted({z.row for z in zones})
    n_rows = len(rows)
    w = np.zeros((len(spec.modules), len(zones)))
    for i, m in enumerate(spec.modules):
        near = "west" if m.end == "west" else "east"
        for j, z in enumerate(zones):
            share = params.supply_reach if z.half == near else 1.0 - params.supply_reach
            w[i, j] = share / n_rows
    return w


def _migrate(net: np.ndarray, coupling: float) -> np.ndarray:
    """Move surplus air from surplus zones toward starved ones.

    Returns the per-zone signed transfer. Conserves mass exactly.
    """
    surplus = np.clip(net, 0.0, None)
    deficit = np.clip(-net, 0.0, None)
    total_surplus = surplus.sum()
    total_deficit = deficit.sum()
    movable = coupling * min(total_surplus, total_deficit)
    if movable <= EPS:
        return np.zeros_like(net)
    gives = -movable * surplus / total_surplus
    takes = movable * deficit / total_deficit
    return gives + takes


def solve(
    spec: HallSpec,
    params: RomParams,
    rack_flow: np.ndarray,
    module_flow: np.ndarray,
) -> GapSolution:
    """Resolve the supply/demand imbalance into recirculation and spill.

    Mass is conserved by construction: for every zone,

        supply_in = sum_racks (1 - phi) * m_rack + spill

    and every kilogram of recirculated air leaving the hot aisle is matched by a
    kilogram of spill entering it.
    """
    rack_flow = np.asarray(rack_flow, dtype=float)
    module_flow = np.asarray(module_flow, dtype=float)
    n_zones = len(spec.zones)
    zone_of = np.array(spec.rack_zone_indices())
    per_row = max(r.position for r in spec.racks) + 1

    w = distribution_matrix(spec, params)
    supply_direct = w.T @ module_flow

    demand = np.bincount(zone_of, weights=rack_flow, minlength=n_zones)

    net_direct = supply_direct - demand
    supply = supply_direct + _migrate(net_direct, params.zone_coupling)
    net = supply - demand

    deficit = np.clip(-net, 0.0, None)
    zone_phi = deficit / np.maximum(demand, EPS)

    baseline = np.array(
        [
            params.baseline_recirc(r.name, r.position, per_row)
            for r in spec.racks
        ]
    )
    # Saturating closure: see params.recirc_gain / recirc_exponent. The exponent
    # is why a small deficit hurts more than a linear reading suggests.
    driven = params.recirc_gain * np.power(
        np.clip(zone_phi, 0.0, None), params.recirc_exponent
    )
    phi = np.clip(
        baseline + driven[zone_of],
        0.0,
        params.max_recirc_fraction,
    )

    # Mass consistency: the recirculated mass in a zone must at least cover that
    # zone's deficit, otherwise the zone would be exporting air it never got.
    # A uniform additive correction, clipped, converges in a couple of passes.
    for _ in range(4):
        recirc = np.bincount(zone_of, weights=phi * rack_flow, minlength=n_zones)
        shortfall = deficit - recirc
        if np.all(shortfall <= 1e-6):
            break
        bump = np.clip(shortfall, 0.0, None) / np.maximum(demand, EPS)
        phi = np.clip(phi + bump[zone_of], 0.0, params.max_recirc_fraction)

    drawn_from_zone = np.bincount(
        zone_of, weights=(1.0 - phi) * rack_flow, minlength=n_zones
    )
    spill = np.clip(supply - drawn_from_zone, 0.0, None)

    recirc_total = float((phi * rack_flow).sum())
    return GapSolution(
        zone_supply=supply,
        zone_supply_direct=supply_direct,
        zone_demand=demand,
        zone_net=net,
        zone_recirc_fraction=zone_phi,
        zone_spill=spill,
        rack_recirc_fraction=phi,
        recirc_total=recirc_total,
        spill_total=float(spill.sum()),
    )
