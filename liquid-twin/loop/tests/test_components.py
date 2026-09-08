"""Hydraulic elements, each checked against the hand calculation it encodes."""

import math

import pytest

from dtloop import fluid
from dtloop.components import (
    KV_TO_K,
    M_LAM,
    Pipe,
    Pump,
    PumpCurve,
    Resistance,
    Valve,
)


# -- Resistance ----------------------------------------------------------

def test_resistance_reproduces_its_rating_point():
    r = Resistance.from_rating(dp_pa=60_000.0, m_dot=2.5)
    assert r.evaluate(2.5, 30.0)[0] == pytest.approx(60_000.0)


def test_resistance_is_quadratic_and_signed():
    r = Resistance.from_rating(60_000.0, 2.5)
    assert r.evaluate(5.0, 30.0)[0] == pytest.approx(4 * 60_000.0)
    # Reverse flow consumes pressure in the reverse direction, not the same one.
    assert r.evaluate(-2.5, 30.0)[0] == pytest.approx(-60_000.0)


def test_small_flow_linearisation_is_continuous_in_value():
    # The kink is in the derivative, by design. A discontinuity in the value
    # would make Newton oscillate across it; see the components.py docstring.
    r = Resistance(k=1000.0)
    just_below = r.evaluate(M_LAM * 0.999999, 30.0)[0]
    just_above = r.evaluate(M_LAM * 1.000001, 30.0)[0]
    assert just_below == pytest.approx(just_above, rel=1e-5)


def test_derivative_matches_finite_difference():
    r = Resistance(k=1000.0)
    m, eps = 3.0, 1e-6
    _, analytic = r.evaluate(m, 30.0)
    numeric = (r.evaluate(m + eps, 30.0)[0] - r.evaluate(m - eps, 30.0)[0]) / (2 * eps)
    assert analytic == pytest.approx(numeric, rel=1e-6)


# -- Pipe ----------------------------------------------------------------

def test_darcy_weisbach_against_hand_calculation():
    pipe = Pipe(length_m=50.0, diameter_m=0.1, roughness_m=4.5e-5)
    m, t = 10.0, 30.0
    f = pipe.friction_factor(m, t)
    rho = float(fluid.density(t))
    area = math.pi * 0.1**2 / 4
    v = m / (rho * area)
    expected = f * (50.0 / 0.1) * rho * v**2 / 2
    assert pipe.evaluate(m, t)[0] == pytest.approx(expected, rel=1e-12)


def test_cold_fluid_costs_more_pressure():
    # The reason viscosity is not a constant: same pipe, same mass flow.
    pipe = Pipe(length_m=50.0, diameter_m=0.1)
    cold = pipe.evaluate(10.0, 5.0)[0]
    warm = pipe.evaluate(10.0, 40.0)[0]
    assert cold > warm * 1.10, "cold-end penalty should be over 10%"


def test_friction_factor_regimes():
    pipe = Pipe(length_m=10.0, diameter_m=0.05)
    # Pick flows either side of the transition by targeting Reynolds directly.
    def m_for_re(re, t=30.0):
        return re * math.pi * 0.05 * float(fluid.viscosity(t)) / 4.0

    assert pipe.friction_factor(m_for_re(1000), 30.0) == pytest.approx(64 / 1000, rel=1e-6)
    turb = pipe.friction_factor(m_for_re(100_000), 30.0)
    assert 0.015 < turb < 0.03


def test_transition_is_continuous_at_both_seams():
    """What the solver needs across the transition is continuity, not monotonicity.

    Friction factor genuinely *rises* through transition - the Moody chart runs
    from about 0.028 at Re 2300 to about 0.042 at Re 4000 - so the blend climbs
    on purpose. What would hurt the solve is a step change in resistance between
    two Newton iterations, so that is what is checked here.
    """
    pipe = Pipe(length_m=10.0, diameter_m=0.05)

    def m_for_re(re, t=30.0):
        return re * math.pi * 0.05 * float(fluid.viscosity(t)) / 4.0

    def f(re):
        return pipe.friction_factor(m_for_re(re), 30.0)

    assert f(2299.9) == pytest.approx(f(2300.1), rel=1e-3)
    assert f(3999.9) == pytest.approx(f(4000.1), rel=1e-3)
    assert f(2300) == pytest.approx(64 / 2300, rel=1e-9)

    band = [f(re) for re in range(2300, 4001, 100)]
    assert all(a <= b for a, b in zip(band, band[1:])), band
    above = [f(re) for re in (4000, 6000, 10_000, 50_000)]
    assert all(a >= b for a, b in zip(above, above[1:])), above


def test_fittings_add_to_the_straight_run():
    bare = Pipe(length_m=10.0, diameter_m=0.05)
    fitted = Pipe(length_m=10.0, diameter_m=0.05, fittings_k=8.0)
    assert fitted.evaluate(2.0, 30.0)[0] > bare.evaluate(2.0, 30.0)[0]


def test_pipe_volume_is_used_by_phase_2():
    pipe = Pipe(length_m=10.0, diameter_m=0.1)
    assert pipe.volume_m3() == pytest.approx(math.pi * 0.05**2 * 10.0)


# -- Valve ---------------------------------------------------------------

def test_kv_conversion_against_the_vendor_definition():
    # Kv is m3/h at 1 bar. Check the constant by going back to that statement.
    kv, t = 100.0, 30.0
    valve = Valve(kv_rated=kv, characteristic="linear", position=1.0)
    m = 10.0
    dp_pa = valve.evaluate(m, t)[0]

    rho = float(fluid.density(t))
    q_m3h = m * 3600.0 / rho
    dp_bar_expected = (q_m3h / kv) ** 2 * (rho / 1000.0)
    assert dp_pa / 1e5 == pytest.approx(dp_bar_expected, rel=1e-12)
    assert KV_TO_K == pytest.approx(1.296e9, rel=1e-9)


def test_equal_percentage_characteristic():
    v = Valve(kv_rated=100.0, characteristic="equal_percentage", rangeability=50.0)
    assert v.kv() == pytest.approx(100.0)          # x = 1
    v.position = 0.5
    assert v.kv() == pytest.approx(100.0 * 50 ** -0.5)
    # Equal percentage means equal *fractional* change per unit lift.
    v.position = 0.4
    a = v.kv()
    v.position = 0.6
    b = v.kv()
    v.position = 0.8
    c = v.kv()
    assert b / a == pytest.approx(c / b, rel=1e-9)


def test_linear_characteristic_halves_kv_at_half_lift():
    v = Valve(kv_rated=100.0, characteristic="linear", position=0.5)
    assert v.kv() == pytest.approx(50.0)


def test_closed_valve_is_large_and_finite_never_infinite():
    # loop_params.json hydraulic.closed_valve_k carries the reasoning.
    v = Valve(kv_rated=100.0, position=0.0)
    assert v.is_closed
    k = v.k_at(30.0)
    assert math.isfinite(k)
    leak = math.sqrt(1e5 / k)  # flow under a 1 bar difference
    assert leak < 5e-3, f"a shut valve passing {leak} kg/s is not shut enough"


def test_unknown_characteristic_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown valve characteristic"):
        Valve(kv_rated=100.0, characteristic="s-curve")
    with pytest.raises(ValueError):
        Valve(kv_rated=0.0)


# -- Pump ----------------------------------------------------------------

def test_curve_interpolates_its_three_points_exactly():
    pts = [(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)]
    c = PumpCurve.from_points(pts)
    for q, h in pts:
        assert c.head_m(q) == pytest.approx(h, rel=1e-12)


def test_curve_needs_three_distinct_points():
    with pytest.raises(ValueError, match="exactly three"):
        PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0)])
    with pytest.raises(ValueError, match="distinct"):
        PumpCurve.from_points([(0.0, 50.0), (0.0, 45.0), (200.0, 25.0)])


def test_affinity_laws():
    # H ~ N^2 at the corresponding flow Q ~ N. Take a point on the full-speed
    # curve and check the half-speed curve passes through (Q/2, H/4).
    c = PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)])
    q, s = 120.0, 0.5
    assert c.head_m(q * s, s) == pytest.approx(c.head_m(q) * s * s, rel=1e-12)


def test_pump_produces_pressure_so_dp_is_negative():
    c = PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)])
    p = Pump(c)
    dp, _ = p.evaluate(10.0, 30.0)
    assert dp < 0, "a pump consuming pressure has its sign convention backwards"


def test_pump_head_converts_through_density_correctly():
    c = PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)])
    p = Pump(c)
    t, m = 30.0, 10.0
    rho = float(fluid.density(t))
    head = c.head_m(m * 3600.0 / rho)
    assert p.evaluate(m, t)[0] == pytest.approx(-rho * 9.80665 * head, rel=1e-12)


def test_pump_derivative_matches_finite_difference():
    c = PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)])
    p = Pump(c, speed=0.8)
    m, eps = 12.0, 1e-6
    _, analytic = p.evaluate(m, 30.0)
    numeric = (p.evaluate(m + eps, 30.0)[0] - p.evaluate(m - eps, 30.0)[0]) / (2 * eps)
    assert analytic == pytest.approx(numeric, rel=1e-6)


def test_running_past_runout_is_flagged():
    c = PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)])
    p = Pump(c, max_flow_m3h=200.0)
    assert not p.beyond_curve(20.0, 30.0)
    assert p.beyond_curve(80.0, 30.0)
