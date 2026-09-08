"""The hydraulic solve, against SPEC.md section 12 rows 3-6.

The load-bearing test is `test_closing_one_branch_redistributes_flow`. Every
scenario the model exists to run depends on flow being an output, and that test
is what proves it is.
"""

import math

import numpy as np
import pytest

from dtloop import fluid
from dtloop.components import Pipe, Pump, PumpCurve, Resistance, Valve
from dtloop.hydraulics import (
    HydraulicSolveError,
    loop_closure_error,
    solve,
    valve_authority,
)
from dtloop.network import Network

G = 9.80665


def simple_loop(t_c=30.0):
    """Pump against one resistance. The operating point is solvable by hand."""
    net = Network("simple")
    net.add_node("A")
    net.add_node("B")
    curve = PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)])
    net.add_branch("pump", "A", "B", [Pump(curve, name="P1", max_flow_m3h=200.0)], t_c)
    net.add_branch("load", "B", "A", [Resistance.from_rating(200e3, 10.0, "coil")], t_c)
    net.set_reference("A", 300_000.0)
    return net, curve


def parallel_racks(n=4, kv=40.0, t_c=30.0):
    """A pump, a supply and return main, and n identical rack branches."""
    net = Network("racks")
    for node in ("suction", "discharge", "supply_hdr", "return_hdr"):
        net.add_node(node)
    curve = PumpCurve.from_points([(0.0, 45.0), (150.0, 38.0), (300.0, 18.0)])
    net.add_branch("pump", "suction", "discharge", [Pump(curve, name="P1", max_flow_m3h=300.0)], t_c)
    net.add_branch("supply", "discharge", "supply_hdr", [Pipe(30.0, 0.15, fittings_k=4.0, name="supply_main")], t_c)
    names = []
    for i in range(n):
        nm = f"rack{i + 1}"
        net.add_branch(nm, "supply_hdr", "return_hdr", [
            Pipe(25.0, 0.05, fittings_k=8.0, name=f"{nm}_pipe"),
            Valve(kv_rated=kv, position=1.0, name=f"{nm}_valve"),
            Resistance.from_rating(60e3, 2.5, f"{nm}_coldplate"),
        ], t_c)
        names.append(nm)
    net.add_branch("return", "return_hdr", "suction", [Pipe(30.0, 0.15, fittings_k=4.0, name="return_main")], t_c)
    net.set_reference("suction", 300_000.0)
    return net, names


# -- SPEC section 12: pump operating point matches hand calc -------------

def test_pump_operating_point_matches_the_analytic_intersection():
    t_c = 30.0
    net, curve = simple_loop(t_c)
    sol = solve(net)
    assert sol.converged

    # By hand: the loop balances where rho*g*H(Q) = K*Q^2. Bisect it.
    rho = float(fluid.density(t_c))
    k = 200e3 / 10.0**2

    def residual(m):
        return rho * G * curve.head_m(m * 3600.0 / rho) - k * m * m

    lo, hi = 1e-9, 100.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if residual(lo) * residual(mid) <= 0:
            hi = mid
        else:
            lo = mid

    assert sol.flow("pump") == pytest.approx(mid, rel=1e-9)


# -- SPEC section 12: hydraulic closure ----------------------------------

def test_pressure_closes_around_the_loop():
    net, _ = simple_loop()
    sol = solve(net)
    assert loop_closure_error(net, sol, ["pump", "load"]) == pytest.approx(0.0, abs=1e-6)


def test_closure_holds_around_every_cycle_of_a_parallel_network():
    net, racks = parallel_racks()
    sol = solve(net)
    for rack in racks:
        err = loop_closure_error(net, sol, ["pump", "supply", rack, "return"])
        assert err == pytest.approx(0.0, abs=1e-3), f"{rack}: {err} Pa"


def test_a_path_that_is_not_a_cycle_is_refused():
    net, _ = parallel_racks()
    sol = solve(net)
    with pytest.raises(ValueError, match="does not continue|not a closed cycle"):
        loop_closure_error(net, sol, ["pump", "rack1"])


# -- SPEC section 12: mass conservation ----------------------------------

def test_mass_conserves_at_every_node():
    net, _ = parallel_racks()
    sol = solve(net)
    q = sol.as_array(net)
    net_in = net.incidence().T @ q
    assert np.max(np.abs(net_in)) < 1e-9


def test_series_branches_carry_identical_flow():
    net, racks = parallel_racks()
    sol = solve(net)
    total = sum(sol.flow(r) for r in racks)
    assert sol.flow("pump") == pytest.approx(total, rel=1e-9)
    assert sol.flow("supply") == pytest.approx(sol.flow("return"), rel=1e-9)


# -- SPEC section 12: redistribution. The load-bearing test. -------------

def test_closing_one_branch_redistributes_flow():
    net, racks = parallel_racks()
    base = solve(net)
    base_each = base.flow("rack2")

    net.branch("rack1").valves()[0].position = 0.0
    shut = solve(net, base.as_array(net))
    assert shut.converged

    # The shut branch stops.
    assert abs(shut.flow("rack1")) < 1e-2
    assert abs(shut.flow("rack1")) < 0.005 * base.flow("rack1")

    # The survivors gain - the whole point. Nothing told them to.
    assert shut.flow("rack2") > base_each
    for rack in racks[1:]:
        assert shut.flow(rack) == pytest.approx(shut.flow("rack2"), rel=1e-9)

    # Total falls, but by less than the quarter that was removed, because the
    # pump rides up its curve as the system resistance rises.
    assert shut.flow("pump") < base.flow("pump")
    lost = 1.0 - shut.flow("pump") / base.flow("pump")
    assert 0.0 < lost < 0.25, f"lost {lost:.1%}; a pump on its curve cannot lose the full quarter"


def test_partial_closure_lands_between_open_and_shut():
    net, _ = parallel_racks()
    base = solve(net)
    valve = net.branch("rack1").valves()[0]

    valve.position = 0.0
    shut = solve(net, base.as_array(net))
    valve.position = 0.5
    half = solve(net, shut.as_array(net))

    assert shut.flow("rack1") < half.flow("rack1") < base.flow("rack1")
    assert base.flow("pump") > half.flow("pump") > shut.flow("pump")


def test_a_shut_branch_does_not_disappear_from_the_network():
    # It keeps its node, so Phase 2 can keep integrating its temperature while
    # it sits starved. That is the failure the scenario exists to show.
    net, _ = parallel_racks()
    net.branch("rack1").valves()[0].position = 0.0
    sol = solve(net)
    assert "rack1" in sol.flows
    assert math.isfinite(sol.flow("rack1"))


# -- SPEC section 12: valve authority ------------------------------------

def test_valve_authority_rises_as_the_valve_is_made_the_dominant_loss():
    generous = parallel_racks(kv=200.0)[0]   # a big valve: little of the drop
    restrictive = parallel_racks(kv=8.0)[0]  # a small one: most of the drop

    a_generous = valve_authority(generous, solve(generous), "rack1", "rack1_valve")
    a_restrictive = valve_authority(restrictive, solve(restrictive), "rack1", "rack1_valve")

    assert 0.0 < a_generous < a_restrictive < 1.0
    assert a_generous < 0.3, "an oversized valve should show poor authority"
    assert a_restrictive > 0.5


def test_valve_authority_names_the_element_it_cannot_find():
    net, _ = parallel_racks()
    sol = solve(net)
    with pytest.raises(KeyError, match="rack1_bypass"):
        valve_authority(net, sol, "rack1", "rack1_bypass")


# -- Solver behaviour ----------------------------------------------------

def test_warm_start_costs_far_fewer_iterations_than_cold():
    net, _ = parallel_racks()
    cold = solve(net)
    net.branch("rack1").valves()[0].position = 0.95  # a small disturbance
    warm = solve(net, cold.as_array(net))
    assert warm.converged
    assert warm.iterations < cold.iterations


def test_reference_pressure_sets_the_level_and_nothing_else():
    net_a, _ = parallel_racks()
    net_b, _ = parallel_racks()
    net_b.set_reference("suction", 800_000.0)

    sol_a, sol_b = solve(net_a), solve(net_b)
    for name in sol_a.flows:
        assert sol_a.flow(name) == pytest.approx(sol_b.flow(name), rel=1e-12)
    offset = 800_000.0 - 300_000.0
    for node in sol_a.pressures:
        assert sol_b.pressures[node] - sol_a.pressures[node] == pytest.approx(offset, abs=1e-6)


def test_pump_raises_pressure_across_itself():
    net, _ = parallel_racks()
    sol = solve(net)
    assert sol.pressures["discharge"] > sol.pressures["suction"]
    assert sol.pressures["supply_hdr"] > sol.pressures["return_hdr"]


def test_cold_fluid_costs_more_pressure_in_the_pipework():
    """Viscosity reaches the pressure drop, which is why fluid.py exists."""
    net, _ = parallel_racks()
    cold, warm = parallel_racks(t_c=5.0)[0], parallel_racks(t_c=45.0)[0]

    s_cold, s_warm = solve(cold), solve(warm)
    dp_cold = cold.branch("rack1").breakdown(s_cold.flow("rack1"))["rack1_pipe"]
    dp_warm = warm.branch("rack1").breakdown(s_warm.flow("rack1"))["rack1_pipe"]
    assert dp_cold > dp_warm * 1.05


def test_temperature_barely_moves_total_flow_in_a_fixed_k_network():
    """A result worth pinning, because the intuition points the other way.

    Cold fluid is more viscous, so one expects less flow. In this network it is
    a fraction of a percent, and not even reliably in that direction. Two
    reasons: the cold plates are `Resistance` elements whose k is a constant, so
    two thirds of the branch loss does not know the temperature at all; and
    denser cold fluid turns the same pump head in metres into more pascals,
    which pushes the other way.

    So a system-level flow change is NOT a good check that viscosity is wired
    up - the pipework test above is. If Phase 2 makes cold plate resistance
    temperature-dependent, this test should be revisited rather than trusted.
    """
    flows = {t: solve(parallel_racks(t_c=t)[0]).flow("pump") for t in (5.0, 30.0, 45.0)}
    spread = (max(flows.values()) - min(flows.values())) / min(flows.values())
    assert spread < 0.01, f"expected under 1% across 5-45 C, got {spread:.2%}: {flows}"


# -- Structural validation ------------------------------------------------

def test_missing_reference_is_reported_as_a_missing_reference():
    net = Network("no-ref")
    net.add_node("A")
    net.add_node("B")
    net.add_branch("a", "A", "B", [Resistance(k=100.0)])
    net.add_branch("b", "B", "A", [Resistance(k=100.0)])
    with pytest.raises(HydraulicSolveError, match="no reference node"):
        solve(net)


def test_a_disconnected_node_is_named():
    net = Network("island")
    for n in ("A", "B", "C"):
        net.add_node(n)
    net.add_branch("a", "A", "B", [Resistance(k=100.0)])
    net.add_branch("b", "B", "A", [Resistance(k=100.0)])
    net.set_reference("A")
    with pytest.raises(HydraulicSolveError, match="'C'"):
        solve(net)


def test_construction_errors_are_caught_at_construction():
    net = Network("bad")
    net.add_node("A")
    with pytest.raises(ValueError, match="duplicate node"):
        net.add_node("A")
    with pytest.raises(ValueError, match="unknown to_node"):
        net.add_branch("x", "A", "Z", [])
    net.add_node("B")
    with pytest.raises(ValueError, match="starts and ends"):
        net.add_branch("x", "A", "A", [])
    net.add_branch("x", "A", "B", [])
    with pytest.raises(ValueError, match="duplicate branch"):
        net.add_branch("x", "A", "B", [])


def test_non_convergence_can_be_survived_instead_of_raised():
    net, _ = simple_loop()
    with pytest.raises(HydraulicSolveError, match="did not converge"):
        solve(net, max_iter=1)
    sol = solve(net, max_iter=1, strict=False)
    assert not sol.converged
    assert any("did not converge" in w for w in sol.warnings)


def test_running_past_runout_is_warned_about_not_hidden():
    net = Network("runout")
    net.add_node("A")
    net.add_node("B")
    curve = PumpCurve.from_points([(0.0, 50.0), (100.0, 45.0), (200.0, 25.0)])
    net.add_branch("pump", "A", "B", [Pump(curve, name="P1", max_flow_m3h=20.0)], 30.0)
    net.add_branch("load", "B", "A", [Resistance.from_rating(1e3, 10.0, "open")], 30.0)
    net.set_reference("A")
    sol = solve(net)
    assert any("runout" in w for w in sol.warnings)


def test_initial_flows_of_the_wrong_length_are_refused():
    net, _ = simple_loop()
    with pytest.raises(ValueError, match="must have 2 entries"):
        solve(net, np.zeros(5))
