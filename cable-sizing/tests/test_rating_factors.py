"""Section 4 - rating factors, the DeclaredAs guard, and harmonics."""
import pytest

from dame_cable.errors import InvalidDeclaration, MissingTableData, OpenItem
from dame_cable.rating_factors import (FactorSet,
                                       HarmonicBasis, RatingFactor,
                                       build_factor_set, harmonic_treatment,
                                       neutral_current_a)
from dame_cable.schema import (SupportType, Cable, CableConstruction, ConductorMaterial,
                               DeclaredAs, InstallationArrangement,
                               InstallationMethod, Insulation, Load, SystemType)
from dame_cable.tables.registry import TableStore


def cable(size=50):
    return Cable(material=ConductorMaterial.COPPER,
                 insulation=Insulation.THERMOSETTING_90,
                 construction=CableConstruction.MULTICORE,
                 size_mm2=size, cores_loaded=3)


def air(**kw):
    kw.setdefault("ambient_c", 40)
    kw.setdefault("arrangement", InstallationArrangement.AIR_TOUCHING)
    kw.setdefault("support_type", SupportType.NONE)
    return InstallationMethod(**kw)


# -- C1: the double-counting guard ----------------------------------------

def test_derated_declaration_is_refused(store):
    with pytest.raises(InvalidDeclaration, match="double-count"):
        build_factor_set(store, cable(), air(), DeclaredAs.DERATED)


def test_same_factor_cannot_be_added_twice():
    fs = FactorSet()
    fs.add(RatingFactor("grouping", 0.8, "x"))
    with pytest.raises(InvalidDeclaration, match="twice"):
        fs.add(RatingFactor("grouping", 0.9, "y"))


# -- C2: factors multiply --------------------------------------------------

def test_factors_multiply(store):
    fs = build_factor_set(store, cable(), air(ambient_c=45, circuits_in_group=4))
    assert fs.as_dict()["ambient_air"] == pytest.approx(0.94)
    assert fs.as_dict()["grouping"] == pytest.approx(0.75)
    assert fs.product == pytest.approx(0.94 * 0.75)


def test_a_single_circuit_still_takes_a_grouping_factor(store):
    """M4 Rev B finding 5 / R-ADM-6, and this reverses Rev A.

    A single circuit is NOT automatically CF 1.00. Table 3.14 NOTE 4 requires a
    Table 3.34 factor for one circuit on a tray: 0.95 unperforated, 0.97
    perforated, 1.00 on ladder. Rev A omitted the factor entirely at one
    circuit, which silently credited every tray installation with the ladder
    value."""
    fs = build_factor_set(store, cable(), air(circuits_in_group=1))
    assert "grouping" in fs.as_dict()


def test_support_type_changes_the_answer_at_one_circuit(store):
    """The case that catches an engine defaulting grouping to 1.00."""
    perf = build_factor_set(store, cable(), air(
        circuits_in_group=1,
        grouping_code="t334_perforated_touching_1row")).as_dict()["grouping"]
    ladder = build_factor_set(store, cable(), air(
        circuits_in_group=1,
        grouping_code="t334_ladder_touching_1row")).as_dict()["grouping"]
    assert perf == pytest.approx(0.97)
    assert ladder == pytest.approx(1.00)
    assert perf < ladder


# -- C3: medium picks the ambient table ------------------------------------

def test_buried_uses_the_soil_tables(store):
    fs = build_factor_set(store, cable(), InstallationMethod(
        support_type=SupportType.NONE, arrangement=InstallationArrangement.BURIED_DIRECT, ambient_c=25,
        depth_of_burial_m=0.8, soil_thermal_resistivity_km_w=1.2))
    keys = fs.as_dict()
    assert "ambient_soil" in keys and "ambient_air" not in keys
    assert "depth_of_burial" in keys and "soil_thermal_resistivity" in keys


def test_buried_without_depth_is_rejected_at_the_boundary():
    from dame_cable.schema import SupportType, InvalidInstallation
    with pytest.raises(InvalidInstallation, match="depth_of_burial_m"):
        InstallationMethod(support_type=SupportType.NONE, arrangement=InstallationArrangement.BURIED_DIRECT,
                           ambient_c=25, soil_thermal_resistivity_km_w=1.2)


# -- R-ADM-3: solar radiation is a base COLUMN, not a factor ---------------

def test_solar_is_a_base_column_not_an_uplift(store):
    """M4 Rev B finding 4. `air_exposed_to_sun` is its own rating column, so
    the ambient factor is entered at the MEASURED ambient and no uplift of any
    kind applies -- including the Clause 3.5.8(b) +20 K proxy, which is only
    for cable types outside the 3.9-3.20 family and is out of M4 scope."""
    sun = build_factor_set(store, cable(),
                           air(arrangement=InstallationArrangement.AIR_EXPOSED_TO_SUN,
                               ambient_c=25))
    plain = build_factor_set(store, cable(), air(ambient_c=25))
    assert sun.as_dict()["ambient_air"] == plain.as_dict()["ambient_air"]
    assert "solar" not in sun.as_dict()
    assert "thermal_insulation" not in sun.as_dict()


def test_a_solar_factor_is_refused(store):
    from dame_cable.errors import InadmissibleFactor
    from dame_cable.rating_factors import admit
    with pytest.raises(InadmissibleFactor):
        admit(InstallationArrangement.AIR_EXPOSED_TO_SUN, "solar")

def test_ambient_rounds_up_to_the_next_band(store):
    """43 C must take the 45 C row, never the 40 C row."""
    at43 = build_factor_set(store, cable(), air(ambient_c=43)).as_dict()["ambient_air"]
    assert at43 == pytest.approx(0.94)


def test_grouping_rounds_up_to_the_listed_row(store):
    """M4 Rev B R-BAND-2, and this reverses Rev A.

    The factor DECREASES as circuits increase, so rounding the count down
    raises it -- the anti-conservative direction. 5 circuits take the
    6-circuit row, 0.72, not the 4-circuit row, 0.75. Rev A had this backwards
    and called it a convention; it was a defect."""
    cf = build_factor_set(store, cable(),
                          air(circuits_in_group=5)).as_dict()["grouping"]
    assert cf == pytest.approx(0.72)


def test_rounding_grouping_down_would_be_anti_conservative(store):
    """Guards the direction itself, not just the value."""
    four = build_factor_set(store, cable(),
                            air(circuits_in_group=4)).as_dict()["grouping"]
    six = build_factor_set(store, cable(),
                           air(circuits_in_group=6)).as_dict()["grouping"]
    five = build_factor_set(store, cable(),
                            air(circuits_in_group=5)).as_dict()["grouping"]
    assert six < four, "the factor must fall as circuits rise"
    assert five == six, "an untabulated count takes the NEXT HIGHER entry"


def test_off_the_top_of_a_band_raises_rather_than_clamping(store):
    with pytest.raises(MissingTableData, match="exceeds the highest band"):
        build_factor_set(store, cable(), air(ambient_c=80))


# -- harmonics --------------------------------------------------------------

def hload(r, i=100):
    return Load(design_current_a=i, system=SystemType.THREE_PHASE_AC,
                nominal_voltage_v=400, third_harmonic_fraction=r)


def test_neutral_equals_phase_at_the_theoretical_crossover():
    """r = 1/sqrt(8) = 35.36 %."""
    i1, i_n = neutral_current_a(hload(1 / 8 ** 0.5))
    assert i_n == pytest.approx(100.0)


def test_below_the_crossover_neutral_is_smaller():
    _, i_n = neutral_current_a(hload(0.25))
    assert i_n < 100.0


def test_standards_band_edge_is_below_the_physical_crossover(store):
    """Clause 3.5.9 switches to a neutral basis at 33 %, slightly ahead of the
    35.36 % point at which the neutral actually overtakes the phase. The
    standard governs; this test records the difference deliberately."""
    at34 = harmonic_treatment(store, hload(0.34))
    assert at34.basis is HarmonicBasis.NEUTRAL
    assert at34.neutral_a < at34.fundamental_phase_a * (1 + 0.34 ** 2) ** 0.5


def test_low_harmonic_content_is_phase_basis(store):
    out = harmonic_treatment(store, hload(0.10))
    assert out.basis is HarmonicBasis.PHASE
    assert out.cf == pytest.approx(1.0)
    assert out.governing_current_a == pytest.approx(100.0)


def test_mid_band_derates_on_a_phase_basis(store):
    out = harmonic_treatment(store, hload(0.20))
    assert out.basis is HarmonicBasis.PHASE
    assert out.cf < 1.0
    assert out.governing_current_a == pytest.approx(100.0)


def test_high_harmonic_content_switches_to_the_neutral(store):
    out = harmonic_treatment(store, hload(0.40))
    assert out.basis is HarmonicBasis.NEUTRAL
    assert out.governing_current_a == pytest.approx(out.neutral_a)


def test_zero_harmonics_short_circuits_without_touching_the_table(store):
    empty = TableStore.load("/nonexistent")
    out = harmonic_treatment(empty, hload(0.0))
    assert out.cf == 1.0 and out.basis is HarmonicBasis.PHASE


def test_missing_harmonic_table_raises_open_item_not_a_default(store):
    """The §3.12 rule: no default is defensible here."""
    empty = TableStore.load("/nonexistent")
    with pytest.raises(OpenItem, match="Table 3.4"):
        harmonic_treatment(empty, hload(0.25))
