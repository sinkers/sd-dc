import pytest

from dtpower.components import UPS

DT = 1 / 60


def test_efficiency_curve_shape():
    u = UPS({"rated_kw": 250, "topology": "double-conversion"})
    full = 250 / (250 + u.loss_kw_at(250))
    quarter = 62.5 / (62.5 + u.loss_kw_at(62.5))
    assert 0.955 < full < 0.97
    assert 0.93 < quarter < full
    eco = UPS({"rated_kw": 250, "topology": "eco"})
    assert 250 / (250 + eco.loss_kw_at(250)) > 0.985


def test_online_draws_load_plus_losses():
    u = UPS({"rated_kw": 250, "soc_init_pct": 100})
    assert u.step(150, DT) == pytest.approx(150 + u.loss_kw_at(150))
    assert u.status == "online"


def test_recharges_after_discharge():
    u = UPS({"rated_kw": 250, "soc_init_pct": 50, "recharge_pct": 10})
    assert u.step(150, DT) == pytest.approx(150 + u.loss_kw_at(150) + 25)


def test_rides_through_then_drops_load():
    u = UPS({"rated_kw": 250, "capacity_kwh": 45, "soc_init_pct": 100})
    expected = u.autonomy_min(150)
    minutes = 0
    while u.step(150, DT, grid_up=False) == 0 and u.status == "on battery":
        minutes += 1
        assert u.output_kw == 150
        assert minutes < 120
    assert u.status == "load dropped"
    assert minutes == pytest.approx(expected, abs=1.01)
    assert u.unserved_kw == 150


def test_overload_goes_to_bypass():
    u = UPS({"rated_kw": 100})
    u.step(130, DT)
    assert u.status == "bypass"
    u.step(130, DT, grid_up=False)
    assert u.status == "load dropped"
