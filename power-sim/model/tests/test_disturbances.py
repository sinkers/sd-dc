"""Grid disturbances: sags, ride-through, resync, recharge under max demand,
and the BESS's fault ride-through, reconnect and peak shaving."""

import pytest

from dtpower.components import BESS, UPS
from dtpower.components.supply import NORMAL, GridEvents, Supply
from dtpower.sims import bess_dr

DT = 1 / 3600  # one second
SAG = Supply(up=True, v_pct=70, dip_ms=150)


def test_sag_is_an_event_not_a_sample():
    ev = GridEvents(sags=[{"t": 14.0, "residual_pct": 70, "duration_ms": 150}])
    two_s = 2 / 3600
    hit = ev.at(14.0, two_s)
    assert hit.v_pct == 70 and hit.dip_ms == pytest.approx(150)
    assert ev.at(14.0 - two_s, two_s) is NORMAL
    assert ev.at(14.0 + two_s, two_s) is NORMAL
    # a sag starting mid-step still lands in that step
    assert ev.at(14.0 - 1 / 3600, two_s).v_pct == 70


def test_outage_window_is_not_up():
    ev = GridEvents(outages=[[14.0, 14.0 + 2 / 3600]])
    assert not ev.at(14.0, DT) and ev.at(14.0 + 3 / 3600, DT)


@pytest.mark.parametrize("ride_through,expect", [(False, True), (True, False)])
def test_ups_ride_through_decides_whether_a_sag_transfers(ride_through, expect):
    u = UPS({"ride_through": ride_through})
    assert u.input_trips(SAG) is expect


def test_ride_through_has_limits():
    u = UPS({"ride_through": True, "ride_through_ms": 500, "ride_through_floor_pct": 50})
    assert u.input_trips(Supply(v_pct=70, dip_ms=800))     # too long
    assert u.input_trips(Supply(v_pct=40, dip_ms=100))     # too deep
    assert not u.input_trips(Supply(v_pct=88, dip_ms=5000))  # inside the input window


def test_ups_stays_on_battery_until_resync_then_walks_in_and_recharges():
    u = UPS({"ride_through": False, "resync_s": 30, "walk_in_s": 4, "recharge_pct": 10})
    u.step(140, DT, SAG)
    assert u.status == "on battery" and u.input_kw == 0
    seen = []
    for _ in range(45):
        u.step(140, DT, NORMAL)
        seen.append(u.status)
    assert seen[:29].count("resync") == 29
    assert "walk-in" in seen
    assert seen[-1] == "recharging"
    assert u.transfers == 1


def test_another_sag_restarts_the_resync():
    u = UPS({"ride_through": False, "resync_s": 30})
    u.step(140, DT, SAG)
    for _ in range(20):
        u.step(140, DT, NORMAL)
    u.step(140, DT, SAG)
    assert u.snapshot()["resync_remaining_s"] == pytest.approx(30)


def test_recharge_is_held_under_max_demand():
    u = UPS({"recharge_pct": 20, "max_demand_enabled": True, "max_demand_kw": 160, "soc_init_pct": 50})
    u.step(140, DT, NORMAL)
    assert u.input_kw == pytest.approx(160)
    assert u.recharge_limited
    free = UPS({"recharge_pct": 20, "soc_init_pct": 50})
    free.step(140, DT, NORMAL)
    assert free.input_kw > 190 and not free.recharge_limited


def test_max_demand_never_limits_the_load_itself():
    u = UPS({"max_demand_enabled": True, "max_demand_kw": 100, "soc_init_pct": 50})
    u.step(140, DT, NORMAL)
    assert u.output_kw == 140 and u.recharge_kw == 0
    assert u.over_demand_s > 0


def test_bess_lvrt_rides_through_a_sag_and_trips_without_it():
    on = BESS({"lvrt": True})
    on.step(100, DT, SAG)
    assert not on.tripped and on.status == "discharging"
    off = BESS({"lvrt": False})
    off.step(100, DT, SAG)
    assert off.tripped and off.status == "tripped"


def test_bess_reconnects_after_delay_and_ramps():
    b = BESS({"lvrt": False, "reconnect_s": 60, "ramp_pct_per_min": 50, "pcs_rated_kw": 200,
              "aux_kw": 0, "pcs_no_load_kw": 0, "max_c_rate": 1})
    b.step(200, DT, SAG)
    for _ in range(59):
        assert b.step(200, DT, NORMAL) == 0
    assert b.status == "reconnecting"
    b.step(200, DT, NORMAL)                      # reconnects this step
    first = b.step(200, DT, NORMAL)
    assert 0 < first < 10                        # ramp just started
    for _ in range(120):
        last = b.step(200, DT, NORMAL)
    assert last == pytest.approx(200)            # full after two minutes at 50 %/min


def test_peak_shave_holds_the_site_and_ride_through_removes_the_event():
    shave = bess_dr.simulate("sag-bess-shave")["summary"]
    assert shave["peak_import_kw"] == pytest.approx(160, abs=0.5)
    plain = bess_dr.simulate("sag-no-ride-through")["summary"]
    assert plain["peak_import_kw"] > 190
    rt = bess_dr.simulate("sag-ride-through")["summary"]
    assert rt["ups_transfers"] == 0 and rt["ups_min_soc_pct"] == pytest.approx(100)


def test_max_demand_scenario_holds_ups_input():
    s = bess_dr.simulate("sag-max-demand")["summary"]
    assert s["ups_peak_input_kw"] == pytest.approx(160, abs=0.01)
    assert s["ups_over_demand_s"] == 0


def test_storm_keeps_the_ups_on_battery_and_drains_it():
    s = bess_dr.simulate("sag-storm")["summary"]
    single = bess_dr.simulate("sag-no-ride-through")["summary"]
    assert s["ups_on_battery_s"] > 2.5 * single["ups_on_battery_s"]
    assert s["ups_min_soc_pct"] < 60


def test_bess_without_lvrt_trips_and_lets_the_peak_through():
    s = bess_dr.simulate("sag-bess-trips")["summary"]
    assert s["bess_trips"] == 1 and s["peak_import_kw"] > 170


def test_disturbance_rows_have_second_resolution_clocks():
    rows = bess_dr.simulate("sag-no-ride-through")["rows"]
    assert len(rows[0]["clock"]) == 8 and rows[1]["t"] - rows[0]["t"] == pytest.approx(2 / 3600)
    hit = [r for r in rows if r["v_pct"] < 90]
    assert len(hit) == 1 and hit[0]["clock"] == "14:00:00"
