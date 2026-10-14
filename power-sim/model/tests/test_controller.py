import pytest

from dtpower.components import BESS, PriceController

DT = 5 / 60


def decide(ctrl, price, bess, site=150, cap=400, export=False, step=0):
    return ctrl.decide(price, step, DT, bess, site, cap, export)


def test_thresholds():
    c = PriceController({"charge_below": 50, "discharge_above": 300})
    b = BESS({"pcs_rated_kw": 200})
    assert decide(c, 20, b) == -200
    assert decide(c, 100, b) == 0
    assert decide(c, 500, b) > 0


def test_no_export_limits_discharge_to_site_draw():
    c = PriceController({"discharge_above": 300})
    b = BESS({"pcs_rated_kw": 200, "aux_kw": 2, "pcs_no_load_kw": 0.5})
    assert decide(c, 500, b, site=120) == pytest.approx(122.5)
    assert decide(c, 500, b, site=120, export=True) == pytest.approx(200)


def test_charge_respects_connection_headroom():
    c = PriceController({"charge_below": 50})
    b = BESS({"pcs_rated_kw": 200, "aux_kw": 0, "pcs_no_load_kw": 0})
    assert decide(c, 10, b, site=300, cap=400) == pytest.approx(-100)
    assert decide(c, 10, b, site=450, cap=400) == 0


def test_reserve_is_kept():
    c = PriceController({"discharge_above": 300, "reserve_pct": 40})
    b = BESS({"soc_init_pct": 40})
    assert decide(c, 1000, b) == 0
    assert c.decision == "hold"


def test_optimal_plan_charges_cheap_and_discharges_dear():
    c = PriceController({"strategy": "optimal", "reserve_pct": 10})
    b = BESS({"capacity_kwh": 100, "pcs_rated_kw": 100, "soc_init_pct": 10, "soc_min_pct": 10, "soc_max_pct": 90})
    forecast = [50.0] * 288
    forecast[100] = 5000.0
    forecast[10] = -20.0
    c.prepare(forecast, b, DT)
    assert c.plan[100] == 1 and c.plan[10] == -1


def test_optimal_saves_energy_for_the_spike():
    """The case a greedy ranking gets wrong: dear-ish prices just before a spike."""
    c = PriceController({"strategy": "optimal", "reserve_pct": 20})
    b = BESS({"capacity_kwh": 400, "pcs_rated_kw": 200, "soc_init_pct": 50})
    # Nothing is cheap enough to charge from (190 after losses and wear is
    # above 200), so the battery has only what it starts with, about seven
    # steps' worth. It must keep them for the spike.
    forecast = [190.0] * 288
    for i in range(72, 84):
        forecast[i] = 200.0          # 06:00-07:00
    for i in range(84, 90):
        forecast[i] = 4000.0         # 07:00-07:30
    c.prepare(forecast, b, DT)
    assert -1 not in c.plan
    assert all(c.plan[i] == 1 for i in range(84, 90))
    assert sum(c.plan[72:84]) <= 1


def test_optimal_skips_spreads_that_do_not_cover_losses():
    c = PriceController({"strategy": "optimal"})
    b = BESS({"wear_cost_per_mwh": 25})
    c.prepare([100.0] * 144 + [108.0] * 144, b, DT)
    assert 1 not in c.plan and -1 not in c.plan
