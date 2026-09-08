import math

import pytest

from dthall import topology


def test_au01_spec_matches_the_export_contract():
    spec = topology.from_cfd_export()
    assert spec.name == "AU01"
    assert len(spec.racks) == 24
    assert spec.rack_names[:2] == ["A01", "A02"]
    assert spec.rack_names[-1] == "B12"
    # Concept-A air-side total (PLAN-CONCEPT-A.md): 16 B300 + network + storage
    assert spec.design_load_kw == pytest.approx(741.8, abs=0.1)
    assert sum(1 for r in spec.racks if r.rack_class == "b300") == 16
    # FWCV 40L2 at each end, split into its two independently failable modules
    assert spec.module_names == ["W1", "W2", "E1", "E2"]
    assert spec.installed_capacity_kw == pytest.approx(950.0)
    assert all(m.airflow_m3h == pytest.approx(65000.0) for m in spec.modules)


def test_zones_split_by_row_and_half():
    spec = topology.from_cfd_export()
    assert spec.zone_names == [
        "cold_A_west",
        "cold_A_east",
        "cold_B_west",
        "cold_B_east",
    ]
    # 12 racks per row, so 6 per zone
    counts = {z: 0 for z in spec.zone_names}
    for r in spec.racks:
        counts[r.zone] += 1
    assert set(counts.values()) == {6}
    assert all(z.volume_m3 > 0 for z in spec.zones)
    assert spec.hot_aisle_volume_m3 > 0
    assert spec.return_volume_m3 > spec.hot_aisle_volume_m3


def test_au01_geometry_derives_from_the_json_not_a_transcription():
    spec = topology.from_cfd_export()
    # room 24.13 x 8.2 x 4.09 m to the eave
    assert spec.notes["room_volume_m3"] == pytest.approx(24.13 * 8.2 * 4.09, rel=1e-3)
    # hot aisle: 1.8 m wide, 7.32 m pod, baffled channel to 3.96 m
    assert spec.hot_aisle_volume_m3 == pytest.approx(1.8 * 7.32 * 3.96, rel=1e-3)


def test_case_hall_spec_uses_cfd_function_object_names():
    spec = topology.from_hall_parameters()
    assert spec.name == "case-hall"
    assert len(spec.racks) == 24
    # These are the postProcessing channel tags, so calibration joins on them.
    assert spec.rack_names[0] == "rA00"
    assert spec.rack_names[-1] == "rB11"
    assert spec.design_load_kw == pytest.approx(864.0)
    assert spec.installed_capacity_kw == pytest.approx(950.0)
    assert spec.supply_temp_c == pytest.approx(28.0)
    assert spec.design_delta_t_k == pytest.approx(15.0)
    assert spec.module_names == ["A1", "A2", "B1", "B2"]


def test_case_hall_load_overrides():
    spec = topology.from_hall_parameters(rack_loads_kw={"rA00": 45.0})
    by_name = {r.name: r.design_kw for r in spec.racks}
    assert by_name["rA00"] == 45.0
    assert by_name["rA01"] == 36.0


def test_volumes_are_finite_and_sane():
    for spec in (topology.from_cfd_export(), topology.from_hall_parameters()):
        vols = [z.volume_m3 for z in spec.zones] + [
            spec.hot_aisle_volume_m3,
            spec.return_volume_m3,
        ]
        assert all(math.isfinite(v) and v > 1.0 for v in vols)
