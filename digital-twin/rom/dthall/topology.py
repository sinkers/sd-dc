"""Hall topology: the node graph the ROM integrates.

A `HallSpec` is a purely geometric/nameplate description — no calibration
parameters, no state. Two loaders build one:

  * `from_cfd_export()`   - the as-built AU01 room, from the FreeCAD export
                            contract `cfd_export_params.json`. This is what the
                            twin runs.
  * `from_hall_parameters()` - the parametric `case-hall` model, from its
                            `system/hallParameters`. This is what the ROM is
                            calibrated against, because it is the case with
                            result data on disk. Rack names match the CFD
                            function-object tags (rA00 ... rB11) so calibration
                            can join on them directly.

Both produce the same node graph:

    4 fan-wall modules -> 4 cold zones -> 24 racks -> hot aisle -> return -> modules

Cold zones are (row A | row B) x (west half | east half) of the pod. The split
by half is what lets a single fan-wall module going offline produce an
asymmetric result; the split by row is what lets the two rows differ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .constants import to_kelvin

# The AU01 Concept-A load map (PLAN-CONCEPT-A.md). Air-side kW only: the B300
# racks also reject ~68.25 kW each to liquid, which is out of scope for the
# air-side twin.
B300_SCHEDULE_KW = {
    "A01": (0.0, "spare"),
    "A02": (36.75, "b300"),
    "A03": (36.75, "b300"),
    "A04": (36.75, "b300"),
    "A05": (36.75, "b300"),
    "A06": (40.0, "ib_leaf"),
    "A07": (45.0, "ib_spine"),
    "A08": (36.75, "b300"),
    "A09": (36.75, "b300"),
    "A10": (36.75, "b300"),
    "A11": (36.75, "b300"),
    "A12": (15.0, "storage"),
    "B01": (0.0, "spare"),
    "B02": (36.75, "b300"),
    "B03": (36.75, "b300"),
    "B04": (36.75, "b300"),
    "B05": (36.75, "b300"),
    "B06": (40.0, "ib_leaf"),
    "B07": (13.8, "ethernet"),
    "B08": (36.75, "b300"),
    "B09": (36.75, "b300"),
    "B10": (36.75, "b300"),
    "B11": (36.75, "b300"),
    "B12": (0.0, "spare"),
}


@dataclass(frozen=True)
class RackSpec:
    name: str  # telemetry / actor binding key, e.g. "A05" or "rA04"
    row: str  # "A" or "B"
    position: int  # 0-based position along the row, west to east
    design_kw: float  # nameplate air-side load
    rack_class: str  # "b300", "ib_leaf", "net", ...
    zone: str  # cold zone it breathes from


@dataclass(frozen=True)
class ModuleSpec:
    name: str  # "W1" / "W2" / "E1" / "E2" (AU01) or "A1".."B2" (case-hall)
    end: str  # "west" or "east"
    airflow_m3h: float  # nameplate volumetric flow at full speed
    capacity_kw: float  # net sensible cooling capacity


@dataclass(frozen=True)
class ZoneSpec:
    name: str
    row: str
    half: str  # "west" or "east"
    volume_m3: float


@dataclass(frozen=True)
class HallSpec:
    name: str
    racks: tuple[RackSpec, ...]
    modules: tuple[ModuleSpec, ...]
    zones: tuple[ZoneSpec, ...]
    hot_aisle_volume_m3: float
    return_volume_m3: float
    supply_temp_c: float
    design_delta_t_k: float
    allowable_max_c: float
    recommended_max_c: float
    notes: dict = field(default_factory=dict)

    # -- convenience lookups -------------------------------------------------
    @property
    def rack_names(self) -> list[str]:
        return [r.name for r in self.racks]

    @property
    def module_names(self) -> list[str]:
        return [m.name for m in self.modules]

    @property
    def zone_names(self) -> list[str]:
        return [z.name for z in self.zones]

    @property
    def design_load_kw(self) -> float:
        return sum(r.design_kw for r in self.racks)

    @property
    def installed_capacity_kw(self) -> float:
        return sum(m.capacity_kw for m in self.modules)

    def zone_index(self, name: str) -> int:
        return self.zone_names.index(name)

    def rack_zone_indices(self) -> list[int]:
        return [self.zone_index(r.zone) for r in self.racks]

    def supply_temp_k(self) -> float:
        return to_kelvin(self.supply_temp_c)


def _zone_name(row: str, half: str) -> str:
    return f"cold_{row}_{half}"


def _build_zones(row_letters, cold_volume_per_zone_m3) -> tuple[ZoneSpec, ...]:
    return tuple(
        ZoneSpec(_zone_name(row, half), row, half, cold_volume_per_zone_m3)
        for row in row_letters
        for half in ("west", "east")
    )


def _assign_zone(row: str, position: int, racks_per_row: int) -> str:
    half = "west" if position < racks_per_row / 2 else "east"
    return _zone_name(row, half)


# ---------------------------------------------------------------------------
# AU01 as-built (the twin's live configuration)
# ---------------------------------------------------------------------------

# The AU01 geometry contract. A copy is packaged with dthall so a container can be
# built from digital-twin/ alone; the sibling CFD tree stays authoritative for
# local work, and `python3 viewer/prepare_geometry.py` refreshes the copy.
_PACKAGED_EXPORT = Path(__file__).with_name("au01_export_params.json")
_SIBLING_EXPORT = (
    Path(__file__).resolve().parents[3]
    / "cfd-cabinet-cooling"
    / "geometry"
    / "CFD_Export_RevE"
    / "cfd_export_params.json"
)
DEFAULT_CFD_EXPORT = (
    _SIBLING_EXPORT if _SIBLING_EXPORT.exists() else _PACKAGED_EXPORT
)


def from_cfd_export(
    path: str | Path = DEFAULT_CFD_EXPORT,
    schedule: dict[str, tuple[float, str]] | None = None,
    design_delta_t_k: float = 15.0,
) -> HallSpec:
    """Build the AU01 spec from the FreeCAD CFD export contract.

    `schedule` maps rack number ("A05") to (air kW, class). Defaults to the
    Concept-A B300 map; pass the export's own `rack_schedule_kw` to reproduce
    the uniform HD/NET case instead.
    """
    p = json.loads(Path(path).read_text())
    mm = p["scale"]  # 0.001, model mm -> m

    room = p["room"]
    room_x = [v * mm for v in room["x"]]
    room_y = [v * mm for v in room["y"]]
    eave = room["eave"] * mm

    hac = p["hac"]
    hac_x = [v * mm for v in hac["x"]]
    hac_y = [v * mm for v in hac["y"]]
    baffle_z = [v * mm for v in hac["baffle_z"]]

    rows = p["racks"]["rows"]
    rack_h = p["racks"]["h"] * mm
    pod_len = hac_x[1] - hac_x[0]

    schedule = schedule or B300_SCHEDULE_KW
    racks_per_row = len([k for k in schedule if k.startswith("A")])

    racks = []
    for row in ("A", "B"):
        for i in range(racks_per_row):
            key = f"{row}{i + 1:02d}"
            kw, klass = schedule[key]
            racks.append(
                RackSpec(
                    name=key,
                    row=row,
                    position=i,
                    design_kw=kw,
                    rack_class=klass,
                    zone=_assign_zone(row, i, racks_per_row),
                )
            )

    # Cold aisle for row A is the strip from the wall to the row's intake face;
    # for row B it is the strip from its intake face to the far wall. Zone
    # volume runs the full free height and half the pod length.
    cold_depth = {
        "A": rows["A"]["intake_y"] * mm - room_y[0],
        "B": room_y[1] - rows["B"]["intake_y"] * mm,
    }
    zones = tuple(
        ZoneSpec(
            _zone_name(row, half),
            row,
            half,
            cold_depth[row] * (pod_len / 2.0) * eave,
        )
        for row in ("A", "B")
        for half in ("west", "east")
    )

    hot_volume = (hac_y[1] - hac_y[0]) * pod_len * baffle_z[1]

    fw = p["fanwall"]
    fw_w = (fw["y"][1] - fw["y"][0]) * mm
    fw_d = (fw["w_x"][1] - fw["w_x"][0]) * mm
    fw_top = fw["top"] * mm
    rack_solid = len(racks) * 0.6 * 1.2 * rack_h

    room_volume = (room_x[1] - room_x[0]) * (room_y[1] - room_y[0]) * eave
    return_volume = max(
        50.0,
        room_volume
        - hot_volume
        - rack_solid
        - 2 * fw_w * fw_d * fw_top
        - sum(z.volume_m3 for z in zones),
    )

    # FWCV 40L2 at each end = 2 x 40L1 modules; the JSON quotes per-end totals.
    per_end_m3h = 130000.0
    per_end_kw = 475.0
    modules = tuple(
        ModuleSpec(f"{tag}{i}", end, per_end_m3h / 2.0, per_end_kw / 2.0)
        for tag, end in (("W", "west"), ("E", "east"))
        for i in (1, 2)
    )

    return HallSpec(
        name="AU01",
        racks=tuple(racks),
        modules=modules,
        zones=zones,
        hot_aisle_volume_m3=hot_volume,
        return_volume_m3=return_volume,
        supply_temp_c=28.0,
        design_delta_t_k=design_delta_t_k,
        allowable_max_c=35.0,
        recommended_max_c=27.0,
        notes={
            "source": str(path),
            "containment": hac["scheme"],
            "room_volume_m3": round(room_volume, 1),
        },
    )


# ---------------------------------------------------------------------------
# case-hall (the calibration configuration)
# ---------------------------------------------------------------------------

DEFAULT_HALL_PARAMETERS = (
    Path(__file__).resolve().parents[3]
    / "cfd-cabinet-cooling"
    / "case-hall"
    / "system"
    / "hallParameters"
)


def read_hall_parameters(path: str | Path = DEFAULT_HALL_PARAMETERS) -> dict:
    """Parse `key value` lines out of hallParameters, dropping # comments.

    Mirrors make_hall_dicts.read_params so the ROM reads the same file the CFD
    was generated from rather than a transcription of it.
    """
    out: dict[str, object] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0]
        if len(parts) == 1:
            out[key] = ""
            continue
        val = " ".join(parts[1:])
        try:
            out[key] = float(val)
        except ValueError:
            out[key] = val
    return out


def from_hall_parameters(
    path: str | Path = DEFAULT_HALL_PARAMETERS,
    rack_loads_kw: dict[str, float] | None = None,
) -> HallSpec:
    """Build a spec matching the parametric case-hall CFD model.

    Rack names are the CFD function-object tags (rA00 ... rB11), so per-rack
    calibration data joins on `name` with no translation layer.
    """
    p = read_hall_parameters(path)

    n = int(p["nRacksPerRow"])
    pitch = float(p["rackPitch"])
    pod_len = n * pitch
    side = float(p["sideAisle"])
    plenum_floor = float(p["plenumFloorZ"])
    plenum_h = float(p["plenumHeight"])
    hall_w = float(p["hallWidth"])
    hot_w = float(p["hotAisleWidth"])
    rack_d = float(p["rackDepth"])
    cont_z = plenum_floor - float(p["containmentGap"])

    unit_d = float(p["unitDepth"])
    unit_w = float(p["unitWidth"])
    unit_h = float(p["unitHeight"])
    rear_gap = float(p["rearGap"])
    clearance = float(p["clearance"])
    lx = 2 * (rear_gap + unit_d + clearance) + pod_len

    load_kw = float(p["rackLoad_kW"])
    racks = []
    for row in ("A", "B"):
        for i in range(n):
            name = f"r{row}{i:02d}"
            kw = (rack_loads_kw or {}).get(name, load_kw)
            racks.append(
                RackSpec(
                    name=name,
                    row=row,
                    position=i,
                    design_kw=kw,
                    rack_class="hd",
                    zone=_assign_zone(row, i, n),
                )
            )

    zones = tuple(
        ZoneSpec(
            _zone_name(row, half),
            row,
            half,
            side * (pod_len / 2.0) * plenum_floor,
        )
        for row in ("A", "B")
        for half in ("west", "east")
    )

    hot_volume = hot_w * pod_len * cont_z

    hall_volume = lx * hall_w * (plenum_floor + plenum_h)
    rack_solid = len(racks) * pitch * rack_d * float(p["rackHeight"])
    unit_solid = 2 * unit_d * unit_w * unit_h
    return_volume = max(
        50.0,
        hall_volume
        - hot_volume
        - rack_solid
        - unit_solid
        - sum(z.volume_m3 for z in zones),
    )

    per_module_m3h = float(p["unitAirflow_m3h"])
    per_module_kw = float(p["unitCapacity_kW"])
    n_mod = int(p["modulesPerUnit"])
    modules = tuple(
        ModuleSpec(f"{tag}{i + 1}", end, per_module_m3h, per_module_kw)
        for tag, end in (("A", "west"), ("B", "east"))
        for i in range(n_mod)
    )

    return HallSpec(
        name="case-hall",
        racks=tuple(racks),
        modules=modules,
        zones=zones,
        hot_aisle_volume_m3=hot_volume,
        return_volume_m3=return_volume,
        supply_temp_c=float(p["supplyTemp_C"]),
        design_delta_t_k=float(p["serverDeltaT_K"]),
        allowable_max_c=float(p["allowableMax_C"]),
        recommended_max_c=float(p["recommendedMax_C"]),
        notes={"source": str(path), "hall_volume_m3": round(hall_volume, 1)},
    )
