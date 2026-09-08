"""dthall — real-time reduced-order digital twin of the AU01 hall.

The physics core (`topology`, `params`, `rackfan`, `gap`, `model`) has no I/O
and no engine dependency: it is a numpy state-space model that steps a hall
forward in time. Everything else — calibration, the simulation loop, the
WebSocket service, the debug view — is built on top of it.
"""

from .constants import CP, to_celsius, to_kelvin
from .model import HallModel, Inputs, Observables, State
from .params import RomParams
from .topology import HallSpec, from_cfd_export, from_hall_parameters

__all__ = [
    "CP",
    "HallModel",
    "HallSpec",
    "Inputs",
    "Observables",
    "RomParams",
    "State",
    "from_cfd_export",
    "from_hall_parameters",
    "to_celsius",
    "to_kelvin",
]
