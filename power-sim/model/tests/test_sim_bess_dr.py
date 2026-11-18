import json

import pytest

from dtpower.sims import SIMS, bess_dr

IDS = [s["id"] for s in bess_dr.SCENARIOS]


@pytest.mark.parametrize("sid", IDS)
def test_every_scenario_runs_and_serialises(sid):
    r = bess_dr.simulate(sid)
    sc = r["scenario"]
    assert len(r["rows"]) == round(sc["hours"] * 60 / sc["dt_min"])
    json.dumps(r)


@pytest.mark.parametrize("sid", IDS)
def test_power_balances_at_the_point_of_connection(sid):
    for row in bess_dr.simulate(sid)["rows"]:
        a = row["assets"]
        net = a["UTIL"]["import_kw"] - a["UTIL"]["export_kw"]
        # what the bus draws, less what the BESS and the generator put in
        bus = a["UPS-1"]["input_kw"] - a["BESS-1"]["ac_kw"] - a["GEN-1"]["kw"]
        if row["grid_up"]:
            assert net == pytest.approx(bus, abs=1e-6)
        else:
            assert net == 0
            if a["GEN-1"]["islanded"] and a["UPS-1"]["status"] != "load dropped":
                assert bus == pytest.approx(0, abs=1e-6)       # islanded: the set carries it all


@pytest.mark.parametrize("sid", IDS)
def test_never_exports_when_export_is_off(sid):
    for row in bess_dr.simulate(sid)["rows"]:
        a = row["assets"]
        assert a["UPS-1"]["input_kw"] - a["BESS-1"]["ac_kw"] - a["GEN-1"]["kw"] >= -1e-6


def test_spike_day_saves_money_and_the_split_adds_up():
    s = bess_dr.simulate("nsw-spike-cap")["summary"]
    assert s["saving_bess"] > 1000
    assert s["saving_cap"] > 0
    assert s["saving"] == pytest.approx(s["saving_bess"] + s["saving_cap"])
    assert s["saving"] == pytest.approx(s["bill_saving"] - s["wear_cost"] + s["stored_energy_value"])
    assert s["mean_discharge_price"] > 10 * s["mean_charge_price"]
    assert s["gpu_work_lost_server_h"] > 0


def test_flat_price_loses_money():
    s = bess_dr.simulate("flat")["summary"]
    assert s["saving"] < 0
    assert s["bess_discharged_kwh"] == 0


def test_disabled_bess_saves_nothing():
    s = bess_dr.simulate("nsw-spike", {"BESS-1": {"enabled": False}})["summary"]
    assert s["saving"] == pytest.approx(0)


def test_negative_prices_are_charged_into():
    assert bess_dr.simulate("sa-negative")["summary"]["mean_charge_price"] < 0


@pytest.mark.parametrize("sid", ["nsw-spike", "nsw-peaks", "nsw-morning-optimal", "tou"])
def test_optimal_beats_thresholds(sid):
    """Perfect foresight should match or beat hand-set thresholds. It plans on a
    grid of SoC levels at full power, so it may trail them by a few percent."""
    opt = bess_dr.simulate(sid, {"DR-1": {"strategy": "optimal"}})["summary"]["saving"]
    thr = bess_dr.simulate(sid, {"DR-1": {"strategy": "threshold"}})["summary"]["saving"]
    assert opt >= thr * 0.95


def test_outage_rides_through_then_drops_load():
    rows = bess_dr.simulate("outage")["rows"]
    down = [x["assets"] for x in rows if not x["grid_up"]]
    assert len(down) == 25
    assert all(a["BESS-1"]["status"] == "tripped" for a in down)
    assert down[0]["UPS-1"]["status"] == "on battery"
    assert down[-1]["UPS-1"]["status"] == "load dropped"
    bigger = bess_dr.simulate("outage", {"UPS-1": {"capacity_kwh": 120}})
    assert bigger["summary"]["unserved_kwh"] == 0


def test_never_exceeds_connection_while_charging():
    r = bess_dr.simulate("nsw-spike", {"UTIL": {"capacity_kw": 250}})
    assert r["summary"]["over_capacity_steps"] == 0


def test_describe_is_complete_and_serialisable():
    d = SIMS["bess-dr"].describe()
    assert set(d["assets"]) == {"UTIL", "MSB", "BESS-1", "UPS-1", "GPU-1", "DR-1", "GEN-1"}
    assert d["assets"]["BESS-1"]["kind_proposed"] is True
    json.dumps(d)
