"""Rack fan model: how much air each rack moves.

The CFD represents server fans as a proportional momentum source holding a
target velocity against whatever back pressure the room presents, with the
target derived from the heat load and the design temperature rise:

    m_design = Q / (cp * dT_design)

Real racks are stiffer than the CFD's stiffness-50 source (which overshot its
target by 4-46%), so the ROM keeps the same design relation and absorbs the
discrepancy into one calibrated multiplier. The consequence that matters for
the twin: rack airflow follows IT load, so a load drop reduces airflow and the
achieved rise stays roughly constant rather than the rise collapsing.
"""

from __future__ import annotations

import numpy as np

from .constants import CP
from .params import RomParams
from .topology import HallSpec


def design_mass_flow(spec: HallSpec) -> np.ndarray:
    """Nameplate airflow per rack [kg/s] at design load and design rise."""
    return np.array(
        [r.design_kw * 1000.0 / (CP * spec.design_delta_t_k) for r in spec.racks]
    )


def rack_mass_flow(
    spec: HallSpec, params: RomParams, rack_kw: np.ndarray
) -> np.ndarray:
    """Airflow per rack [kg/s] at the current load.

    Fans track load down to a floor set as a fraction of design flow, so an
    idling rack still moves air. A rack with zero design load (a spare) moves
    no air at all.
    """
    design = design_mass_flow(spec)
    demand = np.asarray(rack_kw, dtype=float) * 1000.0 / (CP * spec.design_delta_t_k)
    floor = params.fan_flow_floor * design
    return params.fan_flow_multiplier * np.maximum(demand, floor)


def module_mass_flow(
    spec: HallSpec,
    unit_on: np.ndarray,
    airflow_fraction: np.ndarray,
    supply_temp_k: np.ndarray,
    params: RomParams | None = None,
) -> np.ndarray:
    """Airflow per fan-wall module [kg/s].

    Volumetric flow is a nameplate property of the fan at a given speed, so it
    is converted to mass flow at the module's own discharge temperature.
    `airflow_fraction` is the VFD turndown, which is the twin's fan-speed knob.
    """
    from .constants import density

    mult = params.module_flow_multiplier if params else 1.0
    out = np.zeros(len(spec.modules))
    for i, m in enumerate(spec.modules):
        if not unit_on[i]:
            continue
        q_m3s = m.airflow_m3h / 3600.0 * float(airflow_fraction[i])
        out[i] = q_m3s * density(float(supply_temp_k[i])) * mult
    return out
