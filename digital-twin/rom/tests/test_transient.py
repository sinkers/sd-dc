"""Transient behaviour: the twin has to respond to a load step like a hall, not
like a spreadsheet.

These assertions are about *shape* — that there is a lag, that it has roughly
the right magnitude, that nothing rings or blows up — not about matching
measured data. The steady CFD carries no transient information, so the time
constants come from rack thermal mass and air volumes chosen on physical
grounds. That limit is recorded in docs/ROM.md and asserted here only as a
sanity envelope.
"""

import numpy as np
import pytest

from dthall import topology
from dthall.constants import to_celsius
from dthall.model import HallModel, Inputs


@pytest.fixture(scope="module")
def model():
    return HallModel(topology.from_cfd_export())


def run(model, inputs, seconds, dt=0.5, state=None):
    state = state if state is not None else model.initial_state(inputs)
    trace = []
    for _ in range(int(seconds / dt)):
        state, obs = model.step(state, inputs, dt)
        trace.append((state.t, float(obs.rack_inlet_k.mean()), float(state.T_hot)))
    return state, np.array(trace)


def test_a_load_step_does_not_move_temperatures_instantly(model):
    """Half the B300 racks jump from idle to full: the hot aisle must ramp, not
    teleport."""
    inputs = Inputs.design(model.spec)
    inputs.rack_kw *= 0.3
    state, _ = model.steady_state(inputs)
    hot_before = state.T_hot

    stepped = Inputs.design(model.spec)
    _, trace = run(model, stepped, seconds=600.0, state=state)

    t, _, hot = trace.T
    total_rise = hot[-1] - hot_before
    assert total_rise > 3.0, "the step should actually matter"
    # nothing like the full rise arrives in the first couple of seconds
    at_2s = hot[np.argmin(np.abs(t - (state.t + 2.0)))] - hot_before
    assert at_2s < 0.35 * total_rise


def test_the_hot_aisle_time_constant_is_in_the_expected_range(model):
    """Tens of seconds to a couple of minutes: rack metal plus air transport.
    A twin that settled in 2 s or took an hour would both look wrong on screen."""
    inputs = Inputs.design(model.spec)
    inputs.rack_kw *= 0.3
    state, _ = model.steady_state(inputs)
    hot0 = state.T_hot

    _, trace = run(model, Inputs.design(model.spec), seconds=1200.0, state=state)
    t, _, hot = trace.T
    hot_final = hot[-1]
    target = hot0 + 0.632 * (hot_final - hot0)  # 1 - 1/e
    tau = t[np.argmax(hot >= target)] - state.t
    assert 10.0 < tau < 180.0, f"time constant {tau:.0f} s"


def test_the_response_is_monotonic_and_stable(model):
    """Explicit RK2 at the service's default dt must not ring or diverge."""
    inputs = Inputs.design(model.spec)
    inputs.rack_kw *= 0.3
    state, _ = model.steady_state(inputs)

    _, trace = run(model, Inputs.design(model.spec), seconds=900.0, dt=0.5, state=state)
    hot = trace[:, 2]
    assert np.all(np.diff(hot) > -1e-6), "overshoot/ringing in the hot aisle"
    assert np.all(np.isfinite(hot))
    assert to_celsius(hot.max()) < 200.0


def test_supply_temperature_lags_its_setpoint(model):
    """The coil has a time constant; the supply air must not snap to a new
    setpoint the instant the operator drags the slider."""
    inputs = Inputs.design(model.spec)
    state, _ = model.steady_state(inputs)
    before = state.T_sup.mean()

    colder = Inputs.design(model.spec)
    colder.supply_temp_c = model.spec.supply_temp_c - 5.0
    state2, _ = model.step(state, colder, dt=1.0)
    moved = before - state2.T_sup.mean()
    assert 0.0 < moved < 1.0, f"supply moved {moved:.3f} K in one second"


def test_fan_flow_follows_load_so_the_rise_stays_bounded(model):
    """Rack fans track load, so dropping the load must not collapse the achieved
    temperature rise — it should stay near the design rise."""
    from dthall.constants import CP

    for scale in (1.0, 0.6, 0.3):
        inputs = Inputs.design(model.spec)
        inputs.rack_kw *= scale
        _, obs = model.steady_state(inputs)
        live = obs.rack_kw > 0
        rise = (obs.rack_exhaust_k - obs.rack_inlet_k)[live]
        assert 5.0 < rise.mean() < model.spec.design_delta_t_k + 2.0
        carried = (obs.rack_flow * CP * (obs.rack_exhaust_k - obs.rack_inlet_k))[live]
        assert np.allclose(carried / 1000.0, obs.rack_kw[live], rtol=3e-3)


def test_the_twin_can_run_faster_than_real_time(model):
    """Budget check: the service publishes at 10 Hz, so a step must cost far less
    than the wall-clock interval it represents."""
    import time

    inputs = Inputs.design(model.spec)
    state = model.initial_state(inputs)
    n = 400
    t0 = time.perf_counter()
    for _ in range(n):
        state, _ = model.step(state, inputs, 0.5)
    per_step_ms = (time.perf_counter() - t0) / n * 1000.0
    assert per_step_ms < 25.0, f"{per_step_ms:.1f} ms per 0.5 s step"


def test_rack_fans_lag_a_load_drop_rather_than_stepping(model):
    """When the GPUs pause, the fans must coast rather than collapse.

    Real server fan controllers track component temperature, not power draw, so
    airflow does not step down the instant a load drops. Modelling it as
    instantaneous produced a 14 K exhaust temperature spike on every checkpoint
    dip — reduced airflow over still-hot heatsinks — which read as the hall
    getting hotter when the load went down.

    The exhaust *should* still warm somewhat (airflow falls faster than the metal
    cools). It should not leap.
    """
    from dthall.constants import to_celsius

    inputs = Inputs.design(model.spec)
    state, obs = model.steady_state(inputs)
    i = model.spec.rack_names.index("A05")
    flow_before = obs.rack_flow[i]
    out_before = to_celsius(obs.rack_exhaust_k[i])

    dip = Inputs.design(model.spec)
    for j, r in enumerate(model.spec.racks):
        if r.rack_class == "b300":
            dip.rack_kw[j] = r.design_kw * 0.30

    # one second after the step the fans have barely moved
    s1, o1 = model.step(state, dip, 1.0)
    assert o1.rack_flow[i] > 0.9 * flow_before, "fans stepped instead of lagging"

    peak = out_before
    st = state
    for _ in range(720):  # 6 minutes
        st, o = model.step(st, dip, 0.5)
        peak = max(peak, to_celsius(o.rack_exhaust_k[i]))
        flow = o.rack_flow[i]
    assert flow < 0.45 * flow_before, "fans should eventually follow the load down"
    # warms, but modestly — not the 14 K leap an instant-fan model produced
    assert 1.0 < peak - out_before < 8.0, f"exhaust rose {peak - out_before:.1f} K"


def test_fan_lag_does_not_disturb_the_steady_state(model):
    """The lag is a transient parameter only. At equilibrium the fan sits at its
    target, so the CFD calibration cannot be affected by it."""
    from dthall.params import RomParams
    import numpy as np

    slow = HallModel(model.spec, RomParams(fan_tau_s=120.0))
    fast = HallModel(model.spec, RomParams(fan_tau_s=2.0))
    _, a = slow.steady_state()
    _, b = fast.steady_state()
    assert np.allclose(a.rack_flow, b.rack_flow, rtol=1e-4)
    assert np.allclose(a.rack_inlet_k, b.rack_inlet_k, atol=1e-3)
