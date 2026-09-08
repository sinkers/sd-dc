"""Capacity over a route, and the nine-step orchestrator."""
import pytest

from dame_cable.current_capacity import capacity, check_capacity
from dame_cable.errors import InvalidDeclaration
from dame_cable.schema import (SupportType, Cable, CableConstruction, ConductorMaterial,
                               DeviceType, InstallationArrangement,
                               InstallationMethod, Insulation, Load, Protection,
                               Route, RouteSegment, SystemType)
from dame_cable.select_conductor import select


def cable(size=50, **kw):
    return Cable(material=ConductorMaterial.COPPER,
                 insulation=Insulation.THERMOSETTING_90,
                 construction=CableConstruction.MULTICORE,
                 size_mm2=size, cores_loaded=3, **kw)


def air(ambient=40, **kw):
    return InstallationMethod(
        support_type=SupportType.NONE, arrangement=InstallationArrangement.AIR_TOUCHING,
        ambient_c=ambient, **kw)


def load(**kw):
    base = dict(design_current_a=200, system=SystemType.THREE_PHASE_AC,
                nominal_voltage_v=400, power_factor=0.9)
    base.update(kw)
    return Load(**base)


def protection(**kw):
    base = dict(device=DeviceType.MCB_C, rating_a=250,
                prospective_fault_current_a=10000, clearing_time_s=0.1)
    base.update(kw)
    return Protection(**base)


# -- capacity is set by the worst segment ----------------------------------

def test_worst_segment_governs_capacity(store):
    route = Route([
        RouteSegment(30, air(25), "cool switchroom"),
        RouteSegment(10, air(45, circuits_in_group=6), "hot congested tray"),
    ])
    res = capacity(store, cable(120), route, load())
    assert res.governing.segment.label == "hot congested tray"
    assert res.iz_a == pytest.approx(res.governing.capacity_a)
    assert res.iz_a < res.per_segment[0].capacity_a


def test_length_does_not_affect_capacity(store):
    short = capacity(store, cable(120), Route.single(5, air()), load())
    long = capacity(store, cable(120), Route.single(500, air()), load())
    assert short.iz_a == pytest.approx(long.iz_a)


def test_parallel_sets_multiply_capacity_but_demand_correct_grouping(store):
    with pytest.raises(InvalidDeclaration, match="parallel"):
        capacity(store, cable(120, parallel_sets=2),
                 Route.single(50, air(circuits_in_group=1)), load())

    res = capacity(store, cable(120, parallel_sets=2),
                   Route.single(50, air(circuits_in_group=2)), load())
    single = capacity(store, cable(120),
                      Route.single(50, air(circuits_in_group=2)), load())
    assert res.iz_a == pytest.approx(2 * single.iz_a)


def test_capacity_chain_compares_the_right_current_under_harmonics(store):
    """On a neutral basis the I_b <= I_n check must use the neutral current."""
    l = load(design_current_a=100, third_harmonic_fraction=0.40)
    res = capacity(store, cable(120), Route.single(50, air()), l)
    checks = check_capacity(res, l, protection(rating_a=125))
    ib_check = checks[0]
    assert "neutral" in ib_check.name
    assert ib_check.governing_value == pytest.approx(res.harmonic.neutral_a)
    assert ib_check.governing_value > l.design_current_a


def test_overload_rule_applied_when_i2_supplied(store):
    l = load()
    res = capacity(store, cable(240), Route.single(50, air()), l)
    checks = check_capacity(res, l, protection(fusing_current_a=1.6 * res.iz_a))
    overload = [c for c in checks if "1.45" in c.name][0]
    assert not overload.passed


# -- the orchestrator -------------------------------------------------------

def test_select_returns_the_largest_demand(store):
    """A long route makes voltage drop, not capacity, the governing step."""
    sel = select(store, cable(), Route.single(400, air()), load(), protection())
    assert sel.final_size_mm2 is not None
    demands = {s.number: s.demanded_size_mm2 for s in sel.steps if s.demanded_size_mm2}
    assert sel.final_size_mm2 == max(demands.values())
    assert sel.governing_step.number == 6          # voltage drop
    assert demands[6] > demands[5]


def test_short_route_is_governed_by_capacity(store):
    sel = select(store, cable(), Route.single(10, air()), load(), protection())
    assert sel.governing_step.number == 5


def test_final_checks_are_run_at_the_final_size(store):
    sel = select(store, cable(), Route.single(400, air()), load(), protection())
    assert sel.cable.size_mm2 == sel.final_size_mm2
    vd = [c for c in sel.checks if c.name == "voltage drop"][0]
    assert vd.passed
    iz = [c for c in sel.checks if c.name == "I_n <= I_z"][0]
    assert iz.passed


def test_report_renders(store):
    sel = select(store, cable(), Route.single(400, air()), load(), protection())
    text = sel.report()
    assert "Governing size" in text
    assert "voltage drop" in text


def test_harmonic_open_item_stops_the_run_at_step_2(tmp_path):
    """Everything transcribed except Table 3.4, and a data centre load with
    real triplen content. The run must stop and say so rather than quietly
    sizing on the phase current."""
    import shutil
    from pathlib import Path as _P
    from dame_cable.tables.registry import TableStore

    src = _P(__file__).parent / "fixtures"
    for f in src.glob("*.csv"):
        if f.name != "cf_harmonic.csv":
            shutil.copy(f, tmp_path / f.name)
    partial = TableStore.load(tmp_path)

    sel = select(partial, cable(), Route.single(50, air()),
                 load(third_harmonic_fraction=0.3), protection())
    assert sel.final_size_mm2 is None
    assert not sel.compliant
    assert any("Table 3.4" in o for o in sel.open_items)
    step2 = [s for s in sel.steps if s.number == 2][0]
    assert not step2.passed


def test_multi_segment_route_end_to_end(store):
    route = Route([
        RouteSegment(25, air(45, circuits_in_group=4), "plant room riser"),
        RouteSegment(180, air(30), "ceiling tray"),
        RouteSegment(40, InstallationMethod(
            support_type=SupportType.NONE, arrangement=InstallationArrangement.BURIED_DIRECT, ambient_c=25,
            depth_of_burial_m=0.8, soil_thermal_resistivity_km_w=1.2),
            "site crossing"),
    ])
    sel = select(store, cable(), route, load(), protection())
    assert sel.steps[3].number == 4
    assert len(sel.steps[3].detail["segments"]) == 3
    assert sel.final_size_mm2 is not None
    cap_step = [s for s in sel.steps if s.number == 5][0]
    assert cap_step.passed


def test_missing_ccc_rows_for_a_segment_is_an_open_item_not_a_crash(store):
    """A route that crosses into an arrangement with no transcribed table must
    stop at step 1 naming the segment, not fail three modules later."""
    route = Route([
        RouteSegment(20, air(), "tray"),
        RouteSegment(20, InstallationMethod(
            support_type=SupportType.NONE, arrangement=InstallationArrangement.INSULATION_PARTIAL,
            ambient_c=40), "through insulation"),
    ])
    sel = select(store, cable(), route, load(), protection())
    assert sel.final_size_mm2 is None
    assert not sel.compliant
    assert any("through insulation" in o for o in sel.open_items)
