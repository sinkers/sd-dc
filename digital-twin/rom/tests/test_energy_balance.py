"""The loop must conserve mass and energy as tightly as the CFD does.

The CFD closes energy to ~0.1% (case-hall: 84.83 kg/s x 1005 x 10.15 K = 865 kW
against 864 kW imposed). A lumped model has no excuse to do worse, so this is
the gate: if the node bookkeeping ever leaks, these fail.
"""

import numpy as np
import pytest

from dthall import topology
from dthall.model import HallModel, Inputs


@pytest.fixture(params=["au01", "case-hall"])
def model(request):
    spec = (
        topology.from_cfd_export()
        if request.param == "au01"
        else topology.from_hall_parameters()
    )
    return HallModel(spec)


def test_energy_closes_at_steady_state(model):
    _, obs = model.steady_state()
    assert obs.it_load_kw > 0
    err = abs(obs.cooling_kw - obs.it_load_kw) / obs.it_load_kw
    assert err < 1e-3, f"energy closure {err:.4%}: {obs.cooling_kw=} {obs.it_load_kw=}"


def test_mass_closes_at_steady_state(model):
    _, obs = model.steady_state()
    # racks + spill - recirc must equal what the fans return
    assert abs(obs.mass_residual) < 1e-6 * obs.return_flow + 1e-9


def test_mass_closes_when_undersupplied(model):
    """Mass must still balance in the failure mode, where the racks are pulling
    more air than the fan wall delivers and the shortfall comes over the gap."""
    inputs = Inputs.design(model.spec)
    inputs.airflow_fraction[:] = 0.55
    _, obs = model.steady_state(inputs)
    assert obs.zone_net_flow.sum() < 0  # genuinely starved
    assert abs(obs.mass_residual) < 1e-6 * obs.return_flow + 1e-9


def n_minus_one_inputs(spec, load_kw_total):
    """One module offline, with the IT load scaled to something the remaining
    three modules can actually carry."""
    inputs = Inputs.design(spec).with_units_off(spec, [spec.module_names[0]])
    inputs.rack_kw *= load_kw_total / inputs.rack_kw.sum()
    return inputs


def test_energy_closes_with_a_module_offline(model):
    """N-1 within capacity: 3 x 237.5 = 712.5 kW installed, so hold the load at
    650 kW. Energy must still close."""
    inputs = n_minus_one_inputs(model.spec, 650.0)
    _, obs = model.steady_state(inputs)
    assert obs.extras["converged"]
    err = abs(obs.cooling_kw - obs.it_load_kw) / obs.it_load_kw
    assert err < 1e-3
    assert obs.module_flow[0] == 0.0


def test_a_module_offline_at_full_load_has_no_steady_state(model):
    """Design load exceeds N-1 capacity (864 or 742 kW against 712.5 kW), so the
    coils saturate and the hall heats until something trips. The model must show
    that rather than silently reporting a settled state."""
    inputs = Inputs.design(model.spec).with_units_off(
        model.spec, [model.spec.module_names[0]]
    )
    assert inputs.rack_kw.sum() > 3 * model.spec.modules[1].capacity_kw
    _, obs = model.steady_state(inputs, max_time=1500.0)
    assert not obs.extras["converged"]
    assert obs.module_saturated[1:].all()
    assert obs.cooling_kw < obs.it_load_kw  # the deficit is what heats the hall
    from dthall.constants import to_celsius

    assert to_celsius(obs.rack_inlet_k).max() > model.spec.allowable_max_c


def test_rack_heat_all_reaches_the_air(model):
    """Every kW into a rack's metal must leave in its air stream at steady state."""
    _, obs = model.steady_state()
    from dthall.constants import CP

    carried_kw = obs.rack_flow * CP * (obs.rack_exhaust_k - obs.rack_inlet_k) / 1000.0
    live = obs.rack_kw > 0
    assert np.allclose(carried_kw[live], obs.rack_kw[live], rtol=2e-3)


def test_energy_closes_during_a_transient_too(model):
    """Mid-transient, IT load and cooling duty genuinely differ — the gap is heat
    going into or out of the hall's thermal mass. With that term accounted for
    the books must close at every instant, not just at equilibrium.

        it_load = cooling_duty + storage_rate
    """
    inputs = Inputs.design(model.spec)
    inputs.rack_kw *= 0.3
    state, _ = model.steady_state(inputs)

    stepped = Inputs.design(model.spec)
    worst = 0.0
    saw_real_storage = False
    for _ in range(600):
        state, obs = model.step(state, stepped, 0.5)
        residual = obs.it_load_kw - obs.cooling_kw - obs.storage_kw
        worst = max(worst, abs(residual) / max(obs.it_load_kw, 1e-9))
        if abs(obs.storage_kw) > 0.05 * obs.it_load_kw:
            saw_real_storage = True
    assert saw_real_storage, "the step should visibly charge the thermal mass"
    assert worst < 1e-6, f"transient energy residual {worst:.2e}"


def test_storage_is_zero_at_equilibrium(model):
    _, obs = model.steady_state()
    assert abs(obs.storage_kw) < 1e-3 * obs.it_load_kw


def test_no_load_means_no_heat(model):
    inputs = Inputs.design(model.spec)
    inputs.rack_kw[:] = 0.0
    _, obs = model.steady_state(inputs)
    assert obs.cooling_kw == pytest.approx(0.0, abs=1.0)
    # the whole hall settles at supply temperature
    assert np.allclose(obs.rack_inlet_k, obs.rack_inlet_k[0], atol=0.05)
