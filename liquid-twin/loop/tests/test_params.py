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


def test_rd110_cannot_settle_the_dry_cooler_approach(params):
    """The finding in SPEC.md 7.1, pinned so it cannot be quietly filled in.

    RD110's baseline heat rejection is high-temperature chillers. Dry coolers
    appear only in its Design Options list with no approach given, and a chiller
    figure would not transfer: a chiller makes 37 C water at any ambient in
    range, a dry cooler cannot make water colder than the air at all.
    """
    assert params.is_pending("temperatures.drycooler_approach_k")
    why = dict(params.pending())["temperatures.drycooler_approach_k"]
    assert "dry cooler selection" in why

    # RD110 does record its own ambient range, and it is above every ambient at
    # which a dry cooler could hold 37 C - which is consistent with its choice.
    lo, hi = params.get("temperatures.ambient_range_rd110_c")
    assert (lo, hi) == (-9.6, 39.3)
    assert hi > params.get("temperatures.facility_supply_c") - 3.0


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
    # by_confidence("L") is the list of numbers that are judgement, not evidence.
    low = {p.path for p in params.by_confidence("L")}
    assert "loads.cdu_standing_loss_kw" in low
    assert "plant.drycooler.rated_duty_kw" in low
    assert "loads.hall_liquid_kw" not in low


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
