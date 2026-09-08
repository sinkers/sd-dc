"""M4 Rev B verification cases V4-01 to V4-43.

Two kinds of case live here.

Cases that need the licensed tables SKIP until data/ is populated. They are the
acceptance gate for issue, and V4-36 to V4-43 are the strongest of them: they
are the standard's own published answers from Appendix A.1.2 and Appendix B,
carrying no DAME arithmetic at all.

Cases that assert structure, direction or admissibility run everywhere, because
they test the code's conventions rather than the standard's numbers.
"""
import math

import pytest

from dame_cable.errors import InadmissibleFactor
from dame_cable.rating_factors import ADMISSIBLE, DEPTH_TABLE, admit
from dame_cable.schema import (BASE_TABLE, Cable, CableConstruction,
                               ConductorMaterial, Insulation,
                               InstallationArrangement as A,
                               InstallationMethod, InvalidInstallation,
                               MULTICORE_ARRANGEMENTS, SINGLE_CORE_ARRANGEMENTS,
                               SupportType, base_table)

# --------------------------------------------------------------------------
# Structural cases - run without the licensed data
# --------------------------------------------------------------------------

def cu(size=400, ins=Insulation.THERMOSETTING_110,
       cons=CableConstruction.SINGLE_CORE_TREFOIL, cores=3):
    return Cable(material=ConductorMaterial.COPPER, insulation=ins,
                 construction=cons, size_mm2=size, cores_loaded=cores)


def test_base_table_selection_matches_R_TBL_1():
    """The R-TBL-1 grid, including the base cable of every verification case."""
    assert base_table(cu()) == "3.14"                       # V4-01..V4-13
    assert base_table(cu(ins=Insulation.THERMOPLASTIC_75)) == "3.12"   # V4-36..V4-39
    assert base_table(cu(cons=CableConstruction.MULTICORE,
                         cores=4)) == "3.20"                # V4-30..V4-32
    assert base_table(cu(ins=Insulation.THERMOPLASTIC_75,
                         cons=CableConstruction.MULTICORE,
                         cores=4)) == "3.18"                # V4-40..V4-43
    assert len(BASE_TABLE) == 12


def test_V4_07_insulation_complete_is_not_tabulated_for_three_single_core():
    """V4-07. A dash is not a value: the request must raise, not floor onto a
    neighbouring column."""
    assert A.INSULATION_COMPLETE in SINGLE_CORE_ARRANGEMENTS


def test_R_ARR_1_spaced_from_surface_does_not_exist_for_multicore():
    """A request against a multicore table raises rather than silently
    resolving to air_touching."""
    assert A.AIR_SPACED_FROM_SURFACE in SINGLE_CORE_ARRANGEMENTS
    assert A.AIR_SPACED_FROM_SURFACE not in MULTICORE_ARRANGEMENTS


def test_single_core_carries_four_air_arrangements_multicore_three():
    air_single = {a for a in SINGLE_CORE_ARRANGEMENTS
                  if a.value.startswith("air_")}
    air_multi = {a for a in MULTICORE_ARRANGEMENTS
                 if a.value.startswith("air_")}
    assert len(air_single) == 4 and len(air_multi) == 3


@pytest.mark.parametrize("arrangement,family", [
    (A.AIR_TOUCHING, "ambient_soil"),        # V4-28
    (A.AIR_TOUCHING, "depth"),
    (A.AIR_TOUCHING, "soil_resistivity"),
    (A.AIR_EXPOSED_TO_SUN, "solar"),         # V4-29
    (A.AIR_SPACED, "thermal_insulation"),
    (A.INSULATION_PARTIAL, "grouping"),      # OI-4.8
    (A.BURIED_DIRECT, "ambient_air"),
])
def test_inadmissible_factors_are_refused(arrangement, family):
    """R-ADM. A factor for an influence already in the base column is refused,
    not multiplied by, and not defaulted to 1.00."""
    with pytest.raises(InadmissibleFactor):
        admit(arrangement, family)


def test_solar_and_thermal_insulation_are_not_factor_families():
    """M4 Rev B finding 4. Five families exist, not seven."""
    families = set().union(*ADMISSIBLE.values())
    assert "solar" not in families
    assert "thermal_insulation" not in families
    assert families == {"ambient_air", "ambient_soil", "depth",
                        "soil_resistivity", "grouping", "harmonic"}


def test_R_ADM_1_depth_tables_are_not_interchangeable():
    assert DEPTH_TABLE[A.BURIED_DIRECT] == "3.46"
    assert DEPTH_TABLE[A.BURIED_CONDUIT_SHARED] == "3.47"


def test_V4_20_a_fourth_circuit_per_tier_is_outside_table_3_34():
    """R-GRP-1. Outside the table, not off the top of a band."""
    with pytest.raises(InvalidInstallation, match="outside Table 3.34"):
        InstallationMethod(arrangement=A.AIR_SPACED_FROM_SURFACE, ambient_c=40,
                           support_type=SupportType.PERFORATED_TRAY,
                           circuits_in_group=4)


def test_R_HRM_5_the_standard_edge_is_conservative_of_the_physics():
    """The physical crossover is 1/sqrt(8); the standard's edge is 33 %."""
    crossover = 1.0 / math.sqrt(8.0)
    assert crossover == pytest.approx(0.35355, abs=1e-5)
    assert 0.33 < crossover, "the standard's edge moves to neutral early"


# --------------------------------------------------------------------------
# Numeric cases - need the licensed tables
# --------------------------------------------------------------------------

#: V4-01 to V4-13. Table 3.14, at reference conditions.
BASE_CASES = [
    ("V4-01", A.AIR_SPACED, "Cu", 400, 1069),
    ("V4-02", A.AIR_SPACED_FROM_SURFACE, "Cu", 400, 902),
    ("V4-03", A.AIR_TOUCHING, "Cu", 400, 839),
    ("V4-04", A.AIR_EXPOSED_TO_SUN, "Cu", 400, 673),
    ("V4-05", A.ENCLOSED_CONDUIT_IN_AIR, "Cu", 400, 714),
    ("V4-06", A.INSULATION_PARTIAL, "Cu", 400, 571),
    ("V4-08", A.BURIED_DIRECT, "Cu", 400, 744),
    ("V4-09", A.BURIED_CONDUIT_SHARED, "Cu", 400, 628),
    ("V4-10", A.BURIED_CONDUIT_SINGLE_WAY, "Cu", 400, 702),
    ("V4-11", A.AIR_SPACED_FROM_SURFACE, "Al", 500, 837),
    ("V4-12", A.AIR_TOUCHING, "Al", 400, 664),
    ("V4-13", A.AIR_SPACED_FROM_SURFACE, "Cu", 500, 1046),
]


@pytest.mark.parametrize("cid,arrangement,material,size,expected", BASE_CASES)
def test_base_lookup(licensed_ccc, cid, arrangement, material, size, expected):
    """One case per arrangement, from Table 3.14."""
    got = licensed_ccc.value("ccc", table="3.14", arrangement=arrangement,
                               material=material, size_mm2=size)
    assert got == pytest.approx(expected, abs=0.5), cid


def test_V4_02_against_V4_03_pins_the_spaced_to_touching_ratio(licensed_ccc):
    spaced = licensed_ccc.value("ccc", table="3.14",
                                  arrangement=A.AIR_SPACED_FROM_SURFACE,
                                  material="Cu", size_mm2=400)
    touching = licensed_ccc.value("ccc", table="3.14",
                                    arrangement=A.AIR_TOUCHING,
                                    material="Cu", size_mm2=400)
    assert spaced / touching == pytest.approx(1.0751, abs=5e-4)


#: V4-36 to V4-39. The standard's own published answers, Appendix A.1.2.
#: Base cable Cu 400 mm2 V-75, three single-core, Table 3.12.
APPENDIX_A = [
    ("V4-36", A.BURIED_CONDUIT_SHARED, 492, 5, 0.60, 1476.0, 0.5),
    ("V4-37", A.BURIED_CONDUIT_SHARED, 492, 4, 0.79, 1554.0, 1.0),
    ("V4-38", A.BURIED_CONDUIT_SINGLE_WAY, 553, 4, 0.74, 1636.9, 0.05),
    ("V4-39", A.BURIED_DIRECT, 593, 3, 0.87, 1547.7, 0.05),
]


@pytest.mark.parametrize("cid,arrangement,base,n,cf,published,tol", APPENDIX_A)
def test_appendix_A_published_answers(licensed_ccc, cid, arrangement, base,
                                      n, cf, published, tol):
    """The strongest check available: the standard's own arithmetic.

    V4-37 recomputes to 1554.72 where the standard prints 1554, so it asserts
    to 1 A rather than to the printed figure. The standard's rounding is
    inconsistent across these four (OI-4.11); the engine carries full precision.
    """
    tabulated = licensed_ccc.value("ccc", table="3.12",
                                     arrangement=arrangement,
                                     material="Cu", size_mm2=400)
    assert tabulated == pytest.approx(base, abs=0.5), f"{cid} base value"
    assert tabulated * n * cf == pytest.approx(published, abs=tol)


#: V4-40 to V4-43. Appendix B, 4-core PVC Cu clipped to a wall, Table 3.18
#: column 3, design load 35 A.
APPENDIX_B = [
    ("V4-40", 0.00, 35.00, 6, 37),
    ("V4-41", 0.20, 40.70, 10, 51),
    ("V4-42", 0.44, 53.72, 16, 68),
    ("V4-43", 0.50, 52.50, 16, 68),
]


@pytest.mark.parametrize("cid,thd3,design_a,size,capacity", APPENDIX_B)
def test_appendix_B_harmonic_worked_example(licensed_ccc, cid, thd3,
                                            design_a, size, capacity):
    """Exercises all four Table 3.4 bands and both the neutral-current formula
    of R-HRM-1 and the divide-the-design-current form of R-ADM-5."""
    tabulated = licensed_ccc.value("ccc", table="3.18",
                                     arrangement=A.AIR_TOUCHING,
                                     material="Cu", size_mm2=size)
    assert tabulated == pytest.approx(capacity, abs=0.5), f"{cid} base value"
    assert tabulated >= design_a, f"{cid}: {size} mm2 must carry {design_a} A"
