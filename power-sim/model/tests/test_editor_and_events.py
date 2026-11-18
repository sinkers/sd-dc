"""Scenario editor (custom scenarios) and the sequence-of-events log."""

import json

import pytest

from dtpower.sims import bess_dr

SPEC = {"price": "nem:NSW1-2026-10-12", "window": [13, 17], "dt_s": 10,
        "events": [{"type": "price", "t": 13.5, "price": 9000, "duration_min": 15},
                   {"type": "load", "t": 14.5, "utilisation_pct": 30, "duration_min": 20},
                   {"type": "sag", "t": 15.0, "residual_pct": 60, "duration_ms": 200},
                   {"type": "outage", "t": 16.0, "duration_s": 120}],
        "params": {"UPS-1": {"ride_through": False}}}


def at(rows, clock):
    return next(r for r in rows if r["clock"] == clock)


def test_custom_scenario_applies_every_event_type():
    r = bess_dr.simulate("custom", custom=SPEC)
    rows = r["rows"]
    assert len(rows) == 4 * 360
    assert at(rows, "13:35:00")["price"] == 9000                       # price spike
    assert at(rows, "13:50:00")["price"] != 9000                       # and it ends
    gpu = at(rows, "14:40:00")["assets"]["GPU-1"]
    assert gpu["kw"] < at(rows, "14:20:00")["assets"]["GPU-1"]["kw"]   # load change
    assert at(rows, "15:00:00")["v_pct"] == 60                         # sag
    assert not at(rows, "16:01:00")["grid_up"]                         # outage
    assert at(rows, "16:03:00")["grid_up"]
    assert [e["type"] for e in r["injected"]] == ["price", "load", "sag", "outage"]
    json.dumps(r)


@pytest.mark.parametrize("bad,reason", [
    ({"window": [10, 9]}, "window"),
    ({"dt_s": 7}, "step"),
    ({"window": [0, 24], "dt_s": 1}, "too many"),
    ({"events": [{"type": "meteor", "t": 14}]}, "unknown event"),
    ({"price": "nem:nowhere"}, "unknown price day"),
])
def test_custom_scenario_rejects_bad_specs_with_a_reason(bad, reason):
    with pytest.raises(ValueError, match=reason):
        bess_dr.custom_scenario({**SPEC, **bad})


def test_every_preset_round_trips_through_the_editor():
    for sc in bess_dr.SCENARIOS:
        spec = bess_dr.editor_spec(sc)
        a = bess_dr.simulate(sc["id"])["summary"]
        b = bess_dr.simulate("custom", custom=spec)["summary"]
        assert b["saving"] == pytest.approx(a["saving"], abs=0.01), sc["id"]
        assert b["ups_on_battery_s"] == pytest.approx(a["ups_on_battery_s"]), sc["id"]


def test_storm_log_tells_the_story_in_order():
    log = bess_dr.simulate("sag-storm")["log"]
    ev = [(e["clock"], e["asset"], e["event"]) for e in log["events"]]
    sags = [c for c, a, t in ev if a == "UTIL" and t.startswith("Voltage sag")]
    assert sags == ["14:00:00", "14:02:00", "14:05:00", "14:06:30"]
    ups = [t for c, a, t in ev if a == "UPS-1"]
    assert ups[0].startswith("Transferred to battery")
    assert any(t.startswith("Recharging") for t in ups) and ups[-1] == "On line"
    assert [e["t"] for e in log["events"]] == sorted(e["t"] for e in log["events"])
    assert log["counts"]["alarm"] >= 8


def test_generator_outage_log_includes_start_island_and_retransfer():
    ev = [(e["asset"], e["event"]) for e in bess_dr.simulate("outage-gen")["log"]["events"]]
    gen = [t for a, t in ev if a == "GEN-1"]
    assert gen[0].startswith("Start signal (outage)")
    assert "On load, islanded: carrying the site" in gen
    assert "Off load, cooling down" in gen


def test_max_demand_breach_is_logged():
    spec = bess_dr.editor_spec(bess_dr.scenario("sag-no-ride-through"))
    spec["params"] = {**spec["params"], "UPS-1": {**spec["params"]["UPS-1"],
                                                  "max_demand_enabled": True, "max_demand_kw": 100}}
    ev = [e["event"] for e in bess_dr.simulate("custom", custom=spec)["log"]["events"]]
    assert any(t.startswith("Input above max demand") for t in ev)


def test_day_scenarios_log_bess_dispatch():
    ev = [(e["asset"], e["event"]) for e in bess_dr.simulate("nsw-spike")["log"]["events"]]
    assert ("BESS-1", "Discharging at 144 kW") in ev or any(a == "BESS-1" and t.startswith("Discharging") for a, t in ev)


def test_describe_serves_the_editor():
    d = bess_dr.describe()
    assert set(d["editor"]["event_types"]) == {"sag", "outage", "price", "load"}
    assert any(p["value"].startswith("nem:") for p in d["editor"]["price_sources"])
    assert all("editor" in s for s in d["scenarios"])


def test_an_event_from_the_browser_lands_on_its_own_step():
    """Hours arrive rounded from the browser; a sag on a step edge must not leak into the step before."""
    spec = {"price": "tou", "window": [13.9666667, 14.2], "dt_s": 2,
            "events": [{"type": "sag", "t": 13.9972222, "residual_pct": 70, "duration_ms": 150}],
            "params": {"UPS-1": {"ride_through": False}}}
    rows = bess_dr.simulate("custom", custom=spec)["rows"]
    hit = [r["clock"] for r in rows if r["v_pct"] < 90]
    assert hit == ["13:59:50"]


def test_an_injected_spike_does_not_inflate_the_value_of_stored_energy():
    """Stored energy is valued at the recorded day's median, not a window the spike dominates."""
    spec = {"price": "tou", "window": [13 + 58 / 60, 14 + 43 / 60], "dt_s": 2,
            "events": [{"type": "price", "t": 14 + 13 / 60, "price": 5000, "duration_min": 30}]}
    s = bess_dr.simulate("custom", custom=spec)["summary"]
    assert s["median_price"] == 110
    assert s["saving"] > 0.9 * s["bill_saving"] > 300
