"""Mode control: what manual and auto actually do to the hall."""

import numpy as np
import pytest

from dthall import topology
from dthall.constants import to_celsius
from dthall.profiles import ProfileConfig
from dthall.sim import SimEngine


@pytest.fixture(scope="module")
def spec():
    return topology.from_cfd_export()


def test_manual_load_drives_only_the_b300_racks(spec):
    engine = SimEngine(spec, mode="manual")
    before = engine.inputs.rack_kw.copy()
    engine.set_load("global", 12.0)
    after = engine.inputs.rack_kw

    for i, r in enumerate(spec.racks):
        if r.rack_class == "b300":
            assert after[i] == pytest.approx(12.0)
        else:
            assert after[i] == pytest.approx(before[i]), f"{r.name} should not move"
    assert len(engine.driven) == 16


def test_per_rack_override_beats_the_global_setpoint(spec):
    engine = SimEngine(spec, mode="manual")
    engine.set_load("global", 12.0)
    engine.set_load("A05", 45.0)
    kw = engine.inputs.rack_kw
    assert kw[spec.rack_names.index("A05")] == pytest.approx(45.0)
    assert kw[spec.rack_names.index("A04")] == pytest.approx(12.0)

    engine.clear_override("A05")
    assert engine.inputs.rack_kw[spec.rack_names.index("A05")] == pytest.approx(12.0)


def test_setting_a_load_takes_the_twin_out_of_auto(spec):
    """Otherwise the operator drags a slider and the profile silently overwrites
    it on the next tick, which reads as the control being broken."""
    engine = SimEngine(spec, mode="auto")
    engine.advance(60.0)
    engine.set_load("global", 15.0)
    assert engine.mode == "manual"
    engine.advance(30.0)
    assert engine.inputs.rack_kw[engine.driven[0]] == pytest.approx(15.0)


def test_auto_mode_moves_the_load_over_time(spec):
    engine = SimEngine(spec, mode="auto", seed=5)
    loads = []
    for _ in range(120):
        engine.advance(5.0)
        loads.append(float(engine.inputs.rack_kw[engine.driven].sum()))
    assert np.std(loads) > 5.0, "auto mode should not be flat"
    assert max(loads) <= sum(spec.racks[i].design_kw for i in engine.driven) + 1e-6


def test_auto_mode_heats_and_cools_the_hall_as_the_job_runs(spec):
    engine = SimEngine(
        spec,
        mode="auto",
        seed=6,
        profile_config=ProfileConfig(
            checkpoint_interval_s=200.0, checkpoint_duration_s=60.0
        ),
    )
    engine.settle()
    hot = []
    for _ in range(300):
        snap = engine.advance(4.0)
        hot.append(to_celsius(snap.state.T_hot))
    assert max(hot) - min(hot) > 1.0, "checkpoint dips should be visible in the hall"


def test_switching_back_to_auto_restarts_the_job(spec):
    engine = SimEngine(spec, mode="auto", seed=7)
    engine.advance(600.0)
    assert engine.profile.t > 0
    engine.set_mode("manual")
    engine.set_mode("auto")
    assert engine.profile.t == 0.0
    assert engine.profile.phase == "ramp"


def test_cooling_controls_apply(spec):
    engine = SimEngine(spec, mode="manual")
    engine.set_unit("W1", False)
    assert not engine.inputs.unit_on[spec.module_names.index("W1")]
    engine.set_unit_airflow("E1", 0.5)
    assert engine.inputs.airflow_fraction[spec.module_names.index("E1")] == 0.5
    engine.set_supply_temp(21.0)
    assert engine.inputs.supply_temp_c == 21.0


@pytest.mark.parametrize(
    "call,args",
    [
        ("set_mode", ("sideways",)),
        ("set_load", ("global", -1.0)),
        ("set_unit", ("Q7", True)),
        ("set_unit_airflow", ("W1", 5.0)),
        ("set_supply_temp", (99.0,)),
        ("set_speed", (-1.0,)),
    ],
)
def test_invalid_control_input_is_rejected(spec, call, args):
    engine = SimEngine(spec)
    with pytest.raises(ValueError):
        getattr(engine, call)(*args)


def test_advance_accumulates_partial_timesteps(spec):
    """The service hands over whatever the wall clock gave it, which will not be
    a whole number of physics steps."""
    engine = SimEngine(spec, dt=0.5, mode="manual")
    t0 = engine.state.t
    for _ in range(10):
        engine.advance(0.17)
    advanced = engine.state.t - t0
    assert advanced == pytest.approx(1.5, abs=1e-9)  # 1.7 s in, 3 whole steps taken
    assert engine._accumulator == pytest.approx(0.2, abs=1e-9)


def test_settle_reaches_equilibrium_before_publishing(spec):
    engine = SimEngine(spec, mode="manual")
    snap = engine.settle()
    assert snap.obs.extras["converged"]
    assert abs(snap.obs.cooling_kw - snap.obs.it_load_kw) / snap.obs.it_load_kw < 1e-3


def test_snapshot_carries_a_verdict(spec):
    engine = SimEngine(spec, mode="manual")
    snap = engine.settle()
    assert snap.verdict in ("PASS", "MARGINAL", "FAIL")
    assert snap.verdict_reason
