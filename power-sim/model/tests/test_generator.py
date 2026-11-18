"""Generator: start on outage after a delay, island, retransfer with a break,
overload trip, price start with minimum run, minimum load and fuel."""

import pytest

from dtpower.components import Generator
from dtpower.components.supply import NORMAL, Supply
from dtpower.sims import bess_dr

DT = 1 / 3600
LOST = Supply(up=False, v_pct=0)


def run(g, supply, seconds, price=100.0, demand=150.0):
    for _ in range(seconds):
        g.control(0, DT, supply, price)
        g.dispatch(demand, DT)


def test_rating_is_prime_kva_times_pf():
    assert Generator({"prime_kva": 250, "pf": 0.8}).rated_kw == pytest.approx(200)


def test_starts_on_outage_and_takes_load_after_the_delay():
    g = Generator({"start_delay_s": 30})
    run(g, LOST, 30)                       # the step at t=0 signals the start; t=1..29 s it is cranking
    assert g.state == "starting" and g.kw == 0
    run(g, LOST, 1)                        # t=30 s: on load
    assert g.online and g.islanded
    assert g.bus_supply(LOST).up
    run(g, LOST, 1)
    assert g.kw == pytest.approx(150)


def test_outage_start_can_be_switched_off():
    g = Generator({"start_on_outage": False})
    run(g, LOST, 60)
    assert g.state == "off"


def test_retransfer_waits_then_breaks_the_bus():
    g = Generator({"start_delay_s": 0, "retransfer_s": 10, "transfer_ms": 100})
    run(g, LOST, 2)
    breaks = []
    for _ in range(12):
        g.control(0, DT, NORMAL, 100)
        breaks.append(g.bus_supply(NORMAL).v_pct)
        g.dispatch(150, DT)
    assert breaks.count(0.0) == 1          # one open-transition break
    assert g.state == "cooldown"


def test_overload_trips_and_stays_tripped():
    g = Generator({"prime_kva": 250, "pf": 0.8, "overload_pct": 110, "start_delay_s": 0})
    run(g, LOST, 1, demand=0)
    g.control(0, DT, LOST, 100)
    assert g.dispatch(225, DT) == 0
    assert g.state == "tripped" and g.trips == 1
    run(g, LOST, 30)
    assert g.state == "tripped"


def test_price_start_runs_its_minimum_time():
    g = Generator({"price_start": True, "price_threshold": 500, "start_delay_s": 0, "min_run_min": 1,
                   "start_on_outage": False})
    run(g, NORMAL, 2, price=800)
    assert g.online and not g.islanded
    run(g, NORMAL, 30, price=100)
    assert g.online                         # still inside its minimum run
    run(g, NORMAL, 40, price=100)
    assert g.state == "cooldown"


def test_price_below_threshold_does_not_start():
    g = Generator({"price_start": True, "price_threshold": 500})
    run(g, NORMAL, 60, price=499)
    assert g.state == "off"


def test_fuel_cost_counts_load_and_idle():
    g = Generator({"start_delay_s": 0, "fuel_l_per_kwh": 0.25, "fuel_price": 2.0, "idle_fuel_pct": 0})
    run(g, LOST, 3600, demand=100)
    assert g.kwh == pytest.approx(100, rel=1e-3)
    assert g.fuel_cost == pytest.approx(50, rel=1e-3)
    assert g.cost_per_mwh == pytest.approx(500)


def test_outage_scenario_rides_through_on_the_generator():
    s = bess_dr.simulate("outage-gen")["summary"]
    assert s["unserved_kwh"] == 0 and s["gen_trips"] == 0 and s["gen_kwh"] > 40
    assert s["ups_min_soc_pct"] > 85


def test_recharge_trips_the_generator_unless_max_demand_holds_it():
    trip = bess_dr.simulate("outage-gen-trip")["summary"]
    assert trip["gen_trips"] == 1 and trip["unserved_kwh"] > 0
    held = bess_dr.simulate("outage-gen-max-demand")["summary"]
    assert held["gen_trips"] == 0 and held["unserved_kwh"] == 0
    assert held["gen_peak_kw"] <= held["gen_rated_kw"] * 1.1


def test_price_generator_saves_money_on_a_site_without_a_bess():
    s = bess_dr.simulate("nsw-spike-gen")["summary"]
    assert s["saving_gen"] > 1000 and s["gen_fuel_cost"] > 0
    assert s["saving_bess"] == pytest.approx(0, abs=1e-6)


def test_generator_off_by_default_leaves_old_scenarios_alone():
    s = bess_dr.simulate("nsw-spike")["summary"]
    assert s["gen_kwh"] == 0 and s["saving_gen"] == pytest.approx(0)
