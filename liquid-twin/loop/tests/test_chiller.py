"""Free-cooling chillers: the mode boundary and what it costs to cross it."""

import pytest

from dtloop.chiller import (
    MODE_FREE,
    MODE_MECHANICAL,
    MODE_MIXED,
    MODE_OFF,
    FreeCoolingChiller,
    rd110_plant,
)

RETURN_C = 47.0


@pytest.fixture
def unit():
    # Full free cooling at 20 C with 47 C return water: a 27 K span, so the coil
    # is worth 2075/27 = 76.9 kW per kelvin.
    return FreeCoolingChiller.from_full_free_cooling_at(
        "HT_CH-1", rated_kw=2075.0, full_free_ambient_c=20.0, return_water_c=RETURN_C)


def test_coil_is_sized_from_the_full_free_cooling_point(unit):
    assert unit.ua_free_kw_per_k == pytest.approx(2075.0 / 27.0)
    # And by construction it carries exactly the rated load at that ambient.
    assert unit.free_cooling_kw(20.0, RETURN_C) == pytest.approx(2075.0)


def test_full_free_cooling_above_the_return_temperature_is_refused():
    with pytest.raises(ValueError, match="below the return water"):
        FreeCoolingChiller.from_full_free_cooling_at(
            "bad", rated_kw=1000.0, full_free_ambient_c=50.0, return_water_c=47.0)


def test_the_three_regimes_in_ambient_order(unit):
    load = 1500.0
    assert unit.mode(-5.0, load, RETURN_C) == MODE_FREE
    assert unit.mode(30.0, load, RETURN_C) == MODE_MIXED
    assert unit.mode(47.0, load, RETURN_C) == MODE_MECHANICAL
    assert unit.mode(60.0, load, RETURN_C) == MODE_MECHANICAL
    assert unit.mode(10.0, 0.0, RETURN_C) == MODE_OFF


def test_free_cooling_cannot_be_negative(unit):
    # Air hotter than the water it would cool does nothing; it does not add heat.
    assert unit.free_cooling_kw(60.0, RETURN_C) == 0.0


def test_compressors_are_off_below_the_crossover_and_on_above(unit):
    load = 1500.0
    x = unit.crossover_ambient_c(load, RETURN_C)
    below = unit.power_kw(x - 3.0, load, RETURN_C)
    above = unit.power_kw(x + 3.0, load, RETURN_C)

    assert below["mode"] == MODE_FREE
    assert below["compressors_kw"] == 0.0
    assert below["fans_kw"] > 0.0, "the fans still run in free cooling"

    assert above["mode"] == MODE_MIXED
    assert above["compressors_kw"] > 0.0
    assert above["total_kw"] > below["total_kw"]


def test_the_crossover_falls_as_load_rises(unit):
    """The counter-intuitive one, and the reason crossover takes a load.

    A fully loaded plant loses free cooling at a *lower* ambient than a lightly
    loaded one, because the coil has more heat to shift for the same air.
    """
    light = unit.crossover_ambient_c(500.0, RETURN_C)
    heavy = unit.crossover_ambient_c(2000.0, RETURN_C)
    assert heavy < light


def test_free_fraction_runs_from_one_to_zero(unit):
    load = 1500.0
    assert unit.free_fraction(0.0, load, RETURN_C) == 1.0
    mid = unit.free_fraction(35.0, load, RETURN_C)
    assert 0.0 < mid < 1.0
    assert unit.free_fraction(47.0, load, RETURN_C) == 0.0


def test_cop_falls_with_ambient_but_not_below_the_floor(unit):
    assert unit.cop(15.0) > unit.cop(25.0) > unit.cop(40.0)
    assert unit.cop(200.0) == pytest.approx(unit.cop_floor)


def test_power_rises_monotonically_with_ambient(unit):
    load = 1500.0
    totals = [unit.power_kw(t, load, RETURN_C)["total_kw"] for t in range(-10, 50, 2)]
    assert all(a <= b + 1e-9 for a, b in zip(totals, totals[1:])), totals


# -- the plant -----------------------------------------------------------

def test_rd110_plant_runs_n_plus_one():
    p = rd110_plant()
    assert len(p.units) == 4
    assert p.running == 3
    assert p.capacity_kw == pytest.approx(3 * 2075.0)


def test_rd110_capacity_covers_the_liquid_load_with_a_little_to_spare():
    """87 % of the AI racks, not of RD110's whole IT figure.

    48 racks x 142 kW x 0.87 = 5,930 kW against 6,225 kW of N+1 capacity at
    RD110's Paris rating - about 5 % margin. Applying 87 % to the full 7,536 kW
    IT load instead gives 6,556 kW, which would *exceed* N+1 capacity and is
    simply the wrong sum: the 48 networking racks at 15 kW are air-cooled.
    """
    p = rd110_plant()
    liquid = 48 * 142.0 * 0.87
    assert liquid == pytest.approx(5930.0, abs=1.0)
    assert p.capacity_kw > liquid
    assert (p.capacity_kw - liquid) / liquid < 0.10


def test_plant_free_cooling_at_the_rd110_liquid_load():
    p = rd110_plant()
    liquid = 48 * 142.0 * 0.87
    x = p.crossover_ambient_c(liquid, RETURN_C)
    assert 15.0 < x < 30.0

    cold = p.power_kw(x - 5.0, liquid, RETURN_C)
    hot = p.power_kw(42.0, liquid, RETURN_C)
    assert cold["mode"] == MODE_FREE and cold["compressors_kw"] == 0.0
    assert hot["compressors_kw"] > 0.0
    # Crossing the boundary is expensive - that is the whole point of the readout.
    assert hot["total_kw"] > 4 * cold["total_kw"]
    assert cold["cop_effective"] > 4 * hot["cop_effective"]


def test_sweep_is_ordered_and_covers_the_range():
    p = rd110_plant()
    rows = p.sweep(5930.0, RETURN_C, lo=-10.0, hi=48.0, step=0.5)
    assert rows[0]["ambient_c"] == -10.0
    assert rows[-1]["ambient_c"] == 48.0
    assert all(a["ambient_c"] < b["ambient_c"] for a, b in zip(rows, rows[1:]))
    assert {r["mode"] for r in rows} >= {MODE_FREE, MODE_MIXED, MODE_MECHANICAL}
