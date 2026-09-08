"""Section 6 - k, the Table 5.2 break, and the iteration rule."""
import pytest

from dame_cable.schema import (Cable, CableConstruction, ConductorMaterial,
                               DeviceType, Insulation, Protection)
from dame_cable.short_circuit import (k_factor, k_for_size, minimum_size,
                                      withstand_i2t, withstand_is_monotonic)

Cu, Al = ConductorMaterial.COPPER, ConductorMaterial.ALUMINIUM


@pytest.mark.parametrize("material,ti,tf,expected", [
    (Cu, 70, 160, 115),
    (Cu, 90, 250, 143),
    (Al, 70, 160, 76),
    (Al, 90, 250, 95),
])
def test_k_reproduces_published_values(material, ti, tf, expected):
    """The k formula must land on the familiar figures to within rounding."""
    assert k_factor(material, ti, tf) == pytest.approx(expected, abs=0.6)


def test_k_rejects_inverted_temperatures():
    with pytest.raises(ValueError):
        k_factor(Cu, 160, 70)


def pvc(size):
    return Cable(material=Cu, insulation=Insulation.THERMOPLASTIC_75,
                 construction=CableConstruction.MULTICORE, size_mm2=size,
                 cores_loaded=3)


def test_k_steps_down_across_the_300mm2_break(store):
    """Table 5.2 lowers the permitted final temperature above 300 mm2."""
    k300, lim300 = k_for_size(store, pvc(300), 300)
    k400, lim400 = k_for_size(store, pvc(400), 400)
    assert lim300.final_c > lim400.final_c
    assert k400 < k300
    assert k300 == pytest.approx(115, abs=0.6)
    assert k400 == pytest.approx(103, abs=0.6)


def test_k_is_resolved_per_candidate_not_once_before_the_loop(store):
    """The bug this test exists to catch.

    Fault energy chosen so that 400 mm2 passes on the pre-break k (115) and
    fails on its own k (103). An implementation that resolves k once from the
    starting size and reuses it will return 400 mm2. The correct answer is
    500 mm2.
    """
    cable = pvc(240)
    sizes = [240, 300, 400, 500, 630]
    let_through = 1.9e9                      # A^2.s

    assert withstand_i2t(store, cable, 400) < let_through
    assert (115 * 400) ** 2 > let_through     # would have passed on stale k

    protection = Protection(
        device=DeviceType.MCCB, rating_a=400,
        prospective_fault_current_a=(let_through ** 0.5),
        clearing_time_s=1.0,
    )
    assert minimum_size(store, cable, protection, sizes) == 500


def test_withstand_monotonic_across_the_break(store):
    """k falls at the break while S rises; confirm the product still rises,
    which is what makes an ascending scan sufficient."""
    monotonic, values = withstand_is_monotonic(
        store, pvc(240), [95, 120, 150, 185, 240, 300, 400, 500, 630])
    assert monotonic, values


def test_parallel_sets_scale_withstand_by_n_squared(store):
    from dataclasses import replace
    single = pvc(240)
    doubled = replace(single, parallel_sets=2)
    assert withstand_i2t(store, doubled, 240) == pytest.approx(
        4 * withstand_i2t(store, single, 240))


def test_adiabatic_validity_limit(store):
    from dame_cable.errors import OpenItem
    from dame_cable.short_circuit import check
    p = Protection(device=DeviceType.HRC, rating_a=250,
                   prospective_fault_current_a=5000, clearing_time_s=6.0)
    with pytest.raises(OpenItem):
        check(store, pvc(240), p)
