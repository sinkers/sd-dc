"""Build a SYNTHETIC data set for the test suite.

Nothing here is transcribed from AS/NZS 3008.1.1 or AS/NZS 3000. The numbers
are invented but internally consistent, which is all the unit tests need: they
exercise lookup direction, factor composition, the Table 5.2 size break and
the arithmetic. Verification against the standard's published answers happens
separately, against data/ once it is populated - see tests/test_verification.py.
"""
from pathlib import Path

HERE = Path(__file__).parent
SIZES = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300,
         400, 500, 630]
RHO_CU_OHM_KM_MM2 = 17.241     # ohm/km for 1 mm^2 at 20 C
ALPHA = 3.93e-3
X_OHM_KM = 0.08


def r20(size):
    return RHO_CU_OHM_KM_MM2 / size


def r_at(size, t):
    return r20(size) * (1 + ALPHA * (t - 20))


def write(name, header, rows, banner=""):
    lines = [f"# SYNTHETIC TEST FIXTURE - not from any standard. {banner}", header]
    lines += rows
    (HERE / name).write_text("\n".join(lines) + "\n")


# Keyed by TABLE and ARRANGEMENT, per M4 Rev B section 4.4. `cores_loaded` is
# not an axis of any base table and is gone; insulation and construction are
# resolved into the table by R-TBL-1. Arrangement ratios loosely mimic the real
# spread so a test that confuses two columns fails visibly.
ARRANGEMENT_RATIO = {
    "air_spaced": 1.27,
    "air_spaced_from_surface": 1.075,
    "air_touching": 1.00,
    "air_exposed_to_sun": 0.80,
    "enclosed_conduit_in_air": 0.85,
    "insulation_partial": 0.68,
    "buried_direct": 0.89,
    "buried_conduit_shared": 0.75,
    "buried_conduit_single_way": 0.84,
}
MULTICORE_RATIO = {k: v for k, v in ARRANGEMENT_RATIO.items()
                   if k not in ("air_spaced_from_surface", "insulation_partial",
                                "buried_conduit_shared", "buried_conduit_single_way")}
MULTICORE_RATIO["buried_conduit"] = 0.78
MULTICORE_RATIO["insulation_partial_unenclosed"] = 0.68

ccc_rows = []
SINGLE_CORE_TABLES = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")
MULTICORE_TABLES = ("3.15", "3.16", "3.17", "3.18", "3.19", "3.20")
BASE_K = {"3.9": 10.5, "3.10": 11.2, "3.11": 12.0, "3.12": 10.5,
          "3.13": 11.2, "3.14": 12.0, "3.15": 10.5, "3.16": 11.2,
          "3.17": 12.0, "3.18": 10.5, "3.19": 11.2, "3.20": 12.0}

for table in SINGLE_CORE_TABLES + MULTICORE_TABLES:
    ratios = (ARRANGEMENT_RATIO if table in SINGLE_CORE_TABLES
              else MULTICORE_RATIO)
    base_k = BASE_K[table]
    for arr, ratio in ratios.items():
        for s in SIZES:
            cu = round(base_k * s ** 0.62 * ratio, 1)
            ccc_rows.append(f"{table},{arr},Cu,{s:g},{cu}")
            ccc_rows.append(f"{table},{arr},Al,{s:g},{round(cu * 0.79, 1)}")
write("ccc.csv", "table,arrangement,material,size_mm2,current_a", ccc_rows)

# R-REF-1: one headnote carries BOTH datums for every table in the family.
write("ccc_reference.csv",
      "table,reference_ambient_air_c,reference_ambient_soil_c,"
      "reference_soil_resistivity_km_w,reference_depth_m,max_conductor_c",
      [f"{t},40,25,1.2,0.5,{c}" for t, c in
       (("3.9", 75), ("3.10", 90), ("3.11", 110), ("3.12", 75),
        ("3.13", 90), ("3.14", 110), ("3.15", 75), ("3.16", 90),
        ("3.17", 110), ("3.18", 75), ("3.19", 90), ("3.20", 110))])

write("cf_ambient_air.csv", "max_conductor_c,ambient_c,cf",
      ["90,25,1.15", "90,30,1.10", "90,35,1.05", "90,40,1.00",
       "90,45,0.94", "90,50,0.87",
       "75,25,1.20", "75,30,1.13", "75,35,1.07", "75,40,1.00",
       "75,45,0.92", "75,50,0.83"])

write("cf_ambient_soil.csv", "max_conductor_c,ambient_c,cf",
      ["90,15,1.07", "90,20,1.04", "90,25,1.00", "90,30,0.96", "90,35,0.92"])

# `grouping_code` carries the table and item identity -- support type, spacing
# and row count -- and `circuits` is the banded axis. BAND_CEIL: the factor
# falls as circuits rise, so the count rounds UP (R-BAND-2).
#
# A single circuit is NOT 1.00 on a tray (R-ADM-6): the support type alone
# moves it 0.95 to 1.00, which is what makes support_type a required input.
write("cf_grouping.csv", "grouping_code,circuits,cf",
      ["default,1,1.00", "default,2,0.85", "default,3,0.79", "default,4,0.75",
       "default,6,0.72", "default,9,0.70",
       # Table 3.34 shape: perforated tray, touching, one row
       "t334_perforated_touching_1row,1,0.97",
       "t334_perforated_touching_1row,2,0.89",
       "t334_perforated_touching_1row,3,0.87",
       # ... the same, circuits spaced one diameter apart
       "t334_perforated_spaced_1row,1,0.97",
       "t334_perforated_spaced_1row,2,0.93",
       "t334_perforated_spaced_1row,3,0.91",
       # unperforated and ladder differ at ONE circuit
       "t334_unperforated_touching_1row,1,0.95",
       "t334_unperforated_touching_1row,2,0.84",
       "t334_ladder_touching_1row,1,1.00",
       "t334_ladder_touching_1row,2,0.88",
       # two rows of trays
       "t334_perforated_touching_2row,2,0.85",
       # Table 3.33 item: single layer fixed under a ceiling, touching
       "t333_ceiling_touching,1,0.95"])

# R-ADM-1: 3.46 (buried direct) is keyed by size band, 3.47 (in an underground
# enclosure) by core count. Different axes, one file, kept apart by `table`.
write("cf_depth.csv", "table,axis_value,depth_m,cf",
      ["3.46,small,0.5,1.00", "3.46,small,0.8,0.97", "3.46,small,1.2,0.95",
       "3.46,large,0.5,1.00", "3.46,large,0.8,0.96", "3.46,large,1.0,0.92",
       "3.46,large,1.2,0.93",
       "3.47,single_core,0.5,1.00", "3.47,single_core,1.0,0.93",
       "3.47,multicore,0.5,1.00", "3.47,multicore,1.0,0.94"])

write("cf_soil_resistivity.csv", "arrangement,resistivity_km_w,cf",
      [f"{a},{r},{cf}"
       for a in ("buried_direct", "buried_conduit_shared",
                 "buried_conduit_single_way", "buried_conduit")
       for r, cf in ((0.8, 1.10), (1.2, 1.00), (1.5, 0.94), (2.0, 0.87))])

# No cf_thermal_insulation.csv: thermal insulation contact is a base-rating
# COLUMN, not a correction factor (M4 Rev B finding 4). A factor for it is
# refused by rating_factors.admit(), not defaulted to 1.00.

write("cf_harmonic.csv",
      "third_harmonic_fraction,basis,band_upper_fraction,cf",
      ["0.0,phase,0.15,1.00",
       "0.15,phase,0.33,0.86",
       "0.33,neutral,0.45,0.86",
       "0.45,neutral,1.00,1.00"],
      banner="Band STRUCTURE mirrors Clause 3.5.9; values are placeholders.")

# Axes follow the standard: `form_class` splits fixed wiring (Tables 4.1,
# 4.5-4.9) from flexible (4.2, 4.10), and `construction` names the table
# rather than the formation, because a.c. resistance has no formation axis.
res = []
for s in SIZES:
    for t in (20, 75, 90):
        res.append(f"fixed,multicore-circular,Cu,{s:g},{t},{round(r_at(s, t), 5)}")
write("resistance.csv",
      "form_class,construction,material,size_mm2,temperature_c,r_ohm_per_km",
      res)

# Reactance carries an insulation axis in Tables 4.1/4.2 -- three classes,
# coarser than the Insulation enum. The fixture holds one class; the real
# data holds all three.
write("reactance.csv",
      "form_class,construction,insulation_class,size_mm2,x_ohm_per_km",
      [f"fixed,circular,XLPE,{s:g},{X_OHM_KM}" for s in SIZES])

# The 0.8 column mirrors the real tables' CONVENTION, not the naive formula:
# it is the worst case over load power factors in [0.8, 1.0], which equals the
# Max value while the cable power factor stays at or above 0.8 and only becomes
# sqrt(3)(0.8R + 0.6X) below that. See spec-exchange/ANS-001 R-VD-2. Building
# the fixture the naive way would make the suite assert a rule the standard
# does not follow.
mv = []
for s in SIZES:
    r = r_at(s, 90)
    z = (r * r + X_OHM_KM * X_OHM_KM) ** 0.5
    for pf in (0.8, 0.9):
        if pf == 0.8:
            val = (3 ** 0.5 * z if r / z >= 0.8
                   else 3 ** 0.5 * (0.8 * r + 0.6 * X_OHM_KM))
        else:
            sin = (1 - pf * pf) ** 0.5
            val = 3 ** 0.5 * (r * pf + X_OHM_KM * sin)
        # rounded to 3 significant figures, as published tables are
        mv.append(f"3ph,Cu,XLPE/90,multicore,{s:g},{pf},{float(f'{val:.3g}')}")
write("mv_per_a_m.csv",
      "system,material,insulation,construction,size_mm2,power_factor,mv_per_a_m", mv)

write("sc_limits.csv",
      "insulation,size_max_mm2,initial_temperature_c,final_temperature_c",
      ["PVC/75,300,70,160", "PVC/75,1000000000,70,140",
       "PVC/90,300,90,160", "PVC/90,1000000000,90,140",
       "XLPE/90,1000000000,90,250", "EPR/110,1000000000,110,250"],
      banner="Encodes the 300 mm2 thermoplastic break.")

pe = []
for s in SIZES:
    pe.append(f"Cu,{s:g},{s if s <= 16 else (16 if s <= 35 else s / 2):g}")
write("pe_min_size.csv", "material,active_size_mm2,pe_size_mm2", pe)

write("max_zs.csv", "device,rating_a,disconnection_time_s,max_zs_ohm",
      ["MCB-C,100,0.4,0.23", "MCB-C,63,0.4,0.36", "MCB-C,32,0.4,0.72",
       "MCB-C,100,5,0.23"])

print("fixtures written to", HERE)
