import pytest

from dtpower.components import GPUServerLoad
from dtpower.components.gpu_load import SERVERS, profile_factor

DT = 5 / 60


def test_linear_between_idle_and_max():
    g = GPUServerLoad({"server": "dgx-h100", "count": 10, "utilisation_pct": 0})
    assert g.step(12, DT) == pytest.approx(10 * SERVERS["dgx-h100"]["idle_kw"])
    g = GPUServerLoad({"server": "dgx-h100", "count": 10, "utilisation_pct": 100})
    assert g.step(12, DT) == pytest.approx(102)


def test_fixed_cap_clamps_power_and_costs_throughput():
    g = GPUServerLoad({"count": 10, "utilisation_pct": 100, "cap_enabled": True, "cap_pct": 70, "cap_trigger": "always"})
    assert g.step(12, DT) == pytest.approx(0.7 * 102)
    assert g.capped
    assert 70 < g.throughput_pct < 100
    assert g.curtailed_kwh == pytest.approx((102 - 71.4) * DT)


def test_price_triggered_cap_only_above_threshold():
    g = GPUServerLoad({"count": 10, "utilisation_pct": 100, "cap_enabled": True, "cap_trigger": "price", "cap_price": 300})
    assert g.step(12, DT, price=100) == pytest.approx(102)
    assert g.step(12, DT, price=300) < 102


def test_cap_never_below_idle():
    g = GPUServerLoad({"count": 1, "utilisation_pct": 100, "cap_enabled": True, "cap_pct": 20})
    assert g.step(0, DT) == pytest.approx(SERVERS["dgx-h100"]["idle_kw"])


@pytest.mark.parametrize("profile", ["constant", "training", "inference", "overnight-batch", "bursty"])
def test_profiles_stay_in_unit_interval(profile):
    for i in range(24 * 12):
        assert 0 <= profile_factor(profile, i * DT) <= 1


@pytest.mark.parametrize("server,max_kw", [("dgx-b300", 14.5), ("vr200-nvl72-maxq", 190.0), ("vr200-nvl72-maxp", 230.0)])
def test_newer_servers_reach_their_rated_maximum(server, max_kw):
    g = GPUServerLoad({"server": server, "count": 2, "utilisation_pct": 100})
    assert g.step(12, DT) == pytest.approx(2 * max_kw)
    assert SERVERS[server]["provenance"]["verified"] is False


def test_vera_rubin_profiles_share_hardware():
    """Max-Q and Max-P are power profiles on one rack: same idle, lower ceiling."""
    q, p = SERVERS["vr200-nvl72-maxq"], SERVERS["vr200-nvl72-maxp"]
    assert q["idle_kw"] == p["idle_kw"] and q["max_kw"] < p["max_kw"]
