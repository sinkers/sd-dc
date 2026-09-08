"""Generate SYNTHETIC stand-ins for the five licensed data files.

The numbers here are invented. They are not from AS/NZS 3008.1.1, AS/NZS 3000
or any other standard, and no design may be issued from them. Their only job is
to let `import cable_sizing`, the engine and CI run on a checkout that has no
licensed data -- so a contributor can work on the code without a licence, and
so a CI job can prove the package still assembles.

They are internally consistent enough to exercise every code path: capacity
rises with size, resistance falls with size and rises with temperature, and
correction factors sit in (0, 1].

Regenerate with:  python3 fixtures/make_fixtures.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [1, 1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240,
         300, 400, 500, 630]
TEMPS = [25, 30, 45, 60, 75, 80, 90, 110]
WARN = ("SYNTHETIC FIXTURE. Invented numbers, not from any standard. "
        "Never issue a design from this file.")


def r_at(size, temp, k=18.0):
    """Falls with size, rises with temperature. Shape only, not real data."""
    return round(k / size * (1 + 0.004 * (temp - 20)), 4)


def x_at(size):
    return round(0.10 - 0.02 * (size / 630.0), 4)


def main():
    os.makedirs(HERE, exist_ok=True)
    S = lambda s: str(int(s)) if s == int(s) else str(s)

    # -- impedance ---------------------------------------------------------
    imp = {"_SYNTHETIC": True, "_WARNING": WARN, "standard": "SYNTHETIC",
           "tables": {}}
    imp["tables"]["4.1"] = {
        "title": "SYNTHETIC reactance", "verified": False, "complete": True,
        "single_core": {
            "spacing_correction_ohm_km": {"0.5D": 0.02, "1D": 0.04, "2D": 0.07},
            "data": {f: {i: {S(s): x_at(s) for s in SIZES}
                         for i in ("Elastomer", "PVC", "XLPE")}
                     for f in ("trefoil", "flat_touching")}},
        "multicore": {"data": {"circular": {i: {S(s): round(x_at(s) * 0.8, 4)
                                                for s in SIZES}
                                            for i in ("Elastomer", "PVC", "XLPE")},
                               "shaped": {i: {S(s): round(x_at(s) * 0.75, 4)
                                              for s in SIZES if s >= 16}
                                          for i in ("PVC", "XLPE")}}},
        "notes": [WARN]}
    # 4.2 flexible, 4.3 MIMS, 4.4 aerial. Present so the flexible, MIMS and
    # aerial construction paths resolve instead of raising a bare KeyError --
    # the synthetic smoke run is what found that gap.
    imp["tables"]["4.2"] = {
        "title": "SYNTHETIC flexible reactance", "verified": False,
        "complete": True, "notes": [WARN],
        "single_core": {"data": {f: {i: {S(s): round(x_at(s) * 1.05, 4)
                                         for s in SIZES}
                                     for i in ("Elastomer", "PVC", "XLPE")}
                                 for f in ("trefoil", "flat_touching")}},
        "multicore": {"data": {"circular": {i: {S(s): round(x_at(s) * 0.85, 4)
                                                for s in SIZES}
                                            for i in ("Elastomer", "PVC", "XLPE")}}}}
    imp["tables"]["4.3"] = {
        "title": "SYNTHETIC MIMS reactance", "verified": False, "complete": True,
        "notes": [WARN],
        "data": {v: {"single_core_trefoil": {S(s): round(x_at(s) * 0.9, 4)
                                             for s in SIZES if s <= 400},
                     "multicore": {S(s): round(x_at(s) * 0.7, 4)
                                   for s in SIZES if s <= 25}}
                 for v in ("500V", "750V")}}
    imp["tables"]["4.4"] = {
        "title": "SYNTHETIC aerial reactance", "verified": False,
        "complete": True, "notes": [WARN],
        "data": {c: {S(s): round(0.30 - 0.00005 * s, 4) for s in SIZES}
                 for c in ("single_phase_and_trefoil", "three_cables_flat")}}
    for tid, mat_k in (("4.5", {"Copper": 18.0, "Aluminium": 29.0}),
                       ("4.6", {"Copper": 17.8, "Aluminium": 28.8}),
                       ("4.7", {"Copper": 18.1, "Aluminium": 29.1}),
                       ("4.8", {"Copper": 17.9, "Aluminium": 28.9})):
        imp["tables"][tid] = {
            "title": f"SYNTHETIC resistance {tid}", "verified": False,
            "complete": True, "temperatures_c": TEMPS, "notes": [WARN],
            "data": {m: {str(t): {S(s): r_at(s, t, k) for s in SIZES}
                         for t in TEMPS} for m, k in mat_k.items()}}
    for tid in ("4.11", "4.12", "4.13"):
        imp["tables"][tid] = {
            "title": f"SYNTHETIC resistance {tid}", "verified": False,
            "complete": True, "temperatures_c": TEMPS, "notes": [WARN],
            "data": {m: {str(t): {S(s): r_at(s, t, 18.5) for s in SIZES}
                         for t in TEMPS} for m in ("Copper", "Aluminium")}}
    imp["tables"]["4.10"] = {
        "title": "SYNTHETIC flexible resistance", "verified": False,
        "complete": True, "temperatures_c": TEMPS, "notes": [WARN],
        "data": {w: {str(t): {S(s): r_at(s, t, 19.0) for s in SIZES}
                     for t in TEMPS} for w in ("single_core", "multicore")}}

    # -- voltage drop ------------------------------------------------------
    vc = {"_SYNTHETIC": True, "_WARNING": WARN, "standard": "SYNTHETIC",
          "tables": {}}
    for tid in ("4.14", "4.15", "4.17", "4.19", "4.22", "4.24", "4.27"):
        vc["tables"][tid] = {
            "title": f"SYNTHETIC Vc {tid}", "verified": False, "complete": True,
            "temperatures_c": TEMPS, "notes": [WARN],
            "data": {str(t): {S(s): {"max": round(1.732 * r_at(s, t), 4),
                                     "pf_0_8": round(1.732 * r_at(s, t) * 0.95, 4)}
                              for s in SIZES} for t in TEMPS}}

    # -- short circuit -----------------------------------------------------
    sc = {"_SYNTHETIC": True, "_WARNING": WARN, "standard": "SYNTHETIC",
          "tables": {"5.2": {
              "title": "SYNTHETIC short-circuit limits", "verified": False,
              "complete": True, "notes": [WARN],
              "by_material": {c: ({"<=300": 160.0, ">300": 140.0}
                                  if c.startswith("V") else 250.0)
                              for c in ("V-75", "V-90", "TP 90", "V-90HT",
                                        "X-90", "X-90UV", "X-HF-90", "X-HF-110",
                                        "R-EP-90", "R-CPE-90", "R-HF-90",
                                        "R-CSP-90", "R-HF-110", "R-E-110",
                                        "PE", "LLDPE")}}}}

    # -- ratings -----------------------------------------------------------
    ratings = {"_SYNTHETIC": True, "_WARNING": WARN, "verified": False,
               "source": "SYNTHETIC", "families": {"XHF110_4C1CE_CU": {
                   "name": "SYNTHETIC single-core", "insulation": "X-HF-110",
                   "conductor": "Copper", "class": 5, "max_temp_c": 110,
                   "voltage_kv": 0.6, "colour": "#b5721f", "loaded_cores": 4,
                   "arrangement": "SYNTHETIC", "rating_table": "SYNTHETIC",
                   "geometry_source": "SYNTHETIC",
                   "ratings_a": {S(s): round(12 * s ** 0.62, 1) for s in SIZES},
                   "earth_a": {S(s): min(120, max(2.5, s / 2)) for s in SIZES}}}}

    # -- AS/NZS 3000 bodies ------------------------------------------------
    ref = {"_SYNTHETIC": True, "_WARNING": WARN,
           "limiting_temperatures_as3000_table_3_2": {"data": {
               c: {"normal_use_c": n, "max_permissible_c": m,
                   "min_ambient_c": -15, "family": f}
               for c, n, m, f in (("V-75", 75, 75, "thermoplastic"),
                                  ("V-90", 75, 90, "thermoplastic"),
                                  ("V-90HT", 75, 105, "thermoplastic"),
                                  ("TP-90", 75, 90, "thermoplastic"),
                                  ("X-90", 90, 90, "xlpe"),
                                  ("X-90UV", 90, 90, "xlpe"),
                                  ("X-HF-90", 90, 90, "xlpe"),
                                  ("X-HF-110", 110, 110, "xlpe"),
                                  ("R-EP-90", 90, 90, "elastomeric"),
                                  ("R-S-150", 150, 150, "elastomeric"),
                                  ("MIMS", 100, 250, "mims"),
                                  ("PE", 70, 70, "other"))}},
           "min_conductor_size_as3000_table_3_3": {"data": {
               "other_circuits": {"area_mm2": 1.0},
               "socket_outlets": {"area_mm2": 2.5},
               "signal_and_relay_control": {"area_mm2": 0.5}}},
           "conductor_colours_as3000_table_3_4": {"data": {
               "protective_earth": {"colour": "green/yellow"},
               "neutral": {"colour": "black"},
               "active": {"colour": "red", "three_phase": ["red", "white", "blue"]},
               "equipotential_bonding": {"colour": "green/yellow"}}},
           "earth_sizes_as3000_table_5_1": {
               "data": {S(s): max(2.5, round(s / 2, 1))
                                 for s in SIZES},
               "large_conductor_fraction": {"Copper": 0.5, "Aluminium": 0.5,
                                            "applies_above_mm2": 800}},
           "ambient_rating_factors_air": {"data": {
               str(t): round(1.0 - 0.02 * (t - 40), 3) for t in
               (25, 30, 35, 40, 45, 50, 55, 60)}},
           "grouping_rating_factors": {"data": {
               str(n): round(1.0 - 0.06 * (n - 1), 3) for n in range(1, 10)}},
           "ac_dc_resistance_ratio": {"data": {S(s): 1.0 for s in SIZES}},
           "reactance_ohm_km": {"data": {},
                                "nominal_by_construction_ohm_km":
                                    {"single_core": 0.09, "multicore": 0.08},
                                "fallback_ohm_km": 0.08},
           "vd_simplified_as3000_table_c8": {"data": {
               S(s): {"single_phase": round(45 * s, 0),
                      "three_phase": round(90 * s, 0)} for s in SIZES[:12]}},
           "aluminium_earthing_as3000_clause_5_3_2_1_2": {"data": {
               "solid_required_at_or_below_mm2": 10,
               "min_main_earthing_mm2": 16,
               "not_underground_or_damp": True,
               "damp_exception": True,
               "connection_methods_section_3": True,
               "corrosion_prevention_required": True,
               "note": WARN}},
           **{f"conduit_fill_as3000_table_c{n}": {"data": {}, "conduit_columns": []}
              for n in (10, 11, 12)}}

    # -- vendor catalogues -------------------------------------------------
    # Nexans, Ezystrut and Tricab data now lives in S3, so the credential-free
    # run needs stand-ins for these too or nothing can be sized.
    cat = {"_SYNTHETIC": True, "_WARNING": WARN, "cables": {
        "XLPE_SDI_CU": {
            "name": "SYNTHETIC XLPE single core copper", "voltage_kv": 0.6,
            "insulation": "X-90 XLPE", "sheath": "PVC", "conductor": "Copper",
            "class": 2, "max_temp_c": 90, "colour": "#1a1a1a",
            "sizes": {S(s): {
                "i_3ph_touching_a": round(12 * s ** 0.62, 1),
                "i_3ph_spaced_a": round(13 * s ** 0.62, 1),
                "i_3ph_conduit_a": round(10 * s ** 0.62, 1),
                "i_3ph_buried_a": round(11 * s ** 0.62, 1),
                "r_dc_ohm_km": r_at(s, 20), "od_mm": round(4 + s ** 0.5, 1),
                "weight_kg_km": round(20 + 11 * s, 0),
                "bend_radius_mm": round(8 * (4 + s ** 0.5), 0)} for s in SIZES}},
        "XLPE_SDI_AL": {
            "name": "SYNTHETIC XLPE single core aluminium", "voltage_kv": 0.6,
            "insulation": "X-90 XLPE", "sheath": "PVC", "conductor": "Aluminium",
            "class": 2, "max_temp_c": 90, "colour": "#8a8a8a",
            "sizes": {S(s): {
                "i_3ph_touching_a": round(9 * s ** 0.62, 1),
                "i_3ph_spaced_a": round(10 * s ** 0.62, 1),
                "i_3ph_conduit_a": round(8 * s ** 0.62, 1),
                "i_3ph_buried_a": round(9 * s ** 0.62, 1),
                "r_dc_ohm_km": r_at(s, 20, 29.0), "od_mm": round(4 + s ** 0.5, 1),
                "weight_kg_km": round(15 + 4 * s, 0),
                "bend_radius_mm": round(8 * (4 + s ** 0.5), 0)}
                for s in SIZES if s >= 16}},
        "LFH_SINGLE": {
            "name": "SYNTHETIC LFH single core", "voltage_kv": 0.6,
            "insulation": "X-HF-110", "sheath": "-", "conductor": "Copper",
            "class": 5, "max_temp_c": 110, "colour": "#b5721f",
            "sizes": {S(s): {
                "i_3ph_touching_a": round(13 * s ** 0.62, 1),
                "i_3ph_spaced_a": round(14 * s ** 0.62, 1),
                "i_3ph_conduit_a": round(11 * s ** 0.62, 1),
                "i_3ph_buried_a": round(12 * s ** 0.62, 1),
                "r_dc_ohm_km": r_at(s, 20), "od_mm": round(4 + s ** 0.5, 1),
                "weight_kg_km": round(20 + 11 * s, 0),
                "bend_radius_mm": round(8 * (4 + s ** 0.5), 0)} for s in SIZES}}},
        "derating_factors": {
            "ambient_temp": {str(t): round(1.0 - 0.02 * (t - 40), 3)
                             for t in (25, 30, 35, 40, 45, 50, 55, 60)},
            "grouping": {str(n): round(1.0 - 0.06 * (n - 1), 3)
                         for n in range(1, 10)}}}

    tray = {"_SYNTHETIC": True, "_WARNING": WARN, "source": "SYNTHETIC",
            "trays": [{"part": f"SYN-{w}", "width_mm": w, "depth_mm": 50,
                       "type": "cable tray"} for w in
                      (75, 100, 150, 225, 300, 450, 600)]}

    tri = {"_SYNTHETIC": True, "_WARNING": WARN, "source": "SYNTHETIC",
           "scope": "SYNTHETIC family metadata only", "families": [
               {"id": f"SYN-{n}", "name": f"SYNTHETIC family {n}",
                "voltage_kv": 0.6, "conductor": "Copper",
                "insulation": "X-90 XLPE", "per_size_data": False}
               for n in range(1, 4)]}

    for name, doc in (("cable_catalog.json", cat),
                      ("tray_catalogue.json", tray),
                      ("tricab_families.json", tri),
                      ("as3008_impedance_tables.json", imp),
                      ("as3008_vc_tables.json", vc),
                      ("as3008_short_circuit.json", sc),
                      ("as3008_ratings.json", ratings),
                      ("reference_tables.json", ref)):
        with open(os.path.join(HERE, name), "w") as fh:
            json.dump(doc, fh, indent=1)
        print(f"  wrote fixtures/{name}")


if __name__ == "__main__":
    main()
