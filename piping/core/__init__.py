"""Pure-Python pipe routing: specs, validation and one router. No FreeCAD.

Everything here works on plain tuples in millimetres so that the service, the
tests and an agent can route a pipe without a CAD kernel. FreeCAD only enters
when solids are built from the centreline this package returns.
"""
from .specs import PipeSpec, list_specs, spec_for
from .geom import Box, Nozzle
from .validate import validate_route
from .router import RouteOptions, route_pipe, route_network, centreline_parts

__all__ = ["PipeSpec", "list_specs", "spec_for", "Box", "Nozzle",
           "validate_route", "RouteOptions", "route_pipe", "route_network",
           "centreline_parts"]
