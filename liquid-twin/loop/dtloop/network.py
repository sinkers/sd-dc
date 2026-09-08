"""The hydraulic graph: nodes, branches, and the incidence matrix that links them.

A branch is an ordered list of elements in series between two nodes. Series is
the only composition here - parallel paths are expressed as parallel branches,
which is what makes flow redistribution fall out of the solve rather than
needing to be modelled.

Sign convention: `m_dot` on a branch is positive from `from_node` to `to_node`.
The incidence matrix follows it, `A[b, i] = +1` where branch b enters node i and
`-1` where it leaves, so `A.T @ q` is the net inflow at every node and the mass
balance is one matrix product.

One node must be the reference. A closed loop has no absolute pressure of its
own - only differences are determined - so without a reference the system is
singular by one degree of freedom. Physically the reference is the expansion
vessel connection, and nothing about the flow depends on what it is set to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .components import Element, Pipe, Pump, Valve


@dataclass
class Branch:
    """Elements in series between two nodes.

    `temperature_c` evaluates the fluid properties. In Phase 1 it is set per
    branch and held; Phase 2 replaces it with the transported temperature, at
    which point cold-end viscosity starts to move the flow split on its own.
    """

    name: str
    from_node: str
    to_node: str
    elements: list[Element] = field(default_factory=list)
    temperature_c: float = 30.0

    def evaluate(self, m_dot: float) -> tuple[float, float]:
        """Total pressure consumed and its derivative. Series elements add."""
        dp = 0.0
        ddp = 0.0
        for el in self.elements:
            d, g = el.evaluate(m_dot, self.temperature_c)
            dp += d
            ddp += g
        return dp, ddp

    def breakdown(self, m_dot: float) -> dict[str, float]:
        """Pressure consumed by each element - what valve authority is read from."""
        return {el.name: el.evaluate(m_dot, self.temperature_c)[0] for el in self.elements}

    def valves(self) -> list[Valve]:
        return [e for e in self.elements if isinstance(e, Valve)]

    def pumps(self) -> list[Pump]:
        return [e for e in self.elements if isinstance(e, Pump)]

    def volume_m3(self) -> float:
        return sum(e.volume_m3() for e in self.elements if isinstance(e, Pipe))


class Network:
    """A hydraulic network. Build it with `add_node` / `add_branch`, then solve."""

    def __init__(self, name: str = "network"):
        self.name = name
        self._nodes: list[str] = []
        self._demand: dict[str, float] = {}
        self.branches: list[Branch] = []
        self.reference_node: str | None = None
        self.reference_pressure_pa: float = 300000.0

    # -- construction ----------------------------------------------------

    def add_node(self, name: str, demand_kgs: float = 0.0) -> str:
        """A junction. `demand_kgs` extracts flow - zero everywhere in a closed
        loop, which is every loop in this model."""
        if name in self._nodes:
            raise ValueError(f"duplicate node {name!r}")
        self._nodes.append(name)
        self._demand[name] = demand_kgs
        return name

    def add_branch(self, name, from_node, to_node, elements, temperature_c=30.0) -> Branch:
        if from_node not in self._nodes:
            raise ValueError(f"branch {name!r}: unknown from_node {from_node!r}")
        if to_node not in self._nodes:
            raise ValueError(f"branch {name!r}: unknown to_node {to_node!r}")
        if from_node == to_node:
            raise ValueError(f"branch {name!r} starts and ends at {from_node!r}")
        if any(b.name == name for b in self.branches):
            raise ValueError(f"duplicate branch {name!r}")
        branch = Branch(name, from_node, to_node, list(elements), temperature_c)
        self.branches.append(branch)
        return branch

    def set_reference(self, node: str, pressure_pa: float = 300000.0) -> None:
        if node not in self._nodes:
            raise ValueError(f"unknown reference node {node!r}")
        self.reference_node = node
        self.reference_pressure_pa = pressure_pa

    # -- structure -------------------------------------------------------

    @property
    def nodes(self) -> list[str]:
        return list(self._nodes)

    @property
    def n_nodes(self) -> int:
        return len(self._nodes)

    @property
    def n_branches(self) -> int:
        return len(self.branches)

    def node_index(self, name: str) -> int:
        return self._nodes.index(name)

    def branch(self, name: str) -> Branch:
        for b in self.branches:
            if b.name == name:
                return b
        raise KeyError(f"no branch {name!r}")

    def incidence(self) -> np.ndarray:
        """A[b, i]: +1 where branch b enters node i, -1 where it leaves."""
        a = np.zeros((self.n_branches, self.n_nodes))
        for bi, br in enumerate(self.branches):
            a[bi, self.node_index(br.from_node)] = -1.0
            a[bi, self.node_index(br.to_node)] = +1.0
        return a

    def demands(self) -> np.ndarray:
        return np.array([self._demand[n] for n in self._nodes])

    def validate(self) -> list[str]:
        """Structural problems, as messages. Empty means the network is solvable.

        Checked before the solve because every one of these shows up in the
        linear algebra as a singular matrix, and 'singular Jacobian' does not
        tell anyone which node they forgot to connect.
        """
        problems: list[str] = []
        if self.reference_node is None:
            problems.append(
                "no reference node: a closed loop determines only pressure "
                "differences, so one node must be fixed (set_reference)"
            )
        if not self.branches:
            problems.append("no branches")
            return problems

        touched = {n for b in self.branches for n in (b.from_node, b.to_node)}
        for node in self._nodes:
            if node not in touched:
                problems.append(f"node {node!r} has no branches")

        # Every node must reach the reference, or its pressure is undetermined.
        if self.reference_node is not None:
            adjacency: dict[str, set[str]] = {n: set() for n in self._nodes}
            for b in self.branches:
                adjacency[b.from_node].add(b.to_node)
                adjacency[b.to_node].add(b.from_node)
            seen = {self.reference_node}
            stack = [self.reference_node]
            while stack:
                for nxt in adjacency[stack.pop()]:
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            for node in self._nodes:
                if node not in seen:
                    problems.append(
                        f"node {node!r} is not connected to the reference node "
                        f"{self.reference_node!r}; its pressure is undetermined"
                    )
        return problems
