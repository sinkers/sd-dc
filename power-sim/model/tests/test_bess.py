import pytest

from dtpower.components import BESS

DT = 5 / 60
QUIET = {"aux_kw": 0, "pcs_no_load_kw": 0}


def test_disabled_bess_does_nothing():
    b = BESS({"enabled": False})
    assert b.step(-200, DT) == 0 and b.status == "disabled"
    assert b.battery.soc == pytest.approx(0.5, abs=1e-4)


def test_trips_when_grid_is_lost():
    b = BESS()
    assert b.step(200, DT, grid_up=False) == 0
    assert b.status == "tripped"


def test_pcs_rating_limits_ac_power():
    b = BESS({"pcs_rated_kw": 100, "max_c_rate": 2, **QUIET})
    assert b.step(500, DT) == pytest.approx(100)
    assert b.status == "discharging"
    assert b.step(-500, DT) == pytest.approx(-100)
    assert b.status == "charging"


def test_aux_load_is_drawn_while_idle():
    b = BESS({"aux_kw": 3, "pcs_no_load_kw": 0.5})
    assert b.step(0, DT) == pytest.approx(-3.5)
    assert b.status == "idle"


def test_reports_full_and_empty():
    b = BESS({"soc_init_pct": 95, "soc_max_pct": 95, **QUIET})
    b.step(-100, DT)
    assert b.status == "full"
    b = BESS({"soc_init_pct": 10, "soc_min_pct": 10, **QUIET})
    b.step(100, DT)
    assert b.status == "empty"


def test_forced_modes_override_the_request():
    b = BESS({"mode": "charge", **QUIET})
    assert b.step(+150, DT) < 0
    b = BESS({"mode": "idle", **QUIET})
    assert b.step(+150, DT) == 0


def test_c_rate_and_snapshot():
    b = BESS({"capacity_kwh": 400, "pcs_rated_kw": 200, "pcs_eff_pct": 100, **QUIET})
    b.step(200, DT)
    s = b.snapshot()
    assert s["c_rate"] == pytest.approx(0.5)
    assert s["duration_h"] == pytest.approx(2)
    assert s["status"] == "discharging"
