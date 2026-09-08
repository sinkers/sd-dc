"""Effectiveness-NTU, and the two temperature differences that are easy to confuse."""

import math

import pytest

from dtloop.hx import (
    CR_UNITY_TOL,
    FLOW_EXPONENT,
    PlateExchanger,
    effectiveness,
    ntu_for_effectiveness,
)
from dtloop.plant import cdu_plate, design_cdu_flows, hx_model


# -- the relations -------------------------------------------------------

def test_effectiveness_limits():
    # Cr -> 0: one side isothermal, the classic 1 - exp(-NTU).
    assert effectiveness(2.0, 0.0) == pytest.approx(1 - math.exp(-2.0))
    # Cr -> 1: NTU/(1+NTU), the case a matched plate actually sits in.
    assert effectiveness(3.0, 1.0) == pytest.approx(0.75)
    assert effectiveness(0.0, 0.5) == 0.0


def test_effectiveness_is_continuous_across_the_cr_unity_special_case():
    """The general expression is 0/0 at Cr = 1, so it is special-cased. Check the
    seam rather than trusting it."""
    ntu = 2.5
    just_below = effectiveness(ntu, 1.0 - CR_UNITY_TOL * 10)
    at_one = effectiveness(ntu, 1.0)
    assert just_below == pytest.approx(at_one, rel=1e-3)


def test_effectiveness_rises_with_ntu_and_falls_with_cr():
    assert effectiveness(1.0, 0.9) < effectiveness(3.0, 0.9)
    assert effectiveness(3.0, 0.2) > effectiveness(3.0, 0.9)


def test_ntu_inverts_effectiveness():
    for cr in (0.0, 0.3, 0.7, 1.0):
        for eps in (0.2, 0.5, 0.77):
            ntu = ntu_for_effectiveness(eps, cr)
            assert effectiveness(ntu, cr) == pytest.approx(eps, rel=1e-9)


def test_effectiveness_of_one_or_more_is_refused():
    with pytest.raises(ValueError, match="between 0 and 1"):
        ntu_for_effectiveness(1.0, 0.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        ntu_for_effectiveness(0.0, 0.5)


def test_high_effectiveness_is_reachable_in_counterflow_just_expensively():
    """Counterflow eps tends to 1 as NTU grows, for any Cr below 1 - so 0.99 is
    reachable and merely needs 24 transfer units. It is Cr = 1 that caps eps,
    at NTU/(1+NTU), and that is the case a matched plate sits in."""
    assert ntu_for_effectiveness(0.99, 0.9) > 20
    assert effectiveness(24.0, 0.9) == pytest.approx(0.99, abs=0.01)
    # At Cr = 1 the same effectiveness needs 99 transfer units.
    assert ntu_for_effectiveness(0.99, 1.0) == pytest.approx(99.0, rel=1e-6)


# -- calibration ---------------------------------------------------------

def test_the_plate_reproduces_rd110s_four_temperatures():
    """Calibrated from them, so this is a closure check rather than a fit."""
    plate = cdu_plate()
    hot, cold = design_cdu_flows()
    s = plate.state(hot, cold)

    # eps = (50-40)/(50-37) = 10/13
    assert s["effectiveness"] == pytest.approx(10 / 13, abs=0.002)
    assert s["cr"] == pytest.approx(1.0, abs=0.01)
    assert s["ntu"] == pytest.approx((10 / 13) / (1 - 10 / 13), rel=0.02)

    duty = hx_model()["design"]["duty_kw_per_cdu"]
    assert plate.inlet_delta_for_duty_k(duty, hot, cold) == pytest.approx(13.0, abs=0.1)
    assert plate.terminal_approach_k(duty, hot, cold) == pytest.approx(3.0, abs=0.1)


def test_calibrating_from_the_terminal_approach_is_refused_with_the_reason():
    """The mistake this model was built with first.

    eps is a fraction of the inlet-to-inlet difference (13 K here), not of the
    terminal approach (3 K). Feeding it the approach asks for eps = 3.33.
    """
    hot, cold = design_cdu_flows()
    with pytest.raises(ValueError, match="not a fraction"):
        # 50 C hot in, 40 C hot out, but a cold inlet only 3 K below hot out -
        # i.e. treating the terminal approach as the inlet-to-inlet difference.
        PlateExchanger.calibrate_from_temperatures(
            "wrong", 50.0, 40.0, 47.0, hot, cold)


def test_no_heat_moves_without_a_temperature_difference():
    hot, cold = design_cdu_flows()
    with pytest.raises(ValueError, match="no heat moves"):
        PlateExchanger.calibrate_from_temperatures("flat", 40.0, 39.0, 40.0, hot, cold)


# -- flow and area dependence -------------------------------------------

def test_ua_falls_with_flow_as_the_zero_point_eight_power():
    """So a CDU at 70 % flow is not 70 % of a heat exchanger."""
    plate = cdu_plate()
    hot, cold = design_cdu_flows()
    full = plate.ua_kw_per_k(hot, cold)
    part = plate.ua_kw_per_k(hot * 0.7, cold * 0.7)
    assert part / full == pytest.approx(0.7 ** FLOW_EXPONENT, rel=0.01)
    assert part / full > 0.7, "UA falls more slowly than flow"


def test_more_area_lowers_the_approach_but_with_sharp_diminishing_returns():
    """The Cr -> 1 constraint, and a real limit on what area can buy.

    Both sides carry the same duty at the same rise, so Cr is ~1 and eps caps at
    NTU/(1+NTU). Going from 1.0x to 1.6x the plate buys about 1 K.
    """
    plate = cdu_plate()
    hot, cold = design_cdu_flows()
    duty = hx_model()["design"]["duty_kw_per_cdu"]

    approaches = {}
    for scale in (0.5, 1.0, 1.6):
        plate.ua_scale = scale
        approaches[scale] = plate.terminal_approach_k(duty, hot, cold)

    assert approaches[0.5] > approaches[1.0] > approaches[1.6]
    # Halving costs about 3 K; adding 60 % buys about 1.
    assert approaches[0.5] - approaches[1.0] == pytest.approx(3.0, abs=0.6)
    assert approaches[1.0] - approaches[1.6] == pytest.approx(1.1, abs=0.5)


def test_max_duty_and_required_approach_are_inverses():
    plate = cdu_plate()
    hot, cold = design_cdu_flows()
    duty = 500.0
    inlet = plate.inlet_delta_for_duty_k(duty, hot, cold)
    assert plate.max_duty_kw(inlet, hot, cold) == pytest.approx(duty, rel=1e-6)


def test_a_dead_side_shifts_nothing_rather_than_dividing_by_zero():
    plate = cdu_plate()
    hot, _ = design_cdu_flows()
    assert plate.ua_kw_per_k(hot, 0.0) == 0.0
    assert plate.state(hot, 0.0)["effectiveness"] == 0.0
    assert plate.inlet_delta_for_duty_k(100.0, hot, 0.0) is None
    assert plate.terminal_approach_k(100.0, hot, 0.0) is None


# -- what the viewer is handed -------------------------------------------

def test_hx_model_states_its_method_and_its_caveats():
    m = hx_model()
    assert "NTU" in m["method"]
    assert any("1/UA" in r for r in m["relations"])
    assert m["design"]["terminal_approach_k"] == pytest.approx(3.0, abs=0.1)
    assert m["design"]["inlet_delta_k"] == pytest.approx(13.0, abs=0.1)
    assert m["flow_exponent"] == FLOW_EXPONENT
    assert 1.0 in m["ua_scales"]
    assert any("Cr" in c for c in m["caveats"])
