# Liquid twin — two-loop DLC cooling

A real-time model of the AU01 liquid side: DLC cold plates → CDU → dry coolers.
Companion to [`../digital-twin/`](../digital-twin/), which does the air side of
the same hall and which this deliberately does not touch.

**Status: Phase 1 of 6.** The hydraulic core is built and tested. Thermal
transport, heat exchangers, controls and the viewer are not.
[SPEC.md](SPEC.md) is the design; this README is what exists.

```bash
pip install -e '.[dev]'
python3 -m pytest loop/tests -q      # 61 tests
```

## Why this is not CFD

Reducing each heat exchanger to a couple of numbers leaves no flow field to
resolve. What remains is a 1-D hydraulic network plus 1-D thermal transport — a
few hundred states, solved in milliseconds. OpenFOAM keeps one optional offline
role: if manifold maldistribution is ever in question, a steady run of the
header yields per-branch loss coefficients that become constants here. Same
CFD → reduced-model contract the air twin already uses.

## The one decision everything rests on

**Flow is an output, never an input.**

The air-side CFD prescribes it — `case-au01/0.orig/U` puts a fixed mass flow on
the fan wall patches. That is right for a steady design-point study and useless
for asking what a closed valve does, because a prescribed flow cannot
redistribute. So every flow here is solved for:

| Element | Relation |
|---|---|
| Pipe, fittings | Darcy–Weisbach, friction factor from the current flow and temperature |
| Valve | `K = 1.296e9 / (Kv(x)² ρ)`, Kv from the characteristic at lift x |
| Pump | quadratic head curve, affinity-scaled for speed |
| Heat exchanger side | one loss coefficient from the rated pressure drop |
| Node | `Σ ṁ_in = Σ ṁ_out` |

Shut one of four identical rack branches and, with nothing else told to change:

```
all open     total 22.777 kg/s    5.694 each
rack1 shut   total 17.369 kg/s    0.007 / 5.787 / 5.787 / 5.787
```

Total falls 23.7 %, not the 25 % that was removed, because the pump rides up its
curve — and the three survivors each gain 1.6 %. Nobody modelled that. It falls
out of solving the network, and it is the reason the solver is built this way.

## What is here

```
liquid-twin/
├── SPEC.md              the design, all six phases
├── loop/dtloop/
│   ├── loop_params.json every number, with source and confidence  (Phase 0)
│   ├── params.py        the loader that refuses to invent one
│   ├── fluid.py         PG25 properties
│   ├── components.py    pipe, valve, pump, resistance
│   ├── network.py       nodes, branches, incidence
│   └── hydraulics.py    the Newton solve                          (Phase 1)
└── loop/tests/          61 tests
```

## Phase 0: what is not known yet

`loop_params.json` holds every number the model uses together with where it came
from and how much to trust it. Twenty-four are still null, and `params.py`
**raises rather than substituting a default** when one is asked for:

```
>>> LoopParams.load().get("temperatures.tcs_supply_c")
PendingReference: temperatures.tcs_supply_c is not yet known - pending RD110
  CDU secondary outlet / cold plate inlet
```

A default would be a number nobody chose, indistinguishable downstream from one
somebody did. The model's entire temperature basis is currently pending the
Schneider RD110 design package, and that had better be loud.

Two open items are worth naming here rather than leaving in the JSON:

- **All nine temperatures await RD110.** Until then no temperature-dependent
  result means anything. The two that decide the most are the CDU approach and
  the dry cooler approach at design ambient: together they set the floor on cold
  plate inlet temperature, `T_amb + approach_dc + approach_cdu`.
- **The air/liquid split does not add up.** 68 kW liquid + 36.75 kW air is a
  65 % liquid share, against `FINDINGS-AU01.md` §365's "up to 95 % heat
  capture". Both cannot be right, so `dlc_capture_fraction` is deliberately
  null. It must be resolved before this model is used for capacity work.

## Phase 1: the hydraulic core

Newton on the branch flows and node pressures together, `J = [[-D, -A], [Aᵀ, 0]]`,
solved dense. Measured worst case — a valve toggling fully open and shut every
frame:

| branches | iterations | per frame | headroom at 10 Hz |
|---|---|---|---|
| 7 | 7 | 1.2 ms | 81× |
| 27 | 6 | 4.4 ms | 22× |
| 99 | 6 | 16.7 ms | 6× |

The cost is the Python loop over branches, not the linear algebra; vectorising
it is the first optimisation if the network grows.

### Three things the physics forced

Each of these was found by a test failing, and each is documented where it lives:

1. **A shut valve is a large finite resistance, never infinite and never a
   removed branch.** Infinite gives a singular Jacobian; removing the branch
   would discard the thermal states whose temperature rise is the thing the
   scenario exists to show. At `K = 1e10`, a shut valve passes 0.03 % of its
   open flow.

2. **The pump curve is clipped monotonic.** A quadratic through three ordinary
   datasheet points — (0, 50), (100, 45), (200, 25) — peaks at 16.7 m³/h, half a
   metre above shutoff. A network solve is only well posed when every branch's
   pressure is monotonic in its flow, and that half-metre is enough to put the
   iteration into a clean two-point limit cycle. Head is clipped flat over the
   rising stretch, and the reverse-flow region is a steep line rather than the
   quadratic, which otherwise supplies a second, entirely spurious root at large
   negative flow. The solver found that root before the clip existed.

3. **The Newton step is globalised by backtracking, not by a step clamp.** A
   fixed clamp caps how far an iteration travels without asking whether
   travelling there helped, and it was what produced the limit cycle above.

### And one result that contradicts the intuition

Cold PG25 is five times as viscous as hot, and it does cost more pressure in the
pipework — about 7 % between 40 °C and 5 °C. But **total loop flow barely moves**,
under 1 % across 5–45 °C, because the cold plates are modelled as fixed loss
coefficients that do not know the temperature, and denser cold fluid turns the
same pump head in metres into more pascals, pushing the other way.

So a system-level flow change is not a good check that viscosity is wired up.
`test_cold_fluid_costs_more_pressure_in_the_pipework` is; the cancellation is
pinned by its own test so that Phase 2 notices if it changes.

## Next

Phase 2 is thermal transport — pipes discretised into finite volumes so a load
step sends a visible thermal front down the run, plus one ε-NTU component
serving as both CDU and dry cooler. It needs the RD110 temperatures to say
anything meaningful, but not to be built.
