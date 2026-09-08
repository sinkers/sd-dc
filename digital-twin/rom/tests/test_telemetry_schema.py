"""The wire contract. Unreal binds to these names, so breaking them breaks the scene."""

import json

import pytest

from dthall import telemetry, topology
from dthall.sim import SimEngine


@pytest.fixture(scope="module")
def spec():
    return topology.from_cfd_export()


@pytest.fixture
def engine(spec):
    return SimEngine(spec, mode="manual", seed=1)


def test_hello_carries_everything_needed_to_bind_a_scene(spec):
    hello = telemetry.encode_hello(spec, dt=0.5, publish_hz=10.0)
    assert hello["schema_v"] == telemetry.SCHEMA_VERSION
    assert [r["name"] for r in hello["racks"]] == spec.rack_names
    assert [m["name"] for m in hello["modules"]] == spec.module_names
    assert hello["limits"]["allowable_c"] == spec.allowable_max_c
    # the rack names must be the FreeCAD/CFD identifiers, not indices
    assert "A05" in [r["name"] for r in hello["racks"]]


def test_state_frame_is_json_serialisable_and_keyed_by_name(engine, spec):
    frame = telemetry.encode_state(engine.snapshot(), spec)
    text = json.dumps(frame)
    assert json.loads(text) == frame
    assert set(frame["racks"]) == set(spec.rack_names)
    assert set(frame["supply"]) == set(spec.module_names)
    assert set(frame["zones"]) == set(spec.zone_names)


def test_state_frame_reports_celsius_and_volumetric_flow(engine, spec):
    frame = telemetry.encode_state(engine.snapshot(), spec)
    rack = frame["racks"]["A05"]
    assert 10.0 < rack["t_in"] < 60.0, "temperatures must be Celsius on the wire"
    assert rack["flow_m3h"] > 1000.0, "flows must be m3/h on the wire"
    assert 0.0 <= rack["recirc"] <= 1.0
    assert rack["status"] in ("ok", "over_recommended", "over_allowable")


def test_frame_includes_the_derived_values_a_renderer_should_not_compute(engine, spec):
    frame = telemetry.encode_state(engine.snapshot(), spec)
    assert frame["verdict"] in ("PASS", "MARGINAL", "FAIL")
    assert "scale" in frame["fields"] and "offset_k" in frame["fields"]
    assert frame["totals"]["worst_rack"] in spec.rack_names
    for zone in frame["gap"].values():
        assert isinstance(zone["recirculating"], bool)


def test_auto_mode_frames_carry_profile_state(spec):
    engine = SimEngine(spec, mode="auto", seed=3)
    engine.advance(120.0)
    frame = telemetry.encode_state(engine.snapshot(), spec)
    assert frame["profile"]["phase"] in (
        "ramp",
        "sustained",
        "checkpoint",
        "eval",
        "straggler",
    )
    assert 0.0 <= frame["profile"]["mean_utilisation"] <= 1.0


def test_manual_mode_frames_omit_profile_state(engine, spec):
    frame = telemetry.encode_state(engine.snapshot(), spec)
    assert "profile" not in frame


def test_straggler_is_reported_as_a_rack_name_not_an_index(spec):
    from dthall.profiles import ProfileConfig

    engine = SimEngine(
        spec,
        mode="auto",
        seed=9,
        profile_config=ProfileConfig(
            straggler_rate_per_hour=900.0, straggler_duration_s=90.0
        ),
    )
    for _ in range(400):
        engine.advance(2.0)
        frame = telemetry.encode_state(engine.snapshot(), spec)
        strag = frame.get("profile", {}).get("straggler")
        if strag is not None:
            assert strag in spec.rack_names
            assert engine.spec.racks[spec.rack_names.index(strag)].rack_class == "b300"
            return
    pytest.fail("no straggler reported")


# -- commands --------------------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "cmd", "cmd": "set_mode", "mode": "manual"},
        {"type": "cmd", "cmd": "set_load", "target": "global", "kw": 20.0},
        {"type": "cmd", "cmd": "set_load", "target": "A05", "kw": 10.0},
        {"type": "cmd", "cmd": "set_unit", "unit": "W1", "on": False},
        {"type": "cmd", "cmd": "set_unit_airflow", "unit": "E2", "fraction": 0.6},
        {"type": "cmd", "cmd": "set_supply_temp", "celsius": 22.0},
        {"type": "cmd", "cmd": "set_speed", "x": 8.0},
        {"type": "cmd", "cmd": "auto_config", "seed": 42},
    ],
)
def test_valid_commands_parse_and_apply(engine, msg):
    ack = telemetry.apply_command(engine, telemetry.parse_command(msg))
    assert ack["type"] == "ack"
    assert ack["cmd"] == msg["cmd"]


@pytest.mark.parametrize(
    "msg,fragment",
    [
        ({"type": "state"}, "unexpected message type"),
        ({"type": "cmd", "cmd": "launch_missiles"}, "unknown command"),
        ({"type": "cmd", "cmd": "set_unit", "unit": "W1"}, "missing required field"),
        ({"type": "cmd", "cmd": "set_mode", "mode": "sideways"}, "unknown mode"),
        ({"type": "cmd", "cmd": "set_unit", "unit": "Z9", "on": True}, "unknown fan wall"),
        ({"type": "cmd", "cmd": "set_supply_temp", "celsius": 500.0}, "within"),
        ({"type": "cmd", "cmd": "set_load", "target": "nope", "kw": 5.0}, "unknown load"),
    ],
)
def test_invalid_commands_are_rejected_with_a_usable_reason(engine, msg, fragment):
    with pytest.raises((ValueError, TypeError)) as exc:
        telemetry.apply_command(engine, telemetry.parse_command(msg))
    assert fragment in str(exc.value)


def test_error_frames_are_serialisable():
    assert json.loads(json.dumps(telemetry.error("nope")))["type"] == "err"


def test_worst_rack_agrees_with_the_verdict_and_ignores_empty_positions(spec):
    """AU01's Concept-A schedule has three spare positions at 0 kW. They have a
    real air temperature but no IT to protect, so the verdict skips them — and
    the headline "worst rack" must skip them too, or the HUD contradicts itself."""
    engine = SimEngine(spec, mode="manual")
    engine.set_unit("W1", False)
    engine.set_unit("W2", False)
    snap = engine.settle()
    frame = telemetry.encode_state(snap, spec)

    spares = [r.name for r in spec.racks if r.design_kw == 0.0]
    assert spares, "expected some empty rack positions in this schedule"
    assert frame["totals"]["worst_rack"] not in spares
    assert frame["totals"]["populated_racks"] == len(spec.racks) - len(spares)
    # the verdict names the same rack it reports as worst
    if frame["verdict"] == "FAIL":
        assert frame["totals"]["worst_rack"] in frame["verdict_reason"]
    assert frame["totals"]["worst_t_in"] == pytest.approx(
        max(frame["racks"][n]["t_in"] for n in frame["racks"] if n not in spares)
    )
