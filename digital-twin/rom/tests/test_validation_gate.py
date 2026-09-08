"""The validation gate: the calibrated ROM must still reproduce the CFD.

This is the regression that matters. Any change to the model equations, the
topology, or the committed parameters has to keep the ROM agreeing with
case-hall's 24-rack table, its flows and its energy balance — or it fails here.

Scope of the claim, stated plainly: one CFD operating point (case-hall v4,
864 kW uniform, 28 C supply, all four modules running). It shows the ROM
reproduces the CFD *at* that point. It does not show the ROM extrapolates, and
the parameters governing extrapolation (supply_reach, zone_coupling,
recirc_gain) are unidentifiable from a symmetric, oversupplied run. See the
module docstring of dthall/calibrate.py.
"""

import numpy as np
import pytest

from dthall import calibrate, cfddata, topology
from dthall.params import RomParams


@pytest.fixture(scope="module")
def scorecard():
    return calibrate.validate()


def test_committed_parameters_pass_the_gate(scorecard):
    failures = {
        name: detail for name, (ok, detail) in scorecard.checks.items() if not ok
    }
    assert not failures, "\n" + scorecard.report()


def test_every_rack_mean_is_close(scorecard):
    assert np.abs(scorecard.mean_err).max() <= calibrate.GATE["mean_abs_max_k"]


def test_the_end_of_row_hot_spots_are_reproduced_not_averaged_away(scorecard):
    """The four aisle-end racks are the interesting part of the CFD result. A
    model that predicted a uniform hall would pass a mean test and be useless."""
    names = scorecard.rack_names
    ends = [i for i, n in enumerate(names) if n[-2:] in ("00", "11")]
    mid = [i for i, n in enumerate(names) if 3 <= int(n[-2:]) <= 8]

    cfd_lift = scorecard.mean_cfd[ends].mean() - scorecard.mean_cfd[mid].mean()
    rom_lift = scorecard.mean_rom[ends].mean() - scorecard.mean_rom[mid].mean()
    assert cfd_lift > 1.0, "sanity: the CFD really does show end-of-row lift"
    assert rom_lift == pytest.approx(cfd_lift, abs=0.3)


def test_the_reference_reader_uses_windowed_statistics_not_last_values():
    """The hall CFD never fully converges, so a last-value read would be fitting
    to the phase of an oscillating plume."""
    ref = cfddata.load_case_hall()
    last = cfddata.read_channel(ref.case, "rB11_inletTmax")[-1, 1]
    windowed_max = cfddata.windowed(ref.case, "rB11_inletTmax", op="max")
    assert windowed_max >= last
    # the peak channels really are noisy enough for this to matter
    series = cfddata.read_channel(ref.case, "rB11_inletTmax")[-25:, 1]
    assert series.max() - series.min() > 0.5


def test_uncalibrated_defaults_would_not_pass():
    """Guards against the gate silently passing because it is not actually
    testing the fit (e.g. if the calibrated parameters stopped being loaded)."""
    card = calibrate.validate(params=RomParams())
    assert not card.passed


def test_scorecard_report_renders(scorecard):
    text = scorecard.report()
    assert "ROM VALIDATION" in text
    assert "OVERALL: PASS" in text
    for name in scorecard.rack_names:
        assert name in text
