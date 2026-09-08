"""Section 5 - voltage drop, checked against the tabulated mV/A/m."""
import pytest

from dame_cable.schema import (SupportType, Cable, CableConstruction, ConductorMaterial,
                               InstallationArrangement, InstallationMethod,
                               Insulation, Load, Route, RouteSegment, SystemType)
from dame_cable.voltage_drop import (check_voltage_drop, cross_check_mv_per_a_m,
                                     mv_per_a_m, operating_temperature_c,
                                     resistance_at, voltage_drop)

SIZES = [4, 16, 50, 120, 240, 400]


def cable(size):
    return Cable(material=ConductorMaterial.COPPER,
                 insulation=Insulation.THERMOSETTING_90,
                 construction=CableConstruction.MULTICORE,
                 size_mm2=size, cores_loaded=3)


def method(ambient=40, **kw):
    return InstallationMethod(
        support_type=SupportType.NONE, arrangement=InstallationArrangement.AIR_TOUCHING,
        ambient_c=ambient, **kw)


def load(**kw):
    base = dict(design_current_a=100, system=SystemType.THREE_PHASE_AC,
                nominal_voltage_v=400, power_factor=0.9)
    base.update(kw)
    return Load(**base)


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("pf", [0.8, 0.9])
def test_agrees_with_tabulated_mv_per_a_m_within_1_percent(store, size, pf):
    """The headline verification: computed mV/A/m against the table's own."""
    result = cross_check_mv_per_a_m(store, cable(size), load(power_factor=pf), pf)
    assert result["relative_difference"] < 0.01, result


def test_resistance_temperature_correction_is_alpha20_not_interpolation(store):
    """R at 60 C is derived from the nearest tabulated row by the alpha-20
    correction, so it must sit on the alpha-20 line, not between table rows."""
    c = cable(50)
    r75 = resistance_at(store, c, 75)
    r60 = resistance_at(store, c, 60)
    a = 3.93e-3
    expected = r75 * (1 + a * (60 - 20)) / (1 + a * (75 - 20))
    assert r60 == pytest.approx(expected, rel=1e-12)


def test_drop_scales_with_length_and_current(store):
    c, l = cable(50), load()
    short = voltage_drop(store, c, Route.single(50, method()), l)
    long = voltage_drop(store, c, Route.single(150, method()), l)
    assert long.total_drop_v == pytest.approx(3 * short.total_drop_v, rel=1e-9)


def test_route_segments_sum(store):
    """Voltage drop accumulates over segments; a two-segment route of the same
    total length and the same ambient must match a single segment."""
    c, l = cable(50), load()
    one = voltage_drop(store, c, Route.single(120, method()), l)
    two = voltage_drop(store, c, Route([
        RouteSegment(40, method(), "riser"),
        RouteSegment(80, method(), "horizontal"),
    ]), l)
    assert two.total_drop_v == pytest.approx(one.total_drop_v, rel=1e-9)
    assert len(two.per_segment) == 2


def test_hotter_segment_has_higher_resistance(store):
    """Per-segment ambient must actually reach the resistance, under the
    load-dependent temperature refinement."""
    c, l = cable(50), load()
    route = Route([RouteSegment(50, method(ambient=25), "cool"),
                   RouteSegment(50, method(ambient=45), "hot")])
    res = voltage_drop(store, c, route, l,
                       operating_temperature_from_load=True, iz_a=150)
    cool, hot = res.per_segment
    assert hot.conductor_temperature_c > cool.conductor_temperature_c
    assert hot.r_ohm_per_km > cool.r_ohm_per_km


def test_operating_temperature_clamps_at_max():
    c = cable(50)
    assert operating_temperature_c(c, 40, 200, 100) == pytest.approx(90)
    assert operating_temperature_c(c, 40, 0.001, 100) == pytest.approx(40, abs=0.01)


def test_refinement_reduces_drop_at_part_load(store):
    """A half-loaded cable is not at 90 C, and the refinement should say so."""
    c, l = cable(120), load(design_current_a=100)
    route = Route.single(200, method(ambient=30))
    conservative = voltage_drop(store, c, route, l)
    refined = voltage_drop(store, c, route, l,
                           operating_temperature_from_load=True, iz_a=250)
    assert refined.total_drop_v < conservative.total_drop_v


def test_refinement_requires_iz(store):
    with pytest.raises(ValueError):
        voltage_drop(store, cable(50), Route.single(50, method()), load(),
                     operating_temperature_from_load=True)


def test_exact_method_adds_the_quadrature_term(store):
    c, l = cable(16), load(design_current_a=60)
    route = Route.single(300, method())
    approx = voltage_drop(store, c, route, l)
    exact = voltage_drop(store, c, route, l, exact=True)
    assert exact.total_drop_v > approx.total_drop_v
    assert exact.total_drop_v == pytest.approx(approx.total_drop_v, rel=0.05)


def test_single_phase_uses_factor_two():
    assert mv_per_a_m(1.0, 0.0, SystemType.SINGLE_PHASE_AC, 1.0) == pytest.approx(2.0)
    assert mv_per_a_m(1.0, 0.0, SystemType.THREE_PHASE_AC, 1.0) == pytest.approx(3 ** 0.5)


def test_dc_ignores_reactance():
    assert mv_per_a_m(1.0, 5.0, SystemType.DC, 1.0) == pytest.approx(2.0)


def test_check_uses_the_declared_limit(store):
    c = cable(4)
    l = load(design_current_a=30, max_voltage_drop_fraction=0.05)
    res = voltage_drop(store, c, Route.single(400, method()), l)
    check = check_voltage_drop(res, l)
    assert check.limit == pytest.approx(20.0)
    assert check.passed == (res.total_drop_v <= 20.0)
