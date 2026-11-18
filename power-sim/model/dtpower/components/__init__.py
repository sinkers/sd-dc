"""Components. Each one is independent of any particular simulation: it declares
its IndustroML asset kind, its ports, its parameter schema and its role in the
network, steps itself, and reports a snapshot. A simulation decides how they
are wired; dtpower.network decides the order they step in.

Roles, and the step signature each implies:

    source      step(net_kw, price, dt, up)      the grid; absorbs the balance
    bus         (none)                           a node where feeders meet
    conversion  step(out_kw, dt, up) -> in_kw    UPS, and later PDU, transformer
    storage     step(request_kw, dt, up) -> kW   BESS; positive supplies the bus
    load        step(t, dt, price) -> kW         GPU servers
    controller  prepare(...), decide(...)        sets a storage asset's power
    generator   control(...), dispatch(...)      alternate supply to a bus, via its transfer switch
"""

from .battery import Battery
from .bess import BESS
from .busbar import Busbar
from .controller import PriceController
from .converter import Converter
from .generator import Generator
from .gpu_load import GPUServerLoad
from .grid import Grid
from .price import PriceSignal
from .ups import UPS

# IndustroML asset kind -> component. A model's assets are instantiated
# through this table, so a new component is usable by every simulation once it
# is registered here.
REGISTRY = {c.kind: c for c in (Grid, Busbar, BESS, UPS, GPUServerLoad, PriceController, Generator)}

__all__ = ["Battery", "BESS", "Busbar", "Converter", "Generator", "GPUServerLoad", "Grid", "PriceController",
           "PriceSignal", "UPS", "REGISTRY"]
