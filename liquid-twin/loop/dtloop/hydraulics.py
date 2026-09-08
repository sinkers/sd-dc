"""The Newton solve. Flow is the unknown - the model's governing decision.

SPEC.md section 2 states it: this model must never prescribe a flow rate. The
air-side CFD does (`case-au01/0.orig/U` puts a fixed mass flow on the fan wall
patches), which is correct for a steady design-point study and useless for
asking what a closed valve does. Here every flow is solved for, so shutting a
valve redistributes flow across the parallel branches, drives the pump up its
curve, and starves one branch - a chain nobody has to model, because it falls
out of solving the network.

## The system

Unknowns are the branch flows `q` and the free-node pressures `h`, together:

    energy, per branch b:   -(A h)_b - dp_b(q_b) = 0     (p_from - p_to = dp)
    mass,   per free node:   (A.T q)_i - demand_i = 0

with `A` the incidence matrix from network.py. The Jacobian is the saddle-point
block matrix

    J = [ -D   -A_f ]        D = diag(d(dp)/dq)
        [ A_f.T   0 ]

which is assembled and solved dense.

## Measured cost

Toggling a valve fully open and shut every frame - the worst case, not a quiet
one - on this machine:

    branches   iterations   per frame     headroom at 10 Hz
           7            7     1.2 ms                   81x
          27            6     4.4 ms                   22x
          99            6    16.7 ms                    6x

Comfortably inside a 100 ms frame at AU01's size, and 6x is not the margin to
build on if the network grows much past a hundred branches. The cost is not the
linear algebra - a 100x100 dense solve is microseconds - it is the Python loop
over branches calling `evaluate`, run once per iteration plus once per line
search backtrack. Vectorising that loop is the first optimisation, and a sparse
factorisation only becomes the answer in the thousands.

## Warm starting

`solve` takes the previous frame's flows as its initial guess. It saves two or
three iterations against a cold start, less than the order of magnitude one
might hope for, because the backtracking line search already makes a cold start
cheap. Its real value is that a warm start begins near the physical root, which
matters more than speed on a network with a valve near its seat.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .network import Network

# Residual scaling for the line search: roughly one part in a thousand of a
# realistic branch pressure drop and mass flow, so the two contribute comparably.
_ENERGY_SCALE = 100.0  # Pa
_MASS_SCALE = 1.0e-3   # kg/s


@dataclass
class Solution:
    """A converged (or abandoned) hydraulic state."""

    flows: dict[str, float]  # kg/s, per branch
    pressures: dict[str, float]  # Pa, per node
    iterations: int
    converged: bool
    max_mass_residual: float  # kg/s
    max_energy_residual: float  # Pa
    warnings: list[str] = field(default_factory=list)

    def flow(self, branch: str) -> float:
        return self.flows[branch]

    def dp(self, network: Network, branch: str) -> float:
        """Pressure consumed by a branch [Pa]. Negative where a pump dominates."""
        return network.branch(branch).evaluate(self.flows[branch])[0]

    def as_array(self, network: Network) -> np.ndarray:
        return np.array([self.flows[b.name] for b in network.branches])


class HydraulicSolveError(RuntimeError):
    pass


_MAX_BACKTRACKS = 40


def _residuals(network, a_f, demands, q, h):
    """Energy residual per branch and mass residual per free node."""
    dp = np.array([br.evaluate(q[bi])[0] for bi, br in enumerate(network.branches)])
    return -(a_f @ h) - dp, a_f.T @ q - demands


def _residual_norm(r_energy, r_mass) -> float:
    """One number for the line search to reduce.

    Mass residuals are kg/s and energy residuals Pa - eight orders apart - so
    they are scaled before being combined. Without the scaling the norm is a
    pressure norm with a rounding error attached, and the search would happily
    accept a step that fixed pressures while breaking continuity.
    """
    return float(
        np.sqrt(np.sum((r_energy / _ENERGY_SCALE) ** 2) + np.sum((r_mass / _MASS_SCALE) ** 2))
    )


def solve(
    network: Network,
    initial_flows: np.ndarray | None = None,
    *,
    max_iter: int = 60,
    mass_tol: float = 1e-8,       # kg/s
    energy_tol: float = 1e-3,     # Pa
    strict: bool = True,
) -> Solution:
    """Solve for every branch flow and node pressure.

    The Newton step is globalised by backtracking: undamped, the first iteration
    from a cold start routinely asks for thousands of kg/s, because the
    quadratic loss is nearly flat near zero and the linearisation points a long
    way off. The step is halved until the residual norm falls, which costs an
    evaluation or two on the first frame and nothing once warm-started.

    With `strict`, failure to converge raises. Set it False in a real-time loop,
    where carrying a flagged imperfect state to the next frame beats stopping.
    """
    problems = network.validate()
    if problems:
        raise HydraulicSolveError(
            "network is not solvable:\n  " + "\n  ".join(problems)
        )

    n_b = network.n_branches
    a_full = network.incidence()
    ref = network.node_index(network.reference_node)
    free = [i for i in range(network.n_nodes) if i != ref]
    a_f = a_full[:, free]
    n_f = len(free)

    demands = network.demands()[free]

    q = np.ones(n_b) if initial_flows is None else np.array(initial_flows, dtype=float)
    if q.shape != (n_b,):
        raise ValueError(f"initial_flows must have {n_b} entries, got {q.shape}")
    h = np.zeros(n_f)  # gauge relative to the reference node

    warnings: list[str] = []
    converged = False
    it = 0
    r_mass = np.zeros(n_f)
    r_energy = np.zeros(n_b)

    for it in range(1, max_iter + 1):
        dp = np.empty(n_b)
        d = np.empty(n_b)
        for bi, br in enumerate(network.branches):
            dp[bi], d[bi] = br.evaluate(q[bi])

        r_energy = -(a_f @ h) - dp
        r_mass = a_f.T @ q - demands

        if np.max(np.abs(r_mass)) < mass_tol and np.max(np.abs(r_energy)) < energy_tol:
            converged = True
            break

        jac = np.zeros((n_b + n_f, n_b + n_f))
        jac[:n_b, :n_b] = -np.diag(d)
        jac[:n_b, n_b:] = -a_f
        jac[n_b:, :n_b] = a_f.T

        rhs = -np.concatenate([r_energy, r_mass])
        try:
            step = np.linalg.solve(jac, rhs)
        except np.linalg.LinAlgError as exc:
            raise HydraulicSolveError(
                f"singular Jacobian at iteration {it}. The usual cause is a "
                f"branch whose pressure does not depend on its flow: a Pump "
                f"alone on a branch with no pipe or nozzle loss will do it, "
                f"since a clipped curve is flat near shutoff. Give the pump "
                f"branch its suction and discharge losses - a real one has them."
            ) from exc

        # Backtracking line search on the residual norm. A fixed step clamp was
        # tried first and is worse than it looks: it caps how far an iteration
        # may travel without asking whether travelling there helped, and on a
        # loose network it produces a two-point limit cycle that runs out the
        # iteration budget without ever getting near the root. Halving until the
        # residual actually falls costs an evaluation or two and cannot cycle.
        norm0 = _residual_norm(r_energy, r_mass)
        scale = 1.0
        for _ in range(_MAX_BACKTRACKS):
            q_try = q + scale * step[:n_b]
            h_try = h + scale * step[n_b:]
            if _residual_norm(*_residuals(network, a_f, demands, q_try, h_try)) < norm0:
                break
            scale *= 0.5
        q = q + scale * step[:n_b]
        h = h + scale * step[n_b:]

    pressures = {network.reference_node: network.reference_pressure_pa}
    for slot, node_i in enumerate(free):
        pressures[network.nodes[node_i]] = network.reference_pressure_pa + h[slot]

    flows = {br.name: float(q[bi]) for bi, br in enumerate(network.branches)}

    if not converged:
        msg = (
            f"did not converge in {max_iter} iterations "
            f"(mass residual {np.max(np.abs(r_mass)):.3e} kg/s, "
            f"energy residual {np.max(np.abs(r_energy)):.3e} Pa)"
        )
        if strict:
            raise HydraulicSolveError(msg)
        warnings.append(msg)

    for bi, br in enumerate(network.branches):
        for pump in br.pumps():
            if pump.beyond_curve(q[bi], br.temperature_c):
                warnings.append(
                    f"{br.name}/{pump.name} is running past its published "
                    f"runout; head is extrapolated"
                )

    return Solution(
        flows=flows,
        pressures=pressures,
        iterations=it,
        converged=converged,
        max_mass_residual=float(np.max(np.abs(r_mass))),
        max_energy_residual=float(np.max(np.abs(r_energy))),
        warnings=warnings,
    )


def loop_closure_error(network: Network, solution: Solution, path: list[str]) -> float:
    """Pressure that fails to close around a named cycle of branches [Pa].

    A verification quantity, not something the solve uses. Traverse the cycle
    adding each branch's consumed pressure, signed by whether it is traversed
    forwards; on a converged solution the total is zero to solver tolerance,
    pump included. That is Kirchhoff's second law, and it is an independent
    check because the solve enforces the *nodal* form, not this one.
    """
    total = 0.0
    branches = [network.branch(name) for name in path]
    node = branches[0].from_node
    for br in branches:
        dp = br.evaluate(solution.flows[br.name])[0]
        if br.from_node == node:
            total += dp
            node = br.to_node
        elif br.to_node == node:
            total -= dp
            node = br.from_node
        else:
            raise ValueError(
                f"branch {br.name!r} ({br.from_node} -> {br.to_node}) does not "
                f"continue the path at node {node!r}"
            )
    if node != branches[0].from_node:
        raise ValueError(f"path is not a closed cycle; it ends at {node!r}")
    return total


def valve_authority(network: Network, solution: Solution, branch_name: str, valve_name: str) -> float:
    """Valve authority: dp across the valve / dp across the whole branch.

    The classic control-valve figure. Below about 0.3 an equal-percentage valve
    stops behaving like one - its installed characteristic distorts toward
    quick-opening and the control loop above it gets twitchy near the shut end.
    Computed from the solved state, so it is the *installed* authority rather
    than the design intent.
    """
    branch = network.branch(branch_name)
    m_dot = solution.flows[branch_name]
    parts = branch.breakdown(m_dot)
    if valve_name not in parts:
        raise KeyError(f"branch {branch_name!r} has no element named {valve_name!r}")
    total = sum(v for v in parts.values() if v > 0)  # resistive elements only
    if total <= 0:
        return 0.0
    return parts[valve_name] / total
