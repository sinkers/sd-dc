"""PG25 thermophysical properties.

25 % propylene glycol by volume in water — the fluid in both loops.

The one property that must not be treated as constant is viscosity. It roughly
quintuples between 60 C and 0 C, and it enters the pressure drop through the
Reynolds number, so a constant-mu model gets cold-end hydraulics badly wrong.
That is the whole reason this module exists rather than a handful of constants
next to the solver, the way `dthall/constants.py` can get away with for air.

Provenance: the tables below are typical published values for 25 % PG by volume
(ASHRAE Handbook - Fundamentals, ch. 31, and the Dow DOWFROST product tables
agree to within a few percent over this range). They are **generic glycol
data, not a fluid datasheet for the AU01 fill**, and are marked confidence L in
loop_params.json for that reason. Replace them with the supplier's figures
before any pressure-drop number is quoted to a vendor.

Fits are exact cubic interpolants through the four tabulated points. Outside
0-60 C the fit is clamped to the end points rather than extrapolated: a cubic
extrapolates viscosity to nonsense within a few degrees, and silently returning
a negative viscosity is worse than pinning it.
"""

from __future__ import annotations

import numpy as np

# Tabulated at 0, 20, 40, 60 C. See the module docstring for provenance.
_T_C = np.array([0.0, 20.0, 40.0, 60.0])

_RHO = np.array([1030.0, 1024.0, 1015.0, 1004.0])       # kg/m3
_CP = np.array([3800.0, 3850.0, 3900.0, 3950.0])        # J/(kg K)
_K = np.array([0.442, 0.462, 0.478, 0.490])             # W/(m K)
_MU = np.array([4.60e-3, 2.20e-3, 1.35e-3, 0.92e-3])    # Pa s

T_MIN_C, T_MAX_C = float(_T_C[0]), float(_T_C[-1])

_RHO_FIT = np.polyfit(_T_C, _RHO, 3)
_CP_FIT = np.polyfit(_T_C, _CP, 3)
_K_FIT = np.polyfit(_T_C, _K, 3)
_MU_FIT = np.polyfit(_T_C, _MU, 3)

KELVIN = 273.15


def _clamped(t_c):
    """Clamp to the tabulated range. See the module docstring."""
    return np.clip(t_c, T_MIN_C, T_MAX_C)


def density(t_c):
    """Density [kg/m3]."""
    return np.polyval(_RHO_FIT, _clamped(t_c))


def cp(t_c):
    """Specific heat capacity [J/(kg K)]."""
    return np.polyval(_CP_FIT, _clamped(t_c))


def conductivity(t_c):
    """Thermal conductivity [W/(m K)]."""
    return np.polyval(_K_FIT, _clamped(t_c))


def viscosity(t_c):
    """Dynamic viscosity [Pa s]. The property that must not be held constant."""
    return np.polyval(_MU_FIT, _clamped(t_c))


def kinematic_viscosity(t_c):
    """Kinematic viscosity [m2/s]."""
    return viscosity(t_c) / density(t_c)


def prandtl(t_c):
    """Prandtl number [-]."""
    return cp(t_c) * viscosity(t_c) / conductivity(t_c)


def reynolds(m_dot, diameter_m: float, t_c) -> float:
    """Reynolds number for a mass flow in a round pipe.

    Re = rho v D / mu = 4 m_dot / (pi D mu), which is independent of density
    once written in terms of mass flow.
    """
    return 4.0 * np.abs(m_dot) / (np.pi * diameter_m * viscosity(t_c))


def to_kelvin(t_c):
    return t_c + KELVIN


def to_celsius(t_k):
    return t_k - KELVIN


def volumetric_m3h(m_dot, t_c) -> float:
    """Mass flow [kg/s] -> volumetric flow [m3/h], the unit vendors quote."""
    return m_dot * 3600.0 / density(t_c)


def mass_flow_kgs(m3h, t_c) -> float:
    """Volumetric flow [m3/h] -> mass flow [kg/s]."""
    return m3h * density(t_c) / 3600.0


def duty_kw(m_dot, delta_t_k, t_c) -> float:
    """Heat carried by a stream: Q = m cp dT, in kW."""
    return m_dot * cp(t_c) * delta_t_k / 1000.0


def flow_for_duty(duty_w: float, delta_t_k: float, t_c) -> float:
    """Mass flow a duty needs at a given rise: m = Q/(cp dT)."""
    if delta_t_k <= 0:
        raise ValueError("delta_t_k must be positive")
    return duty_w / (cp(t_c) * delta_t_k)
