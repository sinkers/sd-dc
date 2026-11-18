"""Simulations: each one wires a set of components into a topology.

A simulation module exposes ID, TITLE, describe() and simulate(scenario_id,
params). Register it here and the service and the viewer pick it up.
"""

from . import bess_dr

SIMS = {bess_dr.ID: bess_dr}
