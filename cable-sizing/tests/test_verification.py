"""Verification against the standard's own published answers.

These tests run against data/ - the transcribed licensed tables - and SKIP
until it is populated. They are the tests that matter for issue; everything
else in this suite proves the code is self-consistent, these prove it agrees
with AS/NZS 3008.1.1.

Add a row to CASES for each worked figure you check by hand. That list is the
spec's numeric verification section, executable.
"""
import pytest

from dame_cable.errors import MissingTableData
from dame_cable.schema import (Cable, CableConstruction, ConductorMaterial,
                               Insulation, Load, SystemType)
from dame_cable.short_circuit import k_factor
from dame_cable.voltage_drop import cross_check_mv_per_a_m

#: (material, insulation, construction, size_mm2, system, power_factor)
CASES = [
    (ConductorMaterial.COPPER, Insulation.THERMOSETTING_90,
     CableConstruction.MULTICORE, 4, SystemType.THREE_PHASE_AC, 0.8),
    (ConductorMaterial.COPPER, Insulation.THERMOSETTING_90,
     CableConstruction.MULTICORE, 35, SystemType.THREE_PHASE_AC, 0.8),
    (ConductorMaterial.COPPER, Insulation.THERMOSETTING_90,
     CableConstruction.MULTICORE, 185, SystemType.THREE_PHASE_AC, 0.8),
    (ConductorMaterial.ALUMINIUM, Insulation.THERMOSETTING_90,
     CableConstruction.MULTICORE, 240, SystemType.THREE_PHASE_AC, 0.9),
]

TOLERANCE = 0.01          # 1 %


@pytest.mark.parametrize("material,insulation,construction,size,system,pf", CASES)
def test_computed_mv_per_a_m_matches_the_standard(
        licensed_store, material, insulation, construction, size, system, pf):
    """R and X must reproduce the standard's own mV/A.m to better than 1 %.

    At p.f. 0.8 this asserts the Clause 4.2 column via the R-VD-2 branch rule,
    not the Clause 4.5 value at exactly 0.8. The two 4 and 35 mm2 cases were
    previously xfail because they compared those two quantities against each
    other; both were correct and they are not the same thing. See
    spec-exchange/ANS-001, sections A1.2 and A1.4.
    """
    cable = Cable(material=material, insulation=insulation,
                  construction=construction, size_mm2=size, cores_loaded=3)
    load = Load(design_current_a=100, system=system,
                nominal_voltage_v=400, power_factor=pf)
    try:
        result = cross_check_mv_per_a_m(licensed_store, cable, load, pf)
    except MissingTableData as exc:
        pytest.skip(f"data/ not populated for this case: {exc}")
    assert result["relative_difference"] < TOLERANCE, result
    if pf == 0.8:
        assert result["branch"] in ("max", "0.8")


def test_k_values_from_the_transcribed_table_5_2(licensed_store):
    """Whatever temperatures Table 5.2 actually states, the resulting k must
    be a sane number and must step down across the thermoplastic size break."""
    from dame_cable.short_circuit import k_for_size
    cable = Cable(material=ConductorMaterial.COPPER,
                  insulation=Insulation.THERMOPLASTIC_75,
                  construction=CableConstruction.MULTICORE,
                  size_mm2=300, cores_loaded=3)
    try:
        k_small, lim_small = k_for_size(licensed_store, cable, 300)
        k_large, lim_large = k_for_size(licensed_store, cable, 400)
    except MissingTableData as exc:
        pytest.skip(f"sc_limits.csv not populated: {exc}")
    assert 90 < k_small < 130
    assert k_large < k_small
    assert lim_large.final_c < lim_small.final_c


def test_the_formula_itself_is_independent_of_the_data():
    """Sanity anchor that does not depend on any table."""
    assert k_factor(ConductorMaterial.COPPER, 70, 160) == pytest.approx(115, abs=0.6)
