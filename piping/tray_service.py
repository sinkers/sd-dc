"""Loads trays/service.py for the piping front ends.

The tray service lives in ../trays and reuses this package's router and
renderer; the MCP and REST servers here serve both, so an agent has one
server for routing. Both packages call their entry module service.py, so it
is loaded by path under this name rather than imported.
"""
import importlib.util
import os
import sys

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "trays", "service.py")
_spec = importlib.util.spec_from_file_location("tray_service_impl", _PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["tray_service_impl"] = _mod
_spec.loader.exec_module(_mod)

VERSION = _mod.VERSION
TRAY_SCHEMA = _mod.TRAY_SCHEMA
route_and_support = _mod.route_and_support
