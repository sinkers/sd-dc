"""dtloop - real-time model of the AU01 two-loop liquid cooling system.

DLC cold plates -> CDU -> dry coolers, as a hydraulic network plus thermal
transport. See SPEC.md for the physics and the phasing.

Phase 1 (here): fluid properties, hydraulic elements, the network, the solve.
Phase 2 onward: thermal transport, eps-NTU heat exchangers, controls, telemetry.
"""

from .components import (
    Element,
    Pipe,
    Pump,
    PumpCurve,
    Resistance,
    Valve,
)
from .hydraulics import (
    HydraulicSolveError,
    Solution,
    loop_closure_error,
    solve,
    valve_authority,
)
from .network import Branch, Network
from .params import LoopParams, PendingReference

__all__ = [
    "Branch", "Element", "HydraulicSolveError", "LoopParams", "Network",
    "PendingReference", "Pipe", "Pump", "PumpCurve", "Resistance", "Solution",
    "Valve", "loop_closure_error", "solve", "valve_authority",
]
