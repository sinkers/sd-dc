"""The plant layout. Mostly structural: these are the checks that stop a
reviewer having to find a routing mistake by rotating the 3D view."""

import pytest

from dtloop.layout import (
    POD_COUNT,
    RACKS_PER_ROW,
    SERVICES,
    Point,
    build_layout,
    route,
)


@pytest.fixture(scope="module")
def lay():
    return build_layout()


def test_the_layout_is_valid(lay):
    assert lay.validate() == []


def test_every_run_is_orthogonal(lay):
    # Checked by validate() too, but stated separately because it is the thing
    # a fabricator cares about and the thing a careless edit breaks.
    for s in lay.segments:
        for a, b in zip(s.waypoints, s.waypoints[1:]):
            moved = [abs(b.x - a.x) > 1e-9, abs(b.y - a.y) > 1e-9, abs(b.z - a.z) > 1e-9]
            assert sum(moved) == 1, f"{s.name}: diagonal from {a} to {b}"


def test_rd110_equipment_counts(lay):
    assert len(lay.by_kind("chiller")) == 4          # N+1
    assert len(lay.by_kind("cdu")) == 9              # three pods of three
    assert len(lay.by_kind("rack")) == POD_COUNT * 2 * RACKS_PER_ROW == 48


def test_one_control_valve_per_liquid_cooled_rack(lay):
    """RD110_3.2 carries PCV01..PCV48. If this count drifts, the drawing and the
    model have stopped agreeing about how the racks are controlled."""
    pcvs = sorted(s.valve for s in lay.segments if s.valve.startswith("PCV"))
    assert len(pcvs) == 48
    assert pcvs[0] == "PCV01" and pcvs[-1] == "PCV48"
    assert len(set(pcvs)) == 48


def test_chiller_circuits_carry_their_control_valves(lay):
    cvs = sorted(s.valve for s in lay.segments if s.valve.startswith("CV"))
    assert cvs == ["CV01", "CV02", "CV03", "CV04"]


def test_every_rack_has_exactly_one_supply_and_one_return_drop(lay):
    for rack in lay.by_kind("rack"):
        drops = [s for s in lay.segments if s.name.startswith(rack.name + "_DROP")]
        assert len(drops) == 2, f"{rack.name} has {len(drops)} drops"
        assert {s.service for s in drops} == {"tcs_supply", "tcs_return"}
        assert sum(1 for s in drops if s.valve) == 1, "the supply drop carries the valve"


def test_both_loops_are_present_and_balanced_in_length(lay):
    for svc in SERVICES:
        assert lay.by_service(svc), f"no {svc} segments"
    # Supply and return follow the same route, so their totals should be close.
    tcs_s = sum(s.length_mm() for s in lay.by_service("tcs_supply"))
    tcs_r = sum(s.length_mm() for s in lay.by_service("tcs_return"))
    assert abs(tcs_s - tcs_r) / tcs_s < 0.05


def test_services_carry_the_rd110_design_temperatures():
    assert SERVICES["facility_supply"]["design_c"] == 37.0
    assert SERVICES["facility_return"]["design_c"] == 47.0
    assert SERVICES["tcs_supply"]["design_c"] == 40.0
    assert SERVICES["tcs_return"]["design_c"] == 50.0


def test_tcs_headers_run_above_the_racks(lay):
    from dtloop.layout import RACK_H
    for s in lay.segments:
        if s.name.endswith("_TCS_SUPPLY_HDR") or s.name.endswith("_TCS_RETURN_HDR"):
            assert all(p.z >= RACK_H for p in s.waypoints), f"{s.name} passes through a rack"


def test_segment_length_and_elbow_counts_are_the_ones_the_solver_will_use(lay):
    straight = next(x for x in lay.segments if x.name == "FAC_SUPPLY_MAIN")
    assert straight.elbows() == 0
    assert straight.length_mm() == pytest.approx(
        abs(straight.waypoints[1].y - straight.waypoints[0].y))

    drop = next(x for x in lay.segments if x.name.endswith("A01_DROP_S"))
    assert drop.elbows() == 1  # across under the header, then down to the rack
    assert drop.length_mm() == pytest.approx(
        sum(abs(b.x - a.x) + abs(b.y - a.y) + abs(b.z - a.z)
            for a, b in zip(drop.waypoints, drop.waypoints[1:])))


def test_no_run_turns_more_than_once_which_is_a_stated_limitation(lay):
    """Pinned because it is a limit of this model, not a property of real pipework.

    Every run here is a straight leg or a single right angle. Real routing round
    structure, other services and access ways turns far more often, and each
    extra elbow is fitting loss the solver would see. `piping/route_engine.py`
    is where A* routing, real bend radii and clash checking live; this layout is
    for reviewing connectivity and equipment placement, and its fitting counts
    should be read as a floor rather than an estimate.

    If a future edit routes something properly, this test failing is the signal
    to revisit the loss coefficients rather than to relax the assertion.
    """
    assert max(s.elbows() for s in lay.segments) == 1


def test_route_drops_repeated_points_but_not_real_moves():
    p = Point(0, 0, 0)
    assert len(route(p, Point(0, 0, 0), Point(1000, 0, 0))) == 2
    assert len(route(p, Point(1000, 0, 0), Point(1000, 500, 0))) == 3
    with pytest.raises(ValueError, match="two distinct points"):
        route(p, Point(0, 0, 0))


def test_names_are_unique_across_equipment_and_segments(lay):
    names = [e.name for e in lay.equipment] + [s.name for s in lay.segments]
    assert len(names) == len(set(names))


def test_bounds_enclose_everything(lay):
    lo, hi = lay.bounds()
    for e in lay.equipment:
        assert lo.x <= e.origin.x and e.origin.x + e.size[0] <= hi.x
    for s in lay.segments:
        for p in s.waypoints:
            assert lo.x <= p.x <= hi.x and lo.y <= p.y <= hi.y and lo.z <= p.z <= hi.z
