"""Air properties and shared constants.

Deliberately identical to the values used by the CFD dictionary generator
(cfd-cabinet-cooling/make_hall_dicts.py) so the ROM and the CFD it is
calibrated against cannot disagree on the thermodynamics.
"""

CP = 1005.0  # J/(kg K), dry air at constant pressure
R_AIR = 287.05  # J/(kg K)
P_ATM = 101325.0  # Pa
KELVIN = 273.15


def density(temp_k: float) -> float:
    """Air density from the ideal gas law at atmospheric pressure."""
    return P_ATM / (R_AIR * temp_k)


def to_kelvin(celsius):
    return celsius + KELVIN


def to_celsius(kelvin):
    return kelvin - KELVIN


def mass_flow_for_load(load_w: float, delta_t_k: float) -> float:
    """Airflow a rack needs to carry `load_w` at a `delta_t_k` rise: m = Q/(cp dT)."""
    if delta_t_k <= 0:
        raise ValueError("delta_t_k must be positive")
    return load_w / (CP * delta_t_k)


def m3h_to_kgs(m3h: float, temp_k: float) -> float:
    return m3h / 3600.0 * density(temp_k)


def kgs_to_m3h(kgs: float, temp_k: float) -> float:
    return kgs * 3600.0 / density(temp_k)
