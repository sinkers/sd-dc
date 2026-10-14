import math

import pytest

from dtpower.components import Battery, Converter

DT = 5 / 60


def test_energy_bookkeeping_matches_efficiency():
    b = Battery({"capacity_kwh": 100, "soc_init_pct": 50, "cell_rte_pct": 81, "self_discharge_pct_day": 0})
    e0 = b.energy_kwh
    b.exchange(-20, DT)                      # charge 20 kW
    assert b.energy_kwh - e0 == pytest.approx(20 * DT * 0.9)
    e1 = b.energy_kwh
    b.exchange(20, DT)                       # discharge 20 kW
    assert e1 - b.energy_kwh == pytest.approx(20 * DT / 0.9)


def test_round_trip_returns_rte():
    b = Battery({"capacity_kwh": 100, "soc_init_pct": 10, "soc_min_pct": 0, "soc_max_pct": 100,
                 "cell_rte_pct": 90, "max_c_rate": 1, "self_discharge_pct_day": 0})
    for _ in range(12):
        b.exchange(-50, DT)
    for _ in range(200):
        b.exchange(50, DT)
    # everything put in, plus the 10 kWh it started with, comes back out at eta
    added = b.charged_kwh * math.sqrt(0.9)
    assert b.discharged_kwh == pytest.approx((added + 10) * math.sqrt(0.9), rel=1e-6)


def test_soc_window_and_c_rate_are_respected():
    b = Battery({"capacity_kwh": 100, "soc_init_pct": 50, "soc_min_pct": 10, "soc_max_pct": 90, "max_c_rate": 0.5,
                 "self_discharge_pct_day": 0})
    assert b.exchange(1000, DT) == pytest.approx(50)     # C-rate
    for _ in range(500):
        b.exchange(1000, DT)
    assert b.soc == pytest.approx(0.10, abs=1e-6)
    assert b.exchange(10, DT) == pytest.approx(0, abs=1e-6)
    for _ in range(500):
        b.exchange(-1000, DT)
    assert b.soc <= 0.90 + 1e-9


def test_wear_cost_is_per_mwh_discharged():
    b = Battery({"capacity_kwh": 1000, "soc_init_pct": 100, "max_c_rate": 1, "wear_cost_per_mwh": 30})
    for _ in range(12):
        b.exchange(500, DT)                  # 500 kWh out
    assert b.wear_cost == pytest.approx(15)
    assert b.equivalent_cycles == pytest.approx(0.5)


def test_converter_is_its_own_inverse():
    c = Converter({"eff_pct": 97})
    for ac in (-150, -1, 0, 1, 150):
        assert c.ac_for_dc(c.dc_for_ac(ac)) == pytest.approx(ac)
    assert c.dc_for_ac(97) == pytest.approx(100)
    assert c.dc_for_ac(-100) == pytest.approx(-97)
