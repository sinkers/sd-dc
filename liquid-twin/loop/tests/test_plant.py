"""The plant: layout joined to solver, and what the solved flows imply.

Where SPEC.md section 9 gets checked rather than asserted - the pipes drawn in
the review model are the pipes the solver puts flow through.
"""

import pytest

from dtloop.components import CheckValve, Pump
from dtloop.layout import (
    DN_CHILLER_BRANCH,
    DN_FACILITY_MAIN,
    DN_TCS_HEADER,
    V_MAX,
    build_layout,
    size_dn,
)
from dtloop.plant import (
    CHILLERS_RUNNING,
    LOOP_DELTA_T,
    RACK_COUNT,
    build_circuits,
    electrical_balance,
    facility_flow_kgs,
    heat_balance,
    pod_flow_kgs,
    rack_flow_kgs,
    report,
    run_scenarios,
    size_pumps,
    solve_circuit,
)


@pytest.fixture(scope="module")
def solved():
    lay = build_layout()
    circuits = build_circuits(lay)
    for c in circuits.values():
        size_pumps(c)
    sols = {n: solve_circuit(c) for n, c in circuits.items()}
    return circuits, sols


# -- structure -----------------------------------------------------------

def test_four_independent_circuits(solved):
    """Facility plus one per pod. They meet across the CDU plates, thermally.

    Not one network: four disconnected circuits in a single network leave three
    pressure levels undetermined, and the solver refuses it - correctly.
    """
    circuits, _ = solved
    assert set(circuits) == {"facility", "pod1", "pod2", "pod3"}
    for c in circuits.values():
        assert c.network.validate() == []


def test_every_branch_is_either_a_drawn_segment_or_runs_through_equipment(solved):
    circuits, _ = solved
    lay = build_layout()
    drawn = {s.name for s in lay.segments}
    for c in circuits.values():
        for br in c.network.branches:
            if br.name in drawn:
                assert c.segment_of_branch[br.name] == br.name
            else:
                # The ones with no centreline: plates, cold plates, pumps, units.
                assert any(k in br.name for k in
                           ("_PLATE_", "_COLDPLATE", "_UNIT")), br.name


def test_pumps_have_their_own_branches(solved):
    """So each can report its own suction and discharge, which a pump bolted
    onto someone else's branch cannot."""
    circuits, _ = solved
    fac = circuits["facility"]
    assert fac.pump_branches == [f"CWP-{i}_UNIT" for i in range(1, CHILLERS_RUNNING + 1)]
    for name in fac.pump_branches:
        br = fac.network.branch(name)
        assert br.from_node.startswith("pump")
        assert br.to_node.startswith("pump")
        assert len(br.pumps()) == 1


def test_pump_branches_carry_non_return_valves(solved):
    """Added because the solver found the reason for them - see test below."""
    circuits, _ = solved
    for c in circuits.values():
        for name in c.pump_branches:
            assert any(isinstance(e, CheckValve) for e in c.network.branch(name).elements), name


def test_one_flow_meter_per_cdu_per_side(solved):
    circuits, _ = solved
    fac = sorted(circuits["facility"].meters)
    tcs = sorted(t for c in circuits.values() for t in c.meters if t.startswith("FM-T"))
    assert len(fac) == 9 and all(t.startswith("FM-F") for t in fac)
    assert len(tcs) == 9


# -- pipe sizing ---------------------------------------------------------

def test_pipes_are_sized_on_velocity_not_on_one_drawing_callout():
    """The error the flow display caught.

    RD110_3.2's only DN callout is DN150. Applying it to the facility mains as
    well as the branches put 540 m3/h through them at 8.5 m/s - four times the
    design velocity that was already sitting in loop_params.json, unused.
    """
    assert DN_FACILITY_MAIN == 300, "the mains carry the whole plant flow"
    assert DN_CHILLER_BRANCH == 150, "RD110's callout is right for a branch"
    assert DN_TCS_HEADER == 150


def test_size_dn_picks_the_smallest_ladder_size_that_fits():
    import math
    for q in (0.01, 0.05, 0.15, 0.4):
        dn = size_dn(q)
        area = math.pi * (dn / 1000.0) ** 2 / 4.0
        assert q / area <= V_MAX
        # And it is the smallest such size: one step down would exceed.
        from dtloop.layout import DN_LADDER
        i = DN_LADDER.index(dn)
        if i:
            smaller = math.pi * (DN_LADDER[i - 1] / 1000.0) ** 2 / 4.0
            assert q / smaller > V_MAX


def test_no_branch_exceeds_the_velocity_limit(solved):
    """The regression guard. If a size or a duty changes, this fails first."""
    circuits, sols = solved
    for name, c in circuits.items():
        r = report(c, sols[name])
        assert r["over_velocity"] == [], f"{name}: {r['over_velocity']}"
        assert r["max_velocity_ms"] <= V_MAX


# -- design point --------------------------------------------------------

def test_design_flows_follow_from_the_duty_and_the_ten_kelvin_rise():
    per_rack = rack_flow_kgs()
    assert pod_flow_kgs() == pytest.approx(per_rack * 16)
    assert facility_flow_kgs() == pytest.approx(
        rack_flow_kgs(37.0) * RACK_COUNT, rel=0.02)


def test_pumps_land_on_design_flow_because_they_were_sized_to_it(solved):
    circuits, sols = solved
    for name, c in circuits.items():
        r = report(c, sols[name])
        assert r["total_flow_kgs"] == pytest.approx(c.design_flow_kgs, rel=0.02)


def test_meters_sum_to_the_circuit_flow(solved):
    circuits, sols = solved
    for name, c in circuits.items():
        r = report(c, sols[name])
        meters = [m["m_dot_kgs"] for t, m in r["meters"].items()]
        if not meters:
            continue
        assert sum(meters) == pytest.approx(r["total_flow_kgs"], rel=0.02)


def test_pumps_raise_pressure_and_report_both_sides(solved):
    circuits, sols = solved
    r = report(circuits["facility"], sols["facility"])
    for p in r["pumps"].values():
        assert p["discharge_kpa"] > p["suction_kpa"]
        assert p["head_kpa"] == pytest.approx(p["discharge_kpa"] - p["suction_kpa"], abs=0.2)
        assert p["shaft_kw"] > 0


# -- electrical load to heat to liquid -----------------------------------

def test_all_the_electrical_load_becomes_heat_and_the_split_is_only_routing():
    e = electrical_balance()
    assert e["to_liquid_kw"] + e["to_air_kw"] == pytest.approx(e["it_electrical_kw"])
    # 87 % of the AI racks, so under 87 % of total IT - the networking racks are
    # entirely on the air side.
    assert e["liquid_share"] < 0.87
    assert e["liquid_share"] == pytest.approx(0.787, abs=0.005)


def test_the_liquid_carries_exactly_what_was_routed_to_it(solved):
    circuits, sols = solved
    h = heat_balance(circuits, sols)
    assert h["carried_by_liquid_kw"] == pytest.approx(h["electrical"]["to_liquid_kw"], rel=1e-3)


def test_chillers_reject_the_load_plus_the_pumping_that_moved_it(solved):
    """Not a rounding error: the pumps put their work into the fluid, so a plant
    sized on the IT load alone is short by it."""
    circuits, sols = solved
    h = heat_balance(circuits, sols)
    assert h["pump_hydraulic_kw"] > 0
    assert h["rejected_at_chillers_kw"] == pytest.approx(
        h["carried_by_liquid_kw"] + h["pump_hydraulic_kw"], rel=1e-6)
    assert h["pump_shaft_kw"] > h["pump_hydraulic_kw"]  # efficiency


def test_at_design_flow_every_rack_gets_the_design_rise(solved):
    circuits, sols = solved
    h = heat_balance(circuits, sols)
    assert len(h["racks"]) == RACK_COUNT
    for name, r in h["racks"].items():
        assert not r["starved"]
        assert r["delta_t_k"] == pytest.approx(LOOP_DELTA_T, abs=0.5), name
    assert h["verdict"] == "PASS"


# -- scenarios -----------------------------------------------------------

@pytest.fixture(scope="module")
def scenarios():
    return {s["key"]: s for s in run_scenarios()}


def test_shutting_a_rack_valve_starves_that_rack_and_feeds_the_others(scenarios):
    base, shut = scenarios["design"], scenarios["rack_valve_shut"]
    hb, hs = base["heat"], shut["heat"]

    assert hs["verdict"] == "FAIL"
    assert hs["starved_racks"] == ["P1A01"]
    # Its neighbours in the same pod gain; another pod is untouched.
    assert hs["racks"]["P1A02"]["m_dot_kgs"] > hb["racks"]["P1A02"]["m_dot_kgs"]
    assert hs["racks"]["P2A01"]["m_dot_kgs"] == pytest.approx(
        hb["racks"]["P2A01"]["m_dot_kgs"], rel=1e-6)

    # The pod loses flow overall, but less than the one-sixteenth removed.
    lost = 1 - shut["circuits"]["pod1"]["total_flow_kgs"] / base["circuits"]["pod1"]["total_flow_kgs"]
    assert 0 < lost < 1 / 16


def test_a_starved_rack_reports_no_temperature_rather_than_a_wrong_one(scenarios):
    """dT = Q/(m*cp) goes to infinity as flow goes to zero. It once printed
    6,820 K, which is arithmetically correct and useless: there is no steady
    state, because the rack is heating up rather than settling."""
    r = scenarios["rack_valve_shut"]["heat"]["racks"]["P1A01"]
    assert r["starved"]
    assert r["delta_t_k"] is None
    assert r["outlet_c"] is None


def test_half_lift_on_an_equal_percentage_valve_still_overheats_the_rack(scenarios):
    r = scenarios["rack_valve_half"]["heat"]["racks"]["P1A01"]
    assert not r["starved"]
    assert 0.2 < r["flow_fraction"] < 0.4, "half lift is not half flow"
    assert r["over_limit"]
    assert scenarios["rack_valve_half"]["heat"]["verdict"] == "FAIL"


def test_a_tripped_cdu_does_not_backflow(scenarios):
    """The reason CheckValve exists.

    With the pump stopped and no non-return valve, the network drove flow
    backwards through the dead plate - FM-T01 read minus 62 m3/h - and the pod's
    apparent total went *up*, because two working CDUs were short-circuiting
    through the third.
    """
    s = scenarios["cdu_trip"]
    fm = None
    for c in s["circuits"].values():
        if "FM-T01" in c["meters"]:
            fm = c["meters"]["FM-T01"]
    assert fm is not None
    assert fm["q_m3h"] > -1.0, "backflow through a stopped CDU"
    assert abs(fm["q_m3h"]) < 5.0, "a stopped CDU should pass ~nothing"
    # And the pod loses flow, rather than gaining it.
    assert s["circuits"]["pod1"]["total_flow_kgs"] < scenarios["design"]["circuits"]["pod1"]["total_flow_kgs"]


def test_losing_a_pump_reduces_total_flow_and_unbalances_the_survivors(scenarios):
    """Reported as a sum of the pumps, never one pump times their count.

    The shortcut said 193 kg/s against a 152 kg/s design - a rise, on losing a
    pump - because the survivors ride up their curves.
    """
    base, trip = scenarios["design"], scenarios["cwp_trip"]
    f0, f1 = base["circuits"]["facility"], trip["circuits"]["facility"]
    assert f1["total_flow_kgs"] < f0["total_flow_kgs"]
    assert f0["pump_flow_spread"] == pytest.approx(0.0, abs=0.5)
    assert f1["pump_flow_spread"] > 5.0, "one pump off, the others are not sharing"


def test_pump_turndown_follows_the_affinity_laws(scenarios):
    """Flow with speed, power with its cube. The reason for the drive."""
    base, turn = scenarios["design"], scenarios["cwp_turndown"]
    s = 0.8
    f0 = base["circuits"]["facility"]["total_flow_kgs"]
    f1 = turn["circuits"]["facility"]["total_flow_kgs"]
    assert f1 / f0 == pytest.approx(s, rel=0.05)
    assert turn["heat"]["pump_shaft_kw"] / base["heat"]["pump_shaft_kw"] == pytest.approx(
        s ** 3, rel=0.15)


def test_every_scenario_converges(scenarios):
    for key, s in scenarios.items():
        for name, c in s["circuits"].items():
            assert c["converged"], f"{key}/{name} did not converge"
