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
        params.get("temperatures.tcs_supply_c")
    assert "RD110" in str(exc.value)
    assert exc.value.path == "temperatures.tcs_supply_c"


def test_every_temperature_is_pending_rd110(params):
    # If this ever fails it is good news: RD110 arrived. Update the test with
    # the values, do not delete it - it is what stops a placeholder shipping.
    pending = dict(params.pending())
    temps = [k for k in pending if k.startswith("temperatures.")]
    assert len(temps) == 9, f"expected 9 temperature parameters, found {temps}"
    for key in temps:
        assert "RD110" in pending[key], f"{key} is pending {pending[key]!r}, not RD110"


def test_the_air_liquid_split_is_deliberately_unsettled(params):
    # SPEC.md section 8: 68 kW liquid + 36.75 kW air is a 65% liquid share,
    # against FINDINGS-AU01 section 365's "up to 95%". They cannot both hold, so
    # the capture fraction stays null until somebody resolves it.
    assert params.is_pending("loads.dlc_capture_fraction")
    liquid = params.get("loads.rack_liquid_kw")
    air = params.get("loads.rack_air_kw")
    implied = liquid / (liquid + air)
    assert 0.6 < implied < 0.7, "the arithmetic the open item rests on has moved"


def test_pending_lists_every_unsettled_parameter_with_what_would_settle_it(params):
    pending = params.pending()
    assert len(pending) > 20
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
    raw = json.loads((LoopParams.load()._data and json.dumps(LoopParams.load()._data)))
    assert raw["schema_version"] == 1
    assert raw["temperatures"]["facility_supply_c"]["value"] is None
