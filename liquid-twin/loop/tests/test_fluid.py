"""PG25 properties. The tests that matter are about viscosity, because it is
the property a constant-property model gets wrong and the one that decides
cold-end pressure drop."""

import pytest

from dtloop import fluid


def test_tabulated_points_are_reproduced_exactly():
    # The fit is a cubic through four points, so it interpolates them exactly.
    # If this drifts, someone has changed the table without meaning to.
    assert fluid.density(0) == pytest.approx(1030.0, abs=1e-9)
    assert fluid.density(60) == pytest.approx(1004.0, abs=1e-9)
    assert fluid.viscosity(0) == pytest.approx(4.60e-3, abs=1e-12)
    assert fluid.viscosity(40) == pytest.approx(1.35e-3, abs=1e-12)
    assert fluid.cp(20) == pytest.approx(3850.0, abs=1e-9)


def test_viscosity_falls_monotonically_and_by_a_factor_of_five():
    temps = list(range(0, 61, 5))
    mus = [fluid.viscosity(t) for t in temps]
    assert all(a > b for a, b in zip(mus, mus[1:])), "viscosity must fall with temperature"
    assert fluid.viscosity(0) / fluid.viscosity(60) == pytest.approx(5.0, rel=0.05)


def test_density_falls_and_cp_rises_with_temperature():
    assert fluid.density(0) > fluid.density(60)
    assert fluid.cp(0) < fluid.cp(60)


def test_properties_are_clamped_not_extrapolated():
    # A cubic extrapolates viscosity to nonsense - negative within a few degrees
    # past the table. Clamping is the deliberate choice; see fluid.py.
    assert fluid.viscosity(-40) == fluid.viscosity(0)
    assert fluid.viscosity(200) == fluid.viscosity(60)
    assert fluid.density(200) > 0


def test_reynolds_is_independent_of_density():
    # Re = 4*m/(pi*D*mu) has no rho in it once written in terms of mass flow.
    re = fluid.reynolds(10.0, 0.1, 30.0)
    expected = 4 * 10.0 / (3.141592653589793 * 0.1 * fluid.viscosity(30.0))
    assert re == pytest.approx(expected, rel=1e-12)


def test_flow_and_duty_round_trip():
    m = fluid.mass_flow_kgs(50.0, 35.0)
    assert fluid.volumetric_m3h(m, 35.0) == pytest.approx(50.0, rel=1e-12)

    m2 = fluid.flow_for_duty(68_000.0, 10.0, 35.0)
    assert fluid.duty_kw(m2, 10.0, 35.0) == pytest.approx(68.0, rel=1e-12)


def test_zero_delta_t_is_refused():
    with pytest.raises(ValueError):
        fluid.flow_for_duty(1000.0, 0.0, 30.0)
