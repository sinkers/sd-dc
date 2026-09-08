"""
IEC 60228 maximum DC conductor resistance at 20 C, ohm/km.

Used as a fallback when the cable catalogue entry does not carry measured
resistance values. These are the class 2 (stranded, non-flexible) figures and
already include the stranding lay factor, so they are slightly higher than the
resistivity-times-length calculation for a solid conductor of the same area.

Verified against `../cables/cable_catalog.json` XLPE_SDI_CU r_dc_ohm_km, which
matches this table exactly for every size 16-630 mm^2.
"""

R_DC_20_OHM_KM = {
    "Copper": {
        1.0: 18.1, 1.5: 12.1, 2.5: 7.41, 4.0: 4.61, 6.0: 3.08, 10.0: 1.83,
        16.0: 1.15, 25.0: 0.727, 35.0: 0.524, 50.0: 0.387, 70.0: 0.268,
        95.0: 0.193, 120.0: 0.153, 150.0: 0.124, 185.0: 0.0991,
        240.0: 0.0754, 300.0: 0.0601, 400.0: 0.0470, 500.0: 0.0366,
        630.0: 0.0283, 800.0: 0.0221, 1000.0: 0.0176,
    },
    "Aluminium": {
        16.0: 1.91, 25.0: 1.20, 35.0: 0.868, 50.0: 0.641, 70.0: 0.443,
        95.0: 0.320, 120.0: 0.253, 150.0: 0.206, 185.0: 0.164,
        240.0: 0.125, 300.0: 0.100, 400.0: 0.0778, 500.0: 0.0605,
        630.0: 0.0469, 800.0: 0.0367, 1000.0: 0.0291,
    },
}

# Nominal reactance by cable construction, ohm/km, used only when neither the
# catalogue nor AS/NZS 3008 Tables 4.1-4.2 supply a value. See the
# reactance_ohm_km block in reference_tables.json for provenance: the multicore
# figure is back-solved from AS/NZS 3000:2018 Table C8 and the single-core figure
# comes from the catalogue's own range. Reactance varies with formation and
# spacing, so prefer a tabulated value whenever one exists.
NOMINAL_X_BY_CONSTRUCTION = {
    "single_core": 0.08,
    "multicore": 0.107,
}

# Backwards-compatible default (single-core; every catalogue cable is single-core).
NOMINAL_X_OHM_KM = NOMINAL_X_BY_CONSTRUCTION["single_core"]


def nominal_x(construction="single_core"):
    """Nominal reactance in ohm/km for a cable construction."""
    if construction not in NOMINAL_X_BY_CONSTRUCTION:
        raise ValueError(
            f"construction must be one of {sorted(NOMINAL_X_BY_CONSTRUCTION)}")
    return NOMINAL_X_BY_CONSTRUCTION[construction]


def r_dc_20(conductor_name, area_mm2):
    """Maximum DC resistance at 20 C in ohm/km, or None if the size is unlisted."""
    return R_DC_20_OHM_KM.get(conductor_name, {}).get(float(area_mm2))
