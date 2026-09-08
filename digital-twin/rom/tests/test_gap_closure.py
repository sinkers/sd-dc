"""The governing law: the verdict flips where the containment gap flow crosses zero.

From cfd-cabinet-cooling/RESULTS.md — the racks move their design airflow
regardless of what the fan wall delivers, so a supply shortfall is made up by
pulling hot exhaust back over the containment, and intake temperature climbs
toward exhaust temperature. Oversupply instead spills cold air into the hot
aisle and buys nothing thermally.
"""

import numpy as np
import pytest

from dthall import topology
from dthall.constants import to_celsius
from dthall.model import HallModel, Inputs
from dthall.params import RomParams


@pytest.fixture
def model():
    return HallModel(topology.from_hall_parameters())


def sweep_point(model, fraction):
    inputs = Inputs.design(model.spec)
    inputs.airflow_fraction[:] = fraction
    _, obs = model.steady_state(inputs)
    return obs


def test_oversupply_spills_and_undersupply_recirculates(model):
    over = sweep_point(model, 1.0)
    under = sweep_point(model, 0.55)

    assert over.zone_net_flow.sum() > 0
    assert over.zone_spill.sum() > 0
    assert under.zone_net_flow.sum() < 0
    assert under.extras["recirc_total"] > over.extras["recirc_total"]


def test_intake_temperature_climbs_monotonically_as_supply_is_cut(model):
    fractions = [1.2, 1.0, 0.85, 0.7, 0.55, 0.4]
    means = [float(np.mean(sweep_point(model, f).rack_inlet_k)) for f in fractions]
    assert all(b >= a - 1e-6 for a, b in zip(means, means[1:])), means
    # and the swing is large: this is a design-relevant effect, not a nudge
    assert means[-1] - means[0] > 3.0


def test_the_verdict_flips_at_the_balance_point(model):
    """Walk down the supply until gap flow changes sign, and confirm the verdict
    changes with it rather than somewhere unrelated."""
    fractions = np.arange(1.3, 0.35, -0.05)
    verdicts, nets = [], []
    for f in fractions:
        obs = sweep_point(model, float(f))
        verdicts.append(model.verdict(obs)[0])
        nets.append(obs.zone_net_flow.sum())

    nets = np.array(nets)
    assert nets[0] > 0 and nets[-1] < 0, "the sweep must span the balance point"
    crossing = int(np.argmax(nets < 0))

    # Everything comfortably oversupplied passes on the mean; the FAIL verdicts
    # all live on the starved side of the crossing.
    assert all(v != "FAIL" for v in verdicts[:crossing])
    assert verdicts[-1] == "FAIL"


def test_when_oversupplied_middle_racks_ingest_supply_air(model):
    obs = sweep_point(model, 1.0)
    mid = [i for i, r in enumerate(model.spec.racks) if 3 <= r.position <= 8]
    supply_c = model.spec.supply_temp_c
    assert to_celsius(obs.rack_inlet_k[mid]).max() < supply_c + 1.0


def test_end_racks_run_hotter_than_the_middle_even_when_oversupplied(model):
    """The CFD shows this plainly (verification/hall_v4: end racks ~1.3 K above
    the row middle at 15% oversupply). It is what the baseline recirculation
    term exists to reproduce."""
    obs = sweep_point(model, 1.0)
    per_row = max(r.position for r in model.spec.racks) + 1
    ends = [i for i, r in enumerate(model.spec.racks) if r.position in (0, per_row - 1)]
    mid = [i for i, r in enumerate(model.spec.racks) if 3 <= r.position <= 8]
    assert obs.rack_inlet_k[ends].mean() - obs.rack_inlet_k[mid].mean() > 0.5


def test_peaks_are_more_recirculation_sensitive_than_means(model):
    """Mean intake alone will mislead you (RESULTS.md): the peak can sit near
    exhaust temperature while the mean still looks comfortable."""
    obs = sweep_point(model, 1.0)
    live = obs.rack_kw > 0
    assert np.all(obs.rack_inlet_peak_k[live] >= obs.rack_inlet_k[live] - 1e-9)
    spread_mean = obs.rack_inlet_k[live].max() - obs.rack_inlet_k[live].min()
    spread_peak = obs.rack_inlet_peak_k[live].max() - obs.rack_inlet_peak_k[live].min()
    assert spread_peak > spread_mean


def n_minus_one_inputs(spec, load_kw_total=650.0):
    """A west module offline, at a load the remaining three can carry (3 x 237.5
    = 712.5 kW), so the comparison is about distribution rather than a runaway."""
    inputs = Inputs.design(spec).with_units_off(spec, ["A1"])
    inputs.rack_kw *= load_kw_total / inputs.rack_kw.sum()
    return inputs


def test_losing_one_module_hurts_its_own_half_most(model):
    """Zone-level bookkeeping has to make a single module trip an asymmetric
    event, otherwise N-1 studies are meaningless."""
    spec = model.spec
    inputs = n_minus_one_inputs(spec)
    _, obs = model.steady_state(inputs)
    west = [i for i, z in enumerate(spec.zones) if z.half == "west"]
    east = [i for i, z in enumerate(spec.zones) if z.half == "east"]
    assert obs.zone_supply[west].sum() < obs.zone_supply[east].sum()

    west_racks = [i for i, r in enumerate(spec.racks) if spec.zones[
        spec.zone_index(r.zone)].half == "west"]
    east_racks = [i for i, r in enumerate(spec.racks) if spec.zones[
        spec.zone_index(r.zone)].half == "east"]
    assert obs.rack_inlet_k[west_racks].mean() > obs.rack_inlet_k[east_racks].mean()


def test_zone_coupling_decides_whether_a_surplus_rescues_a_starved_half(model):
    """Turn the west fan wall down hard at a moderate load: the hall is
    oversupplied overall, but the west half on its own is starved. Whether the
    east surplus migrates across and rescues it is exactly what zone_coupling
    controls, so the parameter must move the answer — it is one of the fitted
    ones and a fit cannot identify a coefficient that does nothing.
    """
    spec = model.spec
    inputs = Inputs.design(spec)
    inputs.rack_kw *= 450.0 / inputs.rack_kw.sum()
    west_modules = [i for i, m in enumerate(spec.modules) if m.end == "west"]
    inputs.airflow_fraction[west_modules] = 0.15

    isolated = HallModel(spec, RomParams(zone_coupling=0.0))
    shared = HallModel(spec, RomParams(zone_coupling=1.0))
    _, obs_iso = isolated.steady_state(inputs)
    _, obs_shared = shared.steady_state(inputs)

    west_zones = [i for i, z in enumerate(spec.zones) if z.half == "west"]
    assert obs_iso.zone_net_flow[west_zones].max() < 0, "west must be starved"
    assert obs_iso.zone_net_flow.sum() > 0, "hall must be oversupplied overall"

    west = [
        i
        for i, r in enumerate(spec.racks)
        if spec.zones[spec.zone_index(r.zone)].half == "west"
    ]
    assert obs_iso.rack_inlet_k[west].max() > obs_shared.rack_inlet_k[west].max() + 0.1
