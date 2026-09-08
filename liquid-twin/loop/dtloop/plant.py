"""Build the hydraulic networks from the layout, size the pumps, solve.

This is where SPEC.md section 9 stops being a claim. `layout.py` holds the
routed network; `network.py` and `hydraulics.py` hold the solver; this module is
the twenty lines of joinery between them, and the result is that a pipe drawn in
the review model is the same pipe the solver puts flow through.

## Four circuits, not one

The facility loop and the three pod TCS loops are hydraulically separate - they
meet only across the CDU plates, thermally. So this builds four independent
`Network`s rather than one, which is both physically right and structurally
necessary: a single network containing four disconnected circuits has three
undetermined pressure levels and the solver refuses it, correctly.

## What the layout does not draw

Pipe runs stop at equipment. The branches that close each circuit run *through*
equipment and have no centreline in the model, so they are added here:

    chiller{i}_in  -> chiller{i}_out     evaporator
    pump{i}_in     -> pump{i}_out        CWP-i, one of four in parallel
    cdu{n}_fac_in  -> cdu{n}_fac_out     plate, facility side
    cdu{n}_tcs_in  -> cdu{n}_tcs_out     plate, secondary side + integral pump
    {rack}_in      -> {rack}_out         the cold plates in the rack

The pumps sit on their own branches rather than being bolted onto the chiller
branch, because CWP-1..4 are drawn as real skids in the layout with pipe either
side of them: a pump that is a term in someone else's branch cannot report its
own suction and discharge pressure, and that is exactly what a reader wants.

They are also in **parallel between two manifolds**, not in series one per
chiller. On manifolds every pump sees the same differential, so identical pumps
share equally and losing one leaves the survivors to split the whole duty -
which is both what a plant is built like and the N-1 case worth showing.

## Pumps are derived, not guessed

RD110 lists its chilled water pumps as "to be sized upon design implementation",
so there is no curve to read. Rather than invent one, `size_pump` solves the
network once with the pump replaced by an ideal pressure source at design flow,
reads the head the system actually needs, and fits a curve through it. The duty
point then lands on design flow by construction, and if someone changes a pipe
size the pump follows.

Everything about the resistances is grade L until vendor data arrives -
`loop_params.json` marks each one. The shape of the answer is what to trust:
which branch is starved, which way flow moves when a valve shuts, where the
pressure is spent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import fluid
from .components import CheckValve, Pipe, Pump, PumpCurve, Resistance, Valve
from .hx import PlateExchanger
from .hydraulics import Solution, solve, valve_authority
from .layout import (
    CDU_PER_POD,
    POD_COUNT,
    SERVICES,
    V_MAX,
    LoopLayout,
    build_layout,
)
from .network import Network

# Design duty. RD110: 87 % of 48 AI racks at 142 kW, both loops on a 10 K rise.
RACK_LIQUID_KW = 142.0 * 0.87
LOOP_DELTA_T = 10.0
RACK_COUNT = 48
RACKS_PER_POD = RACK_COUNT // POD_COUNT

FACILITY_SUPPLY_C = 37.0
FACILITY_RETURN_C = 47.0
TCS_SUPPLY_C = 40.0
TCS_RETURN_C = 50.0

CHILLERS_RUNNING = 3  # N+1 of four

# Rated pressure drops, all grade L pending vendor data. Each is expressed at
# its design flow so `Resistance.from_rating` can turn it into a coefficient.
DP_COLDPLATE_KPA = 150.0     # GB300 NVL72 rack cold plate circuit
DP_PHX_PRIMARY_KPA = 60.0    # MCDU-50 plate, facility side
DP_PHX_SECONDARY_KPA = 60.0  # MCDU-50 plate, secondary side
DP_EVAPORATOR_KPA = 80.0     # XRAF4242A evaporator

# Rack control valve. Sized for authority near 0.3 at design flow rather than
# for a nominal line size - an oversized valve controls nothing, which the
# Phase 1 tests already demonstrate.
RACK_VALVE_KV = 16.0

FITTING_K_PER_ELBOW = 0.75  # long-radius bend
ROUGHNESS_M = 4.5e-5


def rack_flow_kgs(t_c: float = TCS_SUPPLY_C) -> float:
    return fluid.flow_for_duty(RACK_LIQUID_KW * 1000.0, LOOP_DELTA_T, t_c)


def pod_flow_kgs(t_c: float = TCS_SUPPLY_C) -> float:
    return rack_flow_kgs(t_c) * RACKS_PER_POD


def facility_flow_kgs(t_c: float = FACILITY_SUPPLY_C) -> float:
    return fluid.flow_for_duty(RACK_LIQUID_KW * RACK_COUNT * 1000.0, LOOP_DELTA_T, t_c)


def _pipe_for(segment, t_c: float) -> Pipe:
    return Pipe(
        length_m=segment.length_mm() / 1000.0,
        diameter_m=segment.dn / 1000.0,
        roughness_m=ROUGHNESS_M,
        fittings_k=segment.elbows() * FITTING_K_PER_ELBOW,
        name=f"{segment.name}_pipe",
    )


@dataclass
class Circuit:
    """One solvable loop, with the bookkeeping the viewer needs."""

    name: str
    network: Network
    design_flow_kgs: float
    temperature_c: float
    # Which layout segments this circuit's branches correspond to. A branch that
    # runs through equipment has no segment and is absent here.
    segment_of_branch: dict[str, str] = field(default_factory=dict)
    pump_branches: list[str] = field(default_factory=list)
    # Flow meter tag -> the branch it is installed in.
    meters: dict[str, str] = field(default_factory=dict)


def build_circuits(lay: LoopLayout | None = None) -> dict[str, Circuit]:
    """The facility loop and one TCS loop per pod."""
    lay = lay or build_layout()
    circuits: dict[str, Circuit] = {}
    circuits["facility"] = _build_facility(lay)
    for pod in range(POD_COUNT):
        circuits[f"pod{pod + 1}"] = _build_pod(lay, pod)
    return circuits


def _add_segments(net: Network, lay: LoopLayout, names, t_c: float, mapping: dict,
                  meters: dict | None = None) -> None:
    for seg in lay.segments:
        if seg.name not in names:
            continue
        if seg.meter and meters is not None:
            meters[seg.meter] = seg.name
        elements = [_pipe_for(seg, t_c)]
        if seg.valve:
            kv = RACK_VALVE_KV if seg.valve.startswith("PCV") else 250.0
            elements.append(Valve(
                kv_rated=kv,
                position=1.0,
                characteristic="equal_percentage" if seg.valve.startswith("PCV") else "linear",
                name=seg.valve,
            ))
        for node in (seg.from_node, seg.to_node):
            if node not in net.nodes:
                net.add_node(node)
        net.add_branch(seg.name, seg.from_node, seg.to_node, elements, t_c)
        mapping[seg.name] = seg.name


def _build_facility(lay: LoopLayout) -> Circuit:
    t_c = FACILITY_SUPPLY_C
    net = Network("facility")
    mapping: dict[str, str] = {}

    meters: dict[str, str] = {}
    wanted = {s.name for s in lay.segments
              if s.service.startswith("facility")
              and not s.name.startswith(f"CH{CHILLERS_RUNNING + 1}")}
    _add_segments(net, lay, wanted, t_c, mapping, meters)

    per_chiller = facility_flow_kgs(t_c) / CHILLERS_RUNNING
    per_cdu = facility_flow_kgs(t_c) / (POD_COUNT * CDU_PER_POD)
    pumps = []

    for i in range(1, CHILLERS_RUNNING + 1):
        # Evaporator, fed from the pump discharge manifold.
        for node in (f"chiller{i}_in", f"chiller{i}_out"):
            if node not in net.nodes:
                net.add_node(node)
        net.add_branch(f"CH{i}_UNIT", f"chiller{i}_in", f"chiller{i}_out", [
            Resistance.from_rating(DP_EVAPORATOR_KPA * 1000.0, per_chiller, f"CH{i}_evaporator"),
        ], t_c)

        # CWP-i, in parallel with the others between the two manifolds. The
        # non-return valve is what stops the manifolds short-circuiting straight
        # through a stopped pump - which, on a common-manifold arrangement, they
        # otherwise do: the whole discharge header is sitting on its outlet.
        for node in (f"pump{i}_in", f"pump{i}_out"):
            if node not in net.nodes:
                net.add_node(node)
        name = f"CWP-{i}_UNIT"
        net.add_branch(name, f"pump{i}_in", f"pump{i}_out", [
            Resistance.from_rating(15_000.0, per_chiller, f"CWP-{i}_nozzles"),
            CheckValve.from_rating(8_000.0, per_chiller, f"NRV-{i}"),
        ], t_c)
        pumps.append(name)

    # CDU plates, facility side.
    for n in range(1, POD_COUNT * CDU_PER_POD + 1):
        for node in (f"cdu{n}_fac_in", f"cdu{n}_fac_out"):
            if node not in net.nodes:
                net.add_node(node)
        net.add_branch(f"CDU{n}_PLATE_FAC", f"cdu{n}_fac_in", f"cdu{n}_fac_out", [
            Resistance.from_rating(DP_PHX_PRIMARY_KPA * 1000.0, per_cdu, f"CDU{n}_plate_fac"),
        ], t_c)

    net.set_reference("chiller_hdr_return", 300_000.0)
    return Circuit("facility", net, facility_flow_kgs(t_c), t_c, mapping, pumps, meters)


def _build_pod(lay: LoopLayout, pod: int) -> Circuit:
    t_c = TCS_SUPPLY_C
    net = Network(f"pod{pod + 1}")
    mapping: dict[str, str] = {}

    meters: dict[str, str] = {}
    wanted = {s.name for s in lay.segments
              if s.pod == pod and s.service.startswith("tcs")}
    _add_segments(net, lay, wanted, t_c, mapping, meters)

    per_rack = rack_flow_kgs(t_c)
    per_cdu = pod_flow_kgs(t_c) / CDU_PER_POD
    pumps = []

    # Cold plates: the branch through each rack.
    for eq in lay.by_kind("rack"):
        if eq.pod != pod:
            continue
        for node in (f"{eq.name}_in", f"{eq.name}_out"):
            if node not in net.nodes:
                net.add_node(node)
        net.add_branch(f"{eq.name}_COLDPLATE", f"{eq.name}_in", f"{eq.name}_out", [
            Resistance.from_rating(DP_COLDPLATE_KPA * 1000.0, per_rack, f"{eq.name}_coldplate"),
        ], t_c)

    # CDU secondary side: plate plus the MCDU-50's integral pump.
    for i in range(CDU_PER_POD):
        n = pod * CDU_PER_POD + i + 1
        for node in (f"cdu{n}_tcs_in", f"cdu{n}_tcs_out"):
            if node not in net.nodes:
                net.add_node(node)
        name = f"CDU{n}_PLATE_TCS"
        net.add_branch(name, f"cdu{n}_tcs_in", f"cdu{n}_tcs_out", [
            Resistance.from_rating(DP_PHX_SECONDARY_KPA * 1000.0, per_cdu, f"CDU{n}_plate_tcs"),
            CheckValve.from_rating(6_000.0, per_cdu, f"CDU{n}_NRV"),
        ], t_c)
        pumps.append(name)

    net.set_reference(f"pod{pod + 1}_cdu_in", 250_000.0)
    return Circuit(f"pod{pod + 1}", net, pod_flow_kgs(t_c), t_c, mapping, pumps, meters)


def size_pumps(circuit: Circuit, margin: float = 1.0) -> float:
    """Fit each pump's curve so the circuit's duty point is its design flow.

    Solves once with the pumps as pure resistances, reads the head the system
    needs at design flow, then builds a quadratic through
    (0, 1.25*duty), (duty flow, duty head), (1.6*duty flow, 0.55*duty head) -
    an ordinary pump shape. Returns the duty head in metres.

    Deriving it beats guessing: change a pipe size or a plate and the pump
    follows, and nobody has to notice.
    """
    net = circuit.network
    n_pumps = len(circuit.pump_branches)
    if not n_pumps:
        raise ValueError(f"{circuit.name} has no pump branches")

    share = circuit.design_flow_kgs / n_pumps
    total_dp = 0.0

    # Walk one representative path: the pressure a pump must supply is the sum
    # of losses around the loop at design flow. Taking it from the solved
    # network with pumps absent is simpler and equivalent.
    for branch in net.branches:
        flow = _representative_flow(circuit, branch.name, share)
        dp, _ = branch.evaluate(flow)
        if dp > 0:
            total_dp += dp
    # That sums every parallel branch as though in series, which overstates by
    # the number of parallel paths. Correct it by taking the mean over the
    # parallel groups instead - see _loop_pressure for the honest version.
    total_dp = _loop_pressure(circuit, share)

    rho = float(fluid.density(circuit.temperature_c))
    duty_head_m = total_dp * margin / (rho * 9.80665)
    duty_q = share * 3600.0 / rho

    curve = PumpCurve.from_points([
        (0.0, duty_head_m * 1.25),
        (duty_q, duty_head_m),
        (duty_q * 1.6, duty_head_m * 0.55),
    ])
    for name in circuit.pump_branches:
        net.branch(name).elements.append(
            Pump(curve, speed=1.0, max_flow_m3h=duty_q * 1.6, name=f"{name}_pump")
        )
    return duty_head_m


def _representative_flow(circuit: Circuit, branch_name: str, pump_share: float) -> float:
    """Design flow through a branch, from where it sits in the circuit."""
    if circuit.name == "facility":
        if "_PLATE_FAC" in branch_name or branch_name.startswith("CDU"):
            return facility_flow_kgs(circuit.temperature_c) / (POD_COUNT * CDU_PER_POD)
        if branch_name.startswith("CH") or branch_name.startswith("CWP"):
            return pump_share
        return facility_flow_kgs(circuit.temperature_c)
    if "_COLDPLATE" in branch_name or "_DROP_" in branch_name:
        return rack_flow_kgs(circuit.temperature_c)
    if "CDU" in branch_name:
        return circuit.design_flow_kgs / CDU_PER_POD
    return circuit.design_flow_kgs


def _loop_pressure(circuit: Circuit, pump_share: float) -> float:
    """Losses around one representative circuit at design flow [Pa].

    One path only - source to plate and back - rather than every branch, because
    parallel branches each see the same pressure and summing them would size the
    pump for a loop that does not exist.
    """
    net = circuit.network
    total = 0.0
    if circuit.name == "facility":
        path = ["FAC_RETURN_MAIN", "RETURN_TO_SUCTION", "CWP-1_SUCTION",
                "CWP-1_UNIT", "CWP-1_DISCHARGE", "PUMP_DISCHARGE_MANIFOLD",
                "CH1_FEED", "CH1_UNIT", "CH1_SUPPLY", "FAC_SUPPLY_MAIN",
                "CDU1_FAC_IN", "CDU1_PLATE_FAC", "CDU1_FAC_OUT"]
    else:
        pod = int(circuit.name[-1]) - 1
        n = pod * CDU_PER_POD + 1
        rack = f"P{pod + 1}A01"
        path = [f"CDU{n}_PLATE_TCS", f"CDU{n}_TCS_OUT", f"P{pod + 1}_TCS_SUPPLY_HDR",
                f"{rack}_DROP_S", f"{rack}_COLDPLATE", f"{rack}_DROP_R",
                f"P{pod + 1}_TCS_RETURN_HDR", f"CDU{n}_TCS_IN"]
    for name in path:
        branch = net.branch(name)
        dp, _ = branch.evaluate(_representative_flow(circuit, name, pump_share))
        total += max(dp, 0.0)
    return total


def solve_circuit(circuit: Circuit, initial=None, strict: bool = True) -> Solution:
    return solve(circuit.network, initial, strict=strict)


def report(circuit: Circuit, sol: Solution) -> dict:
    """Per-branch flow and per-node pressure, in the units an engineer reads."""
    rho = float(fluid.density(circuit.temperature_c))
    branches = {}
    for br in circuit.network.branches:
        m = sol.flows[br.name]
        dp, _ = br.evaluate(m)
        area = None
        pipes = [e for e in br.elements if isinstance(e, Pipe)]
        if pipes:
            area = pipes[0].area_m2
        branches[br.name] = {
            "m_dot_kgs": round(float(m), 4),
            "q_m3h": round(float(m) * 3600.0 / rho, 2),
            "velocity_ms": round(float(m) / (rho * area), 3) if area else None,
            "dp_kpa": round(float(dp) / 1000.0, 2),
            "dn": pipes[0].diameter_m * 1000 if pipes else None,
            "segment": circuit.segment_of_branch.get(br.name),
        }
        for valve in br.valves():
            branches[br.name]["valve"] = valve.name
            branches[br.name]["valve_position"] = valve.position
            branches[br.name]["valve_authority"] = round(
                valve_authority(circuit.network, sol, br.name, valve.name), 3)
    meters = {}
    for tag, branch_name in circuit.meters.items():
        m = sol.flows[branch_name]
        meters[tag] = {
            "branch": branch_name,
            "m_dot_kgs": round(m, 4),
            "q_m3h": round(m * 3600.0 / rho, 2),
            "l_per_s": round(m * 1000.0 / rho, 2),
        }

    pumps = {}
    for name in circuit.pump_branches:
        br = circuit.network.branch(name)
        m = sol.flows[name]
        dp, _ = br.evaluate(m)
        pump = br.pumps()[0] if br.pumps() else None
        pumps[name] = {
            "m_dot_kgs": round(m, 3),
            "q_m3h": round(m * 3600.0 / rho, 1),
            "suction_kpa": round(sol.pressures[br.from_node] / 1000.0, 1),
            "discharge_kpa": round(sol.pressures[br.to_node] / 1000.0, 1),
            "head_kpa": round((sol.pressures[br.to_node] - sol.pressures[br.from_node]) / 1000.0, 1),
            "head_m": round((sol.pressures[br.to_node] - sol.pressures[br.from_node]) / (rho * 9.80665), 2),
            "speed": float(pump.speed) if pump else 1.0,
            "shaft_kw": round(pump.shaft_kw(m, circuit.temperature_c), 1) if pump else None,
        }

    # Velocity check. Worth its own line rather than being left to a reader's
    # eye: the facility mains were drawn DN150 because that was RD110's only DN
    # callout, which put 540 m3/h through them at 8.5 m/s - four times the
    # design velocity that had been sitting in loop_params.json unused. Correct
    # sizing took the facility pump from 42.9 m of head to 23.0 m and its shaft
    # power from 30 kW to 16.8 kW.
    over = sorted(
        (name, abs(d["velocity_ms"]))
        for name, d in branches.items()
        if d["velocity_ms"] is not None and abs(d["velocity_ms"]) > V_MAX
    )

    pressures = [v for v in sol.pressures.values()]
    return {
        "velocity_limit_ms": V_MAX,
        "over_velocity": [{"branch": n, "velocity_ms": round(v, 2)} for n, v in over],
        "max_velocity_ms": round(max(
            (abs(d["velocity_ms"]) for d in branches.values()
             if d["velocity_ms"] is not None), default=0.0), 2),
        "circuit": circuit.name,
        "meters": meters,
        "pumps": pumps,
        "pressure_min_kpa": round(min(pressures) / 1000.0, 1),
        "pressure_max_kpa": round(max(pressures) / 1000.0, 1),
        "temperature_c": circuit.temperature_c,
        "design_flow_kgs": round(circuit.design_flow_kgs, 3),
        # Sum the pumps, never one of them times their count. Scaling a single
        # pump's flow is right only while every pump is doing the same thing,
        # and the scenarios that matter are exactly the ones where they are not:
        # with CWP-3 off, the survivors ride up their curves and the shortcut
        # reported 193 kg/s against a 152 kg/s design - a rise, on losing a pump.
        "total_flow_kgs": round(float(sum(sol.flows[n] for n in circuit.pump_branches)), 3),
        "pump_flow_spread": round(
            max(sol.flows[n] for n in circuit.pump_branches)
            - min(sol.flows[n] for n in circuit.pump_branches), 3),
        "reverse_flow_branches": sorted(
            br.name for br in circuit.network.branches if sol.flows[br.name] < -1e-3),
        "converged": sol.converged,
        "iterations": sol.iterations,
        "pressure_kpa": {k: round(v / 1000.0, 2) for k, v in sol.pressures.items()},
        "branches": branches,
        "warnings": sol.warnings,
    }


def build_and_solve(lay: LoopLayout | None = None) -> dict[str, tuple[Circuit, Solution]]:
    """Every circuit, sized and solved at design conditions."""
    out = {}
    for name, circuit in build_circuits(lay).items():
        size_pumps(circuit)
        out[name] = (circuit, solve_circuit(circuit))
    return out


# -- scenarios -----------------------------------------------------------
# Each is a list of (kind, target, value) actions applied before solving.
# Precomputed in Python and handed to the viewer as a table, for the same reason
# the chiller sweep is: one implementation of the physics, and JavaScript only
# looks things up.
SCENARIOS = [
    {
        "key": "design",
        "label": "Design — everything running",
        "note": "All 48 rack valves open, 3 of 4 chillers and their pumps running, "
                "9 CDUs on. The point of comparison for every row below.",
        "actions": [],
    },
    {
        "key": "rack_valve_shut",
        "label": "One rack valve shut (PCV01)",
        "note": "Flow redistributes across the other 15 racks in the pod and the "
                "CDU pumps ride up their curves. Nothing models that chain; it "
                "falls out of solving the network.",
        "actions": [("valve", "PCV01", 0.0)],
    },
    {
        "key": "rack_valve_half",
        "label": "One rack valve at 50 % lift (PCV01)",
        "note": "The equal-percentage plug at half lift passes far less than half "
                "its rated Kv, which is the characteristic doing its job.",
        "actions": [("valve", "PCV01", 0.5)],
    },
    {
        "key": "cdu_trip",
        "label": "One CDU tripped (CDU-1 pump off)",
        "note": "Two CDUs carry the pod. N+1 by design, so the pod keeps its flow "
                "only if the survivors have the head for it.",
        "actions": [("pump_speed", "CDU1_PLATE_TCS", 0.0)],
    },
    {
        "key": "cwp_trip",
        "label": "One chilled water pump tripped (CWP-3)",
        "note": "The facility loop loses a third of its pumping. Watch the CDU "
                "flow meters, not the total: an even split is the thing that fails.",
        # The isolating valve shuts with the pump, as a plant controller would.
        # Leaving CV03 open makes the solver drive flow backwards through the
        # idle chiller's evaporator - a real commissioning error, and one this
        # model will show if anyone wants to see it.
        "actions": [("pump_speed", "CWP-3_UNIT", 0.0), ("valve", "CV03", 0.0)],
    },
    {
        "key": "cwp_turndown",
        "label": "Pumps at 80 % speed",
        "note": "Affinity laws: flow falls with speed, head with its square, and "
                "shaft power with its cube. The reason variable-speed pumping is "
                "worth the drive.",
        "actions": [("all_pump_speed", "", 0.8)],
    },
]


def apply_actions(circuits: dict, actions) -> None:
    """Apply a scenario's actions across every circuit that owns the target."""
    for kind, target, value in actions:
        for circuit in circuits.values():
            net = circuit.network
            if kind == "valve":
                for br in net.branches:
                    for valve in br.valves():
                        if valve.name == target:
                            valve.position = value
            elif kind == "pump_speed":
                if any(b.name == target for b in net.branches):
                    for pump in net.branch(target).pumps():
                        pump.speed = value
            elif kind == "all_pump_speed":
                for name in circuit.pump_branches:
                    for pump in net.branch(name).pumps():
                        pump.speed = value
            else:
                raise ValueError(f"unknown scenario action {kind!r}")


def run_scenarios(lay: LoopLayout | None = None) -> list[dict]:
    """Solve every scenario, from a freshly built and sized plant each time.

    Rebuilt rather than reset between scenarios: the actions mutate valve
    positions and pump speeds in place, and carrying one scenario's state into
    the next is the kind of bug that produces plausible wrong numbers.
    """
    lay = lay or build_layout()
    out = []
    for scenario in SCENARIOS:
        circuits = build_circuits(lay)
        for circuit in circuits.values():
            size_pumps(circuit)
        apply_actions(circuits, scenario["actions"])

        reports = {}
        sols = {}
        for name, circuit in circuits.items():
            sol = solve_circuit(circuit, strict=False)
            sols[name] = sol
            reports[name] = report(circuit, sol)

        out.append({
            "key": scenario["key"],
            "label": scenario["label"],
            "note": scenario["note"],
            "circuits": reports,
            "heat": heat_balance(circuits, sols),
            "plates": plate_table(circuits, sols),
        })
    return out


def segment_flows(scenario_report: dict) -> dict:
    """Layout segment name -> flow and pressure drop, across all four circuits.

    What the viewer colours pipes by. Branches that run through equipment have
    no segment and are left out.
    """
    out = {}
    for circuit in scenario_report["circuits"].values():
        for branch, data in circuit["branches"].items():
            if data.get("segment"):
                out[data["segment"]] = {
                    "m_dot_kgs": data["m_dot_kgs"],
                    "q_m3h": data["q_m3h"],
                    "velocity_ms": data["velocity_ms"],
                    "dp_kpa": data["dp_kpa"],
                    "circuit": circuit["circuit"],
                }
    return out


# -- electrical load to heat to liquid -----------------------------------

# RD110's IT. The 87 % liquid share applies to the AI racks only; the networking
# racks are air-cooled, so their whole load is on the air side.
AI_RACK_ELECTRICAL_KW = 142.0
NETWORK_RACK_ELECTRICAL_KW = 15.0
NETWORK_RACK_COUNT = 48
LIQUID_FRACTION = 0.87

# Pump efficiency, for turning hydraulic work into shaft power. Grade L.
PUMP_EFFICIENCY = 0.75

# Below this share of design flow a rack is reported as starved rather than as a
# temperature. dT = Q/(m*cp) goes to infinity as flow goes to zero, so a shut
# valve produced "6,820 K" - arithmetically correct and useless: there is no
# steady state to report, because the rack is heating up rather than settling.
# Phase 2's thermal capacitance turns that into the real answer, a 30-60 s ramp
# to a trip. Until then, saying "starved" is the honest output.
STARVED_FLOW_FRACTION = 0.25

# Cold plate inlet limit to judge against. Grade L: RD110 gives 40 C as its TCS
# design supply and states no allowable maximum, and loop_params.json keeps
# temperatures.cold_plate_max_inlet_c pending for exactly this reason. 45 C is a
# placeholder to make the verdict visible, not a vendor figure.
TCS_RETURN_LIMIT_C = 60.0


def electrical_balance(rack_kw: float | None = None,
                       liquid_fraction: float | None = None) -> dict:
    """Where the IT electrical load goes, before any flow is solved.

    Every watt into a rack leaves it as heat - a server does no net work on its
    surroundings - so the split is not an efficiency, it is a routing question:
    which coolant carries it out. RD110 answers it at 87/13 for the GB300 racks,
    and both arguments default to its figures.

    Parametric because the two numbers are the ones a reader most wants to move:
    the rack a hall is designed around changes generation to generation, and the
    liquid share is the open item in loop_params.json.
    """
    rack_kw = AI_RACK_ELECTRICAL_KW if rack_kw is None else rack_kw
    liquid_fraction = LIQUID_FRACTION if liquid_fraction is None else liquid_fraction
    ai_total = rack_kw * RACK_COUNT
    net_total = NETWORK_RACK_ELECTRICAL_KW * NETWORK_RACK_COUNT
    to_liquid = ai_total * liquid_fraction
    to_air = ai_total * (1.0 - liquid_fraction) + net_total
    return {
        "rack_kw": round(rack_kw, 2),
        "liquid_fraction": round(liquid_fraction, 4),
        "rack_liquid_kw": round(rack_kw * liquid_fraction, 2),
        "it_electrical_kw": round(ai_total + net_total, 1),
        "ai_racks_kw": round(ai_total, 1),
        "network_racks_kw": round(net_total, 1),
        "to_liquid_kw": round(to_liquid, 1),
        "to_air_kw": round(to_air, 1),
        "liquid_share": round(to_liquid / (ai_total + net_total), 4),
        "ai_rack_count": RACK_COUNT,
        "network_rack_count": NETWORK_RACK_COUNT,
        "network_rack_kw": NETWORK_RACK_ELECTRICAL_KW,
        "note": (
            "All of it becomes heat; the split is which coolant carries it out. "
            "The 87 % applies to the AI racks only - the networking racks are "
            "air-cooled, so their full 720 kW is on the air side."
        ),
    }


def heat_balance(circuits: dict, solutions: dict) -> dict:
    """What the solved flows can actually carry, and at what temperature rise.

    This is where the hydraulics start paying for themselves. Each rack has a
    fixed heat to shed, so its temperature rise is whatever its *solved* flow
    forces:

        dT = Q / (m_dot * cp)

    Shut a valve and the flow falls, so dT rises and the rack's outlet climbs -
    at constant supply temperature, because the CDU is holding that. A rack at
    70 % of design flow runs a 14.3 K rise instead of 10 K. That is the failure
    the model exists to show, and it needs no thermal transport to state at
    steady state; Phase 2 adds the transient and the CDU's response.

    Pump work is counted too. It is not a rounding error to be waved away: the
    pumps put their shaft power into the fluid, so the chillers reject the IT
    liquid load *plus* the pumping, and a plant sized on the IT load alone is
    short by that much.
    """
    elec = electrical_balance()
    cp_tcs = float(fluid.cp(TCS_SUPPLY_C))

    racks = {}
    worst = None
    for name, circuit in circuits.items():
        if name == "facility":
            continue
        sol = solutions[name]
        for br in circuit.network.branches:
            if not br.name.endswith("_COLDPLATE"):
                continue
            rack = br.name[: -len("_COLDPLATE")]
            m = sol.flows[br.name]
            # float() throughout: the solution's flows come from a numpy array,
            # and numpy.bool_ is not JSON serialisable - which only surfaces when
            # the manifest is written, a long way from here.
            fraction = float(m) / rack_flow_kgs(TCS_SUPPLY_C)
            starved = bool(fraction < STARVED_FLOW_FRACTION)
            dt = RACK_LIQUID_KW * 1000.0 / (float(m) * cp_tcs) if m > 1e-4 else None
            row = {
                "m_dot_kgs": round(float(m), 4),
                "flow_fraction": round(fraction, 4),
                "duty_kw": round(RACK_LIQUID_KW, 2),
                "starved": starved,
                # Reported only where a steady state exists. See
                # STARVED_FLOW_FRACTION for why a number here would be a lie.
                "delta_t_k": None if starved or dt is None else round(dt, 2),
                "outlet_c": None if starved or dt is None else round(TCS_SUPPLY_C + dt, 2),
                "over_limit": bool(dt is not None and not starved
                                   and TCS_SUPPLY_C + dt > TCS_RETURN_LIMIT_C),
                "pod": name,
            }
            racks[rack] = row
            if worst is None:
                worst = rack
            else:
                current = racks[worst]
                # Starved beats hot; among the hot, the hottest wins.
                if row["starved"] and not current["starved"]:
                    worst = rack
                elif row["starved"] == current["starved"]:
                    if (row["delta_t_k"] or 0) > (current["delta_t_k"] or 0):
                        worst = rack

    # Pump shaft power, and the hydraulic work that lands in the fluid.
    pump_shaft_kw = 0.0
    pump_fluid_kw = 0.0
    for name, circuit in circuits.items():
        sol = solutions[name]
        rho = float(fluid.density(circuit.temperature_c))
        for branch_name in circuit.pump_branches:
            br = circuit.network.branch(branch_name)
            m = sol.flows[branch_name]
            rise = sol.pressures[br.to_node] - sol.pressures[br.from_node]
            hydraulic_kw = max(0.0, m * rise / rho) / 1000.0
            pump_fluid_kw += hydraulic_kw
            pump_shaft_kw += hydraulic_kw / PUMP_EFFICIENCY

    carried_kw = sum(r["duty_kw"] for r in racks.values())
    rejected_kw = carried_kw + pump_fluid_kw

    # The facility side has a temperature rise of its own, and it was invisible
    # until this was added. Losing a chilled water pump costs 30 % of facility
    # flow and starves no rack, so the verdict said PASS - while the facility
    # return climbed from 47 C to over 51 C, which raises the chiller return,
    # the CDU approach and eventually the cold plate inlet. The TCS-side verdict
    # cannot see that; this line can.
    fac = circuits.get("facility")
    facility = None
    if fac is not None:
        m_fac = sum(solutions["facility"].flows[n] for n in fac.pump_branches)
        cp_fac = float(fluid.cp(FACILITY_SUPPLY_C))
        dt_fac = rejected_kw * 1000.0 / (m_fac * cp_fac) if m_fac > 1e-3 else None
        facility = {
            "m_dot_kgs": round(float(m_fac), 3),
            "flow_fraction": round(float(m_fac) / facility_flow_kgs(FACILITY_SUPPLY_C), 4),
            "delta_t_k": round(dt_fac, 2) if dt_fac else None,
            "return_c": round(FACILITY_SUPPLY_C + dt_fac, 2) if dt_fac else None,
            "design_return_c": FACILITY_RETURN_C,
            "over_design": bool(dt_fac and FACILITY_SUPPLY_C + dt_fac > FACILITY_RETURN_C + 0.5),
        }

    starved = sorted(k for k, v in racks.items() if v["starved"])
    over = sorted(k for k, v in racks.items() if v["over_limit"])
    if starved:
        verdict, reason = "FAIL", f"{len(starved)} rack(s) starved: {', '.join(starved[:4])}"
    elif over:
        verdict, reason = "FAIL", (
            f"{len(over)} rack(s) over the {TCS_RETURN_LIMIT_C:.0f} C return limit: "
            f"{', '.join(over[:4])}")
    elif facility and facility["over_design"]:
        verdict, reason = "WARN", (
            f"racks are fine, but facility return is {facility['return_c']} C against "
            f"{FACILITY_RETURN_C:.0f} C design - the chillers and the CDU approach "
            f"see that before the racks do")
    else:
        verdict, reason = "PASS", (
            f"worst rise {racks[worst]['delta_t_k']} K at {racks[worst]['outlet_c']} C")

    return {
        "electrical": elec,
        "racks": racks,
        "verdict": verdict,
        "verdict_reason": reason,
        "facility": facility,
        "starved_racks": starved,
        "over_limit_racks": over,
        "return_limit_c": TCS_RETURN_LIMIT_C,
        "worst_rack": worst,
        "worst_delta_t_k": racks[worst]["delta_t_k"] if worst else None,
        "design_delta_t_k": LOOP_DELTA_T,
        "carried_by_liquid_kw": round(carried_kw, 1),
        "pump_hydraulic_kw": round(pump_fluid_kw, 2),
        "pump_shaft_kw": round(pump_shaft_kw, 1),
        "rejected_at_chillers_kw": round(rejected_kw, 1),
        "closure_kw": round(rejected_kw - carried_kw - pump_fluid_kw, 6),
        "note": (
            "Chillers reject the IT liquid load plus the pumping that moved it. "
            "Sizing on the IT load alone is short by the pump work."
        ),
    }


def heat_constants() -> dict:
    """Everything a caller needs to redo the heat sums at a different load.

    The hydraulics do not depend on the heat load at all: flow is set by the
    pumps and the valve positions, so changing load moves the temperature rise
    and leaves every flow where it was. That is what makes load and liquid share
    live inputs rather than another axis to precompute - `dT = Q/(m cp)` at the
    already-solved flow.

    The caveat belongs next to the numbers, so `note` carries it: this answers
    "the plant as built, carrying a different load", not "the plant you would
    build for that load". At a much larger rack the pipes and pumps would be
    sized differently, and the model will happily show a 30 K rise rather than
    telling you to use bigger pipe.
    """
    return {
        "cp_tcs": round(float(fluid.cp(TCS_SUPPLY_C)), 1),
        "cp_facility": round(float(fluid.cp(FACILITY_SUPPLY_C)), 1),
        "tcs_supply_c": TCS_SUPPLY_C,
        "tcs_return_c": TCS_RETURN_C,
        "facility_supply_c": FACILITY_SUPPLY_C,
        "facility_return_c": FACILITY_RETURN_C,
        "return_limit_c": TCS_RETURN_LIMIT_C,
        "starved_flow_fraction": STARVED_FLOW_FRACTION,
        "design_delta_t_k": LOOP_DELTA_T,
        "design_rack_kw": AI_RACK_ELECTRICAL_KW,
        "design_liquid_fraction": LIQUID_FRACTION,
        "ai_rack_count": RACK_COUNT,
        "network_rack_count": NETWORK_RACK_COUNT,
        "network_rack_kw": NETWORK_RACK_ELECTRICAL_KW,
        "pump_efficiency": PUMP_EFFICIENCY,
        "note": (
            "Flow is set by the pumps and valves, not by the load, so varying "
            "load moves the temperature rise and nothing else. This is the plant "
            "as built carrying a different load - not the plant you would build "
            "for that load."
        ),
    }


# -- heat exchangers -----------------------------------------------------

# UA multipliers to tabulate, so a reviewer can ask "what if the plate were
# better or worse" without re-solving anything. 1.0 is RD110's own plate.
UA_SCALES = (0.5, 0.6, 0.7, 0.85, 1.0, 1.2, 1.4, 1.6)


def design_cdu_flows() -> tuple[float, float]:
    """Secondary (hot) and facility (cold) design flow through one CDU plate."""
    return (pod_flow_kgs(TCS_SUPPLY_C) / CDU_PER_POD,
            facility_flow_kgs(FACILITY_SUPPLY_C) / (POD_COUNT * CDU_PER_POD))


def cdu_plate() -> PlateExchanger:
    """The CDU plate, calibrated from RD110's four temperatures.

    Secondary 50 -> 40 C against 37 C facility in, at design flows. The plate
    therefore reproduces RD110's stated 3 K terminal approach by construction
    rather than being asserted to have it.
    """
    hot, cold = design_cdu_flows()
    return PlateExchanger.calibrate_from_temperatures(
        "Motivair MCDU-50 plate", TCS_RETURN_C, TCS_SUPPLY_C, FACILITY_SUPPLY_C, hot, cold)


def plate_table(circuits: dict, solutions: dict) -> dict:
    """Plate state per CDU per UA scale, for every solved scenario.

    Load-independent by construction: eps, C_min and C_hot depend only on the
    flows and the plate, so the browser can vary the IT load live and get the
    approach from `Q / (eps * C_min)` without any of the model moving to
    JavaScript. That division and the one below it are an energy balance, not a
    second implementation.
    """
    plate = cdu_plate()
    out: dict[str, dict] = {}
    for name, circuit in circuits.items():
        if name == "facility":
            continue
        sol = solutions[name]
        fac = solutions["facility"]
        for br in circuit.network.branches:
            if not br.name.endswith("_PLATE_TCS"):
                continue
            n = br.name.split("_")[0].replace("CDU", "")
            hot = float(sol.flows[br.name])
            cold_branch = f"CDU{n}_PLATE_FAC"
            cold = float(fac.flows[cold_branch]) if cold_branch in fac.flows else 0.0
            # A list aligned to UA_SCALES, not a dict keyed by the float. Keying
            # by str(scale) put "1.0" in the JSON, and JavaScript's String(1.0)
            # is "1" - so the browser looked up a key that was not there and got
            # undefined for the design case, the one that matters most.
            rows = []
            for scale in UA_SCALES:
                plate.ua_scale = scale
                s = plate.state(abs(hot), abs(cold))
                c_h, _ = plate.capacities_kw_per_k(abs(hot), abs(cold))
                rows.append({
                    "ua_scale": scale,
                    "ua_kw_per_k": s["ua_kw_per_k"],
                    "effectiveness": s["effectiveness"],
                    "ntu": s["ntu"],
                    "cr": s["cr"],
                    "c_min_kw_per_k": s["c_min_kw_per_k"],
                    "c_hot_kw_per_k": round(c_h, 2),
                })
            out[f"CDU-{n}"] = {
                "hot_flow_kgs": round(abs(hot), 3),
                "cold_flow_kgs": round(abs(cold), 3),
                "pod": name,
                "by_ua_scale": rows,  # aligned to UA_SCALES
            }
    return out


def hx_model() -> dict:
    """How the heat exchangers are modelled, as data the viewer can display."""
    plate = cdu_plate()
    hot, cold = design_cdu_flows()
    s = plate.state(hot, cold)
    duty = RACK_LIQUID_KW * RACK_COUNT / (POD_COUNT * CDU_PER_POD)
    return {
        "method": "effectiveness-NTU, counterflow",
        "relations": [
            "1/UA = 1/(c_h m_h^0.8) + 1/(c_c m_c^0.8)",
            "NTU = UA/C_min,  Cr = C_min/C_max",
            "eps = (1-exp[-NTU(1-Cr)]) / (1-Cr exp[-NTU(1-Cr)])",
            "Q = eps C_min (T_h,in - T_c,in)",
        ],
        "calibrated_from": (
            "RD110's four temperatures: secondary 50 -> 40 C against 37 C "
            "facility in, at design flow. The 3 K terminal approach follows "
            "rather than being assumed."
        ),
        "design": {
            "duty_kw_per_cdu": round(duty, 1),
            "hot_flow_kgs": round(hot, 3),
            "cold_flow_kgs": round(cold, 3),
            "ua_kw_per_k": s["ua_kw_per_k"],
            "ntu": s["ntu"],
            "cr": s["cr"],
            "effectiveness": s["effectiveness"],
            "inlet_delta_k": round(plate.inlet_delta_for_duty_k(duty, hot, cold), 2),
            "terminal_approach_k": round(plate.terminal_approach_k(duty, hot, cold), 2),
        },
        "flow_exponent": 0.8,
        "ua_scales": list(UA_SCALES),
        "caveats": [
            "Cr is 0.997 - both sides carry the same duty at the same rise - and "
            "that is the worst case for a counterflow plate: eps caps at "
            "NTU/(1+NTU), so 1.6x the area buys only about 1 K of approach.",
            "UA falls with flow as m^0.8 on each side, so a CDU at 70 % flow is "
            "not 70 % of a heat exchanger.",
            "Rated pressure drops (60 kPa per side) are grade L placeholders "
            "pending the MCDU-50 datasheet, as is the dry cooler coil.",
        ],
    }


def fluid_properties(temps=(0.0, 10.0, 20.0, 30.0, 37.0, 40.0, 47.0, 50.0, 60.0)) -> dict:
    """PG25 properties at the temperatures this plant runs at.

    Stated rather than adjustable in the browser, deliberately: viscosity enters
    the pressure drop, so changing the fluid re-solves every circuit. It is a
    Python-side edit in fluid.py, not a slider - and the properties are generic
    published 25 % PG data (grade L), not a datasheet for the AU01 fill.
    """
    rows = []
    for t_c in temps:
        rows.append({
            "t_c": t_c,
            "rho": round(float(fluid.density(t_c)), 1),
            "cp": round(float(fluid.cp(t_c)), 0),
            "k": round(float(fluid.conductivity(t_c)), 4),
            "mu_mpas": round(float(fluid.viscosity(t_c)) * 1000.0, 3),
            "prandtl": round(float(fluid.prandtl(t_c)), 2),
        })
    return {
        "name": "PG25 - 25 % propylene glycol by volume",
        "confidence": "L",
        "source": "generic published 25 % PG tables (ASHRAE Fundamentals ch. 31; Dow DOWFROST agrees within a few percent)",
        "caveat": (
            "Generic glycol data, NOT a datasheet for the AU01 fill. Replace "
            "before quoting pressure drop to a vendor. Viscosity is the property "
            "that must not be held constant: it is 5x higher at 0 C than 60 C, "
            "and it enters the pressure drop through the Reynolds number."
        ),
        "loop_temperatures": {
            "facility_supply_c": FACILITY_SUPPLY_C,
            "facility_return_c": FACILITY_RETURN_C,
            "tcs_supply_c": TCS_SUPPLY_C,
            "tcs_return_c": TCS_RETURN_C,
        },
        "rows": rows,
    }
