"""Baked CFD field textures and the ROM scalars that remap them.

The texture supplies the spatial pattern; the ROM supplies the magnitudes. These
tests cover both halves of that contract: that a baked PNG decodes back to the
CFD values it came from, and that the published remap scalars behave the way the
Unreal material assumes.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from dthall import topology
from dthall.model import HallModel, Inputs

FIELDS = Path(__file__).resolve().parents[2] / "fields"
MANIFEST = FIELDS / "slice_manifest.json"

pytestmark = pytest.mark.skipif(
    not MANIFEST.exists(), reason="run fields/bake_slices.py first"
)


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text())


def test_png16_codec_round_trips():
    from fields.bake_slices import write_png16

    rng = np.random.default_rng(0)
    original = rng.random((32, 64))
    path = FIELDS / "baked" / "_test_roundtrip.png"
    try:
        write_png16(path, original)
        import matplotlib.image as mpimg

        decoded = np.flipud(mpimg.imread(path))
        assert decoded.shape == original.shape
        # 16-bit quantisation only
        assert np.abs(decoded - original).max() < 2.0 / 65535
    finally:
        path.unlink(missing_ok=True)


def test_manifest_describes_every_baked_plane(manifest):
    assert manifest["planes"], "no planes baked"
    for plane in manifest["planes"]:
        png = FIELDS / "baked" / plane["file"]
        assert png.exists(), f"{plane['file']} missing"
        assert plane["value_max"] > plane["value_min"]
        assert plane["resolution"] == list(plane["resolution"])
        assert plane["normal_axis"] in ("x", "y", "z")
        assert plane["u_axis"] != plane["v_axis"] != plane["normal_axis"]
        assert len(plane["u_range_m"]) == 2 and plane["u_range_m"][1] > plane["u_range_m"][0]


def test_baked_temperatures_span_the_cfd_range(manifest):
    """Sanity: the temperature planes must cover supply to hot-aisle, in Celsius."""
    temps = [p for p in manifest["planes"] if p["field"] == "T"]
    assert temps
    supply = manifest["reference"]["supply_temp_c"]
    for p in temps:
        assert p["units"] == "degC"
        assert p["value_min"] == pytest.approx(supply, abs=0.5)
        assert p["value_max"] > supply + 8.0


def test_geometry_matches_the_hall_the_slices_came_from(manifest):
    """The plane extents must line up with the case geometry, or Unreal will
    place the field planes in the wrong place."""
    spec = topology.from_hall_parameters()
    plan = next(
        p for p in manifest["planes"] if p["name"] == "coldAisleA" and p["field"] == "T"
    )
    # case-hall is 8.35 m wide; the plan slice spans the full width
    width = plan["v_range_m"][1] - plan["v_range_m"][0]
    assert width == pytest.approx(8.35, abs=0.05)
    assert 0.0 < plan["normal_position_m"] < 2.0  # rack mid-height


# -- the ROM side of the contract -----------------------------------------


@pytest.fixture(scope="module")
def model():
    return HallModel(topology.from_hall_parameters())


def test_remap_is_identity_at_the_baked_operating_point(model, manifest):
    """The bake came from this hall at design load, so the published scalars
    should be ~neutral there: scale ~1, offset ~0."""
    _, obs = model.steady_state()
    assert obs.field_offset_k == pytest.approx(0.0, abs=0.05)
    assert obs.field_scale == pytest.approx(1.0, abs=0.35)


def test_dropping_the_load_compresses_the_field(model):
    inputs = Inputs.design(model.spec)
    inputs.rack_kw *= 0.4
    _, obs = model.steady_state(inputs)
    assert obs.field_scale < 0.6, "a colder hall must scale the pattern down"


def test_lowering_supply_temperature_slides_the_field(model):
    inputs = Inputs.design(model.spec)
    inputs.supply_temp_c = model.spec.supply_temp_c - 6.0
    _, obs = model.steady_state(inputs)
    assert obs.field_offset_k == pytest.approx(-6.0, abs=0.3)
    # the pattern's amplitude should be almost unchanged
    assert obs.field_scale == pytest.approx(1.0, abs=0.35)


def test_remap_reproduces_the_baked_peak_at_the_reference_point(model, manifest):
    """Apply the published remap to the baked peak and confirm it lands on the
    ROM's own hot-aisle temperature — the two descriptions of the same hall must
    agree, or the render will contradict the HUD."""
    from dthall.constants import to_celsius

    state, obs = model.steady_state()
    supply = manifest["reference"]["supply_temp_c"]
    baked_peak = manifest["peak_baked_temp_c"]
    remapped = (
        supply + obs.field_offset_k + (baked_peak - supply) * obs.field_scale
    )
    # The baked peak is a local face maximum, so it sits above the well-mixed
    # hot aisle node but must be the same order.
    hot = to_celsius(state.T_hot)
    assert hot - 2.0 < remapped < hot + 12.0
