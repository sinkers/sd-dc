"""The spec sheet, and its refusal to invent numbers.

Phase 0's whole content is knowing what is not known yet, so most of these
tests are about the null case rather than the values.
"""

import json

import pytest

from dtloop.params import GRADES, LoopParams, PendingReference


@pytest.fixture
def params():
    return LoopParams.load()


def test_settled_values_come_back_with_their_provenance(params):
    p = params.param("loads.hall_liquid_kw")
    assert p.value == 1092.0
    assert p.unit == "kW"
    assert p.confidence == "M"
    assert "FINDINGS-AU01" in p.source
    assert "1092.0" in p.describe() and "[M:" in p.describe()


def test_a_pending_parameter_refuses_rather_than_defaulting(params):
    # The design decision of params.py. A default here would be a number nobody
    # chose, indistinguishable downstream from one somebody did.
    with pytest.raises(PendingReference) as exc:
        params.get("temperatures.ambient_design_c")
    assert "weather file" in str(exc.value)
    assert exc.value.path == "temperatures.ambient_design_c"


def test_rd110_loop_temperatures():
    """RD110 rev 3, Facility Cooling and IT Space attribute tables.

    These four are stated outright, so they are graded H and should not move
    without a new revision of the document.
    """
    p = LoopParams.load()
    assert p.get("temperatures.facility_supply_c") == 37.0
    assert p.get("temperatures.facility_return_c") == 47.0
    assert p.get("temperatures.tcs_supply_c") == 40.0
    assert p.get("temperatures.tcs_return_c") == 50.0
    for path in ("facility_supply_c", "facility_return_c", "tcs_supply_c", "tcs_return_c"):
        assert p.param(f"temperatures.{path}").confidence == "H"


def test_both_loops_run_a_ten_kelvin_rise(params):
    facility = params.get("temperatures.facility_return_c") - params.get("temperatures.facility_supply_c")
    tcs = params.get("temperatures.tcs_return_c") - params.get("temperatures.tcs_supply_c")
    assert facility == pytest.approx(10.0)
    assert tcs == pytest.approx(10.0)


def test_cdu_approach_is_what_rd110s_own_temperatures_imply(params):
    # Derived, not stated - hence grade M. 40 C TCS supply off 37 C facility.
    approach = params.get("temperatures.tcs_supply_c") - params.get("temperatures.facility_supply_c")
    assert params.get("temperatures.cdu_approach_k") == pytest.approx(approach)
    assert params.param("temperatures.cdu_approach_k").confidence == "M"


def test_the_whole_temperature_stack_is_thirteen_kelvin_wide(params):
    # 37 -> 40 at the CDU, 40 -> 50 through the plate, 50 -> 47 on the way back.
    # A tight stack, and the reason a 3 K CDU approach carries so much weight.
    lo = params.get("temperatures.facility_supply_c")
    hi = params.get("temperatures.tcs_return_c")
    assert hi - lo == pytest.approx(13.0)


def test_the_chillers_are_the_baseline_and_dry_coolers_are_not(params):
    """RD110's Design Options list dry coolers; its baseline is the chillers,
    and following the baseline is the decision that has been taken.

    A free-cooling chiller is a dry cooler below its crossover ambient and a
    chiller above it, so the dry-cooler approach is no longer on the critical
    path - `hydraulic.free_cooling_full_ambient_c` sets the crossover instead.
    The parameter is kept rather than deleted because the option is real.
    """
    assert params.get("plant.drycooler.selected") is False
    assert params.is_pending("temperatures.drycooler_approach_k")
    assert "design option" in dict(params.pending())["temperatures.drycooler_approach_k"]

    crossover_input = params.param("hydraulic.free_cooling_full_ambient_c")
    assert crossover_input.confidence == "L", "this is judgement, not an RD110 figure"

    lo, hi = params.get("temperatures.ambient_range_rd110_c")
    assert (lo, hi) == (-9.6, 39.3)


def test_the_liquid_load_uses_the_ai_racks_not_the_whole_it_figure(params):
    """The arithmetic slip worth pinning: 87 % of the AI racks, not of all IT."""
    load = params.get("loads.rd110_liquid_load_kw")
    ai_only = params.get("plant.rd110.ai_rack_count") * params.get("plant.rd110.ai_rack_kw") \
        * params.get("plant.rd110.liquid_fraction")
    assert load == pytest.approx(ai_only, abs=1.0)

    all_it = params.get("plant.rd110.it_load_kw") * params.get("plant.rd110.liquid_fraction")
    capacity = 3 * 2075.0  # N+1 of four at RD110's Paris rating
    assert load < capacity < all_it, (
        "the wrong sum exceeds N+1 capacity and the right one does not - "
        "which is exactly why it matters"
    )


def test_rd110_plant_is_recorded_separately_from_au01s(params):
    # RD110 is a 142 kW GB300 design with 9 Motivair MCDU-50s; AU01 is a B300
    # hall with 3 Vertiv XDU 1350s. Comparable, not interchangeable.
    assert params.get("plant.rd110.ai_rack_kw") == 142.0
    assert params.get("plant.rd110.cdu_count") == 9
    assert params.get("plant.cdu.count") == 3
    assert "Motivair" in params.get("plant.rd110.cdu_model")
    assert "Vertiv" in params.get("plant.cdu.model")
    assert "chiller" in params.get("plant.rd110.heat_rejection").lower()


def test_the_air_liquid_split_is_deliberately_unsettled(params):
    """RD110 sharpened this open item rather than closing it.

    RD110 states 87 % liquid / 13 % air - for a 142 kW GB300 NVL72. AU01's own
    68 kW liquid and 36.75 kW air imply 65 %, for B300 nodes. Different machines,
    and a 22-point gap is roughly a factor of three on the air load, so the two
    are recorded separately and the capture fraction stays null.
    """
    assert params.is_pending("loads.dlc_capture_fraction")

    liquid = params.get("loads.rack_liquid_kw")
    air = params.get("loads.rack_air_kw")
    au01_implied = liquid / (liquid + air)
    assert 0.6 < au01_implied < 0.7, "the arithmetic the open item rests on has moved"

    rd110 = params.get("plant.rd110.liquid_fraction")
    assert rd110 == 0.87
    assert rd110 - au01_implied > 0.2, "the gap that keeps this open has closed - revisit"


def test_pending_lists_every_unsettled_parameter_with_what_would_settle_it(params):
    pending = params.pending()
    assert len(pending) > 10
    for path, why in pending:
        assert why and why != "an unrecorded source", f"{path} has no route to an answer"
        assert params.is_pending(path)


def test_judgement_calls_are_findable(params):
    """by_confidence("L") is the list of numbers that are judgement, not evidence.

    Worth keeping honest: every one of these moves a result, and none of them
    came from a document. `free_cooling_full_ambient_c` is the one with the most
    leverage - it sets the crossover ambient, and so the whole free-cooling story.
    """
    low = {p.path for p in params.by_confidence("L")}
    assert "hydraulic.free_cooling_full_ambient_c" in low
    assert "loads.cdu_standing_loss_kw" in low
    assert "fluid.properties_source" in low

    # And things that did come from a document are not in it.
    for settled in ("loads.hall_liquid_kw", "temperatures.facility_supply_c",
                    "plant.rd110.ai_rack_kw"):
        assert settled not in low


def test_unknown_paths_and_groups_are_distinguished(params):
    with pytest.raises(KeyError, match="no parameter"):
        params.get("loads.nonexistent")
    with pytest.raises(KeyError, match="is a group"):
        params.get("loads")
    with pytest.raises(ValueError, match="unknown confidence grade"):
        params.by_confidence("X")


def test_every_settled_parameter_carries_a_known_grade(params):
    seen = 0
    for grade in GRADES:
        for p in params.by_confidence(grade):
            assert p.confidence in GRADES
            seen += 1
    assert seen >= 10


def test_notes_written_as_lists_are_flattened(params):
    note = params.param("hydraulic.closed_valve_k").note
    assert isinstance(note, str)
    assert "singular" in note


def test_the_json_is_the_only_source_of_values():
    # A stray literal in params.py would defeat the whole arrangement.
    raw = json.loads(json.dumps(LoopParams.load()._data))
    assert raw["schema_version"] == 1
    assert raw["temperatures"]["facility_supply_c"]["value"] == 37.0
    assert raw["temperatures"]["drycooler_approach_k"]["value"] is None
