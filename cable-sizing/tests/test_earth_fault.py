"""Section 7 - PE sizing and earth fault loop impedance."""
import pytest

from dame_cable.earth_fault import check, loop_impedance_ohm, pe_minimum_size
from dame_cable.errors import OpenItem
from dame_cable.schema import (SupportType, Cable, CableConstruction, ConductorMaterial,
                               DeviceType, InstallationArrangement,
                               InstallationMethod, Insulation, Load, Protection,
                               Route, RouteSegment, SystemType)
from dame_cable.select_conductor import select

Cu = ConductorMaterial.COPPER


def cable(size=95, pe=None):
    return Cable(material=Cu, insulation=Insulation.THERMOSETTING_90,
                 construction=CableConstruction.MULTICORE, size_mm2=size,
                 cores_loaded=3, pe_size_mm2=pe, pe_material=Cu)


def air(ambient=40, **kw):
    return InstallationMethod(
        support_type=SupportType.NONE, arrangement=InstallationArrangement.AIR_TOUCHING,
        ambient_c=ambient, **kw)


def protection(**kw):
    base = dict(device=DeviceType.MCB_C, rating_a=100,
                prospective_fault_current_a=6000, clearing_time_s=0.1,
                max_disconnection_time_s=0.4)
    base.update(kw)
    return Protection(**base)


def test_pe_size_is_the_larger_of_table_and_adiabatic(store):
    """Both obligations bind; satisfying one is not enough."""
    small_fault = pe_minimum_size(store, cable(240), protection(
        prospective_fault_current_a=2000, clearing_time_s=0.05))
    assert small_fault.governing_mm2 == small_fault.table_minimum_mm2
    assert small_fault.table_minimum_mm2 > small_fault.adiabatic_minimum_mm2

    big_fault = pe_minimum_size(store, cable(16), protection(
        prospective_fault_current_a=30000, clearing_time_s=0.4))
    assert big_fault.governing_mm2 == big_fault.adiabatic_minimum_mm2
    assert big_fault.adiabatic_minimum_mm2 > big_fault.table_minimum_mm2


def test_loop_impedance_requires_a_pe_size(store):
    with pytest.raises(OpenItem, match="protective earthing conductor"):
        loop_impedance_ohm(store, cable(95, pe=None),
                           Route.single(50, air()), protection())


def test_loop_impedance_grows_with_length(store):
    short = loop_impedance_ohm(store, cable(95, pe=50),
                               Route.single(50, air()), protection())
    long = loop_impedance_ohm(store, cable(95, pe=50),
                              Route.single(200, air()), protection())
    assert long["z_circuit_ohm"] == pytest.approx(4 * short["z_circuit_ohm"], rel=1e-9)
    assert long["z_s_ohm"] > long["z_circuit_ohm"] - 1e-12


def test_external_impedance_is_included(store):
    with_ext = loop_impedance_ohm(store, cable(95, pe=50),
                                  Route.single(50, air()),
                                  protection(external_loop_impedance_ohm=0.1))
    assert with_ext["z_s_ohm"] == pytest.approx(with_ext["z_circuit_ohm"] + 0.1)


def test_hot_conductor_gives_a_higher_loop_impedance(store):
    cold = loop_impedance_ohm(store, cable(95, pe=50), Route.single(80, air()),
                              protection(), loop_temperature_c=20)
    hot = loop_impedance_ohm(store, cable(95, pe=50), Route.single(80, air()),
                             protection(), loop_temperature_c=90)
    assert hot["z_s_ohm"] > cold["z_s_ohm"]


def test_tabulated_max_zs_is_preferred_over_u0_over_ia(store):
    res = check(store, cable(95, pe=50), Route.single(30, air()), protection(),
                u0_v=230, disconnection_current_a=10)
    assert "maximum Z_s table" in res.detail["basis"]
    assert res.limit == pytest.approx(0.23)


def test_falls_back_to_u0_over_ia_when_the_table_is_silent(store):
    res = check(store, cable(95, pe=50), Route.single(30, air()),
                protection(device=DeviceType.MCCB, rating_a=250),
                u0_v=230, disconnection_current_a=2000)
    assert res.limit == pytest.approx(230 / 2000)


def test_no_basis_at_all_is_an_open_item(store):
    with pytest.raises(OpenItem, match="No default"):
        check(store, cable(95, pe=50), Route.single(30, air()),
              protection(device=DeviceType.MCCB, rating_a=250), u0_v=230)


def test_selection_iterates_active_size_for_loop_impedance(store):
    """A long run can be driven by Z_s rather than by capacity or drop."""
    load = Load(design_current_a=60, system=SystemType.THREE_PHASE_AC,
                nominal_voltage_v=400, power_factor=0.9,
                max_voltage_drop_fraction=0.20)
    sel = select(store, cable(4), Route.single(150, air()),
                 load, protection(rating_a=63),
                 u0_v=230, disconnection_current_a=2000)
    step8 = [s for s in sel.steps if s.number == 8][0]
    assert step8.demanded_size_mm2 is not None
    assert "z_s_ohm" in step8.detail
    assert step8.detail["z_s_ohm"] <= step8.detail["max_zs_ohm"]
