"""Plant figures for the report: voltage, power, state of charge, power capping."""

import pytest

from dtpower.sims import bess_dr


def flow(p, label):
    return next(f for f in p["power"] if f["label"] == label)


def test_voltage_summary_counts_sags_and_outages():
    v = bess_dr.simulate("sag-storm")["plant"]["voltage"]
    assert v["sags"] == 4 and v["lowest_pct"] == 55
    assert v["below_90_s"] == pytest.approx((150 + 120 + 300 + 200) / 1000)
    assert v["outage_s"] == 0
    o = bess_dr.simulate("outage-gen")["plant"]["voltage"]
    assert o["outage_s"] == pytest.approx(20 * 60) and len(o["outages"]) == 1
    assert o["outages"][0]["clock_start"] == "14:00:00"


def test_power_flows_reconcile():
    r = bess_dr.simulate("nsw-spike")
    p = r["plant"]
    grid = flow(p, "Grid import (net)")
    assert grid["energy_kwh"] == pytest.approx(r["summary"]["import_kwh"] - r["summary"]["export_kwh"], rel=1e-6)
    assert grid["peak_kw"] == pytest.approx(r["summary"]["peak_import_kw"])
    dis = flow(p, "BESS discharge")
    assert dis["energy_kwh"] > 0 and dis["peak_at"] >= "14:00"
    # UPS input = output + losses - battery recharge (none here, battery full all day)
    ups_in, ups_out, ups_loss = flow(p, "UPS input"), flow(p, "UPS output"), flow(p, "UPS losses")
    assert ups_in["energy_kwh"] == pytest.approx(ups_out["energy_kwh"] + ups_loss["energy_kwh"], rel=1e-6)


def test_soc_summary():
    soc = {s["asset"]: s for s in bess_dr.simulate("sag-storm")["plant"]["soc"]}
    assert soc["UPS-1"]["start_pct"] == pytest.approx(100)
    assert soc["UPS-1"]["lowest_pct"] < 50 and soc["UPS-1"]["lowest_at"] > "14:06"
    assert soc["BESS-1"]["start_pct"] == pytest.approx(50)


def test_power_capping_periods():
    cap = bess_dr.simulate("nsw-spike-cap")["plant"]["capping"][0]
    assert cap["applied"] and cap["periods"]
    first = cap["periods"][0]
    assert first["clock_start"] == "14:00" and first["mean_price"] >= 300
    assert first["cut_peak_kw"] > 0 and first["lowest_throughput_pct"] < 100
    assert cap["curtailed_kwh"] > 0 and cap["work_lost_server_h"] > 0


def test_no_capping_is_reported_as_none():
    cap = bess_dr.simulate("nsw-spike")["plant"]["capping"][0]
    assert not cap["applied"] and cap["capped_steps"] == 0 and cap["periods"] == []
