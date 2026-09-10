"""CSV-backed table store.

Design rules, in order of importance:

1. No silent defaults. A lookup that finds nothing raises MissingTableData
   naming the table, the key and the clause of the standard it comes from.
2. No interpolation unless the manifest says the table is interpolable. The
   correction-factor tables in the standard are step tables; interpolating them
   invents numbers the committee did not publish.
3. Every table declares its provenance. `TableSpec.source` is printed in errors
   and in the coverage report, so transcription work is a shopping list rather
   than an archaeology exercise.

The CSV files themselves are deliberately NOT shipped populated. AS/NZS
3008.1.1 and AS/NZS 3000 are licensed documents; the numbers are transcribed
from the licence holder's own copy. `validate.py` reports what is still empty.
"""

from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..errors import MissingTableData


class LookupMode:
    EXACT = "exact"
    #: key column holds the LOWER bound of a band; pick the highest bound <= value
    BAND_FLOOR = "band_floor"
    #: key column holds the UPPER bound of a band; pick the lowest bound >= value
    BAND_CEIL = "band_ceil"


@dataclass(frozen=True)
class TableSpec:
    table_id: str
    source: str
    filename: str
    key_columns: tuple[str, ...]
    value_column: str
    #: at most one key column may be banded; named here
    banded_column: str | None = None
    band_mode: str = LookupMode.EXACT
    numeric_columns: tuple[str, ...] = ()
    #: columns carried alongside the value column, e.g. a basis flag
    extra_columns: tuple[str, ...] = ()
    notes: str = ""


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------
# Clause and table numbers are AS/NZS 3008.1.1:2025 unless marked 3000.
# Verify each against the licensed copy before relying on it in anger; the
# numbering changed between the 2017 and 2025 editions.

MANIFEST: tuple[TableSpec, ...] = (
    TableSpec(
        table_id="ccc",
        source="AS/NZS 3008.1.1:2025 Section 3, current-carrying capacity tables",
        filename="ccc.csv",
        key_columns=("table", "arrangement", "material", "size_mm2"),
        value_column="current_a",
        numeric_columns=("size_mm2", "current_a"),
        notes="Tabulated I_t at the table's own reference conditions. Keyed by "
              "TABLE, because R-TBL-1 resolves insulation and construction into "
              "the table already and keeping them as separate keys would let two "
              "rows disagree. `cores_loaded` is NOT an axis of any base table "
              "(M4 Rev B section 4.4.3): every table is calculated for three "
              "loaded conductors, and the four-loaded-conductor rating is derived "
              "through the Table 3.4 harmonic factor, which is the only mechanism "
              "the standard provides. `arrangement` names one column pair; see "
              "schema.InstallationArrangement.",
    ),
    TableSpec(
        table_id="ccc_reference",
        source="AS/NZS 3008.1.1:2025 Section 3, table headnotes",
        filename="ccc_reference.csv",
        key_columns=("table",),
        value_column="reference_ambient_air_c",
        numeric_columns=("reference_ambient_air_c", "reference_ambient_soil_c",
                         "reference_soil_resistivity_km_w", "reference_depth_m",
                         "max_conductor_c"),
        extra_columns=("reference_ambient_soil_c",
                       "reference_soil_resistivity_km_w", "reference_depth_m",
                       "max_conductor_c"),
        notes="Reference conditions each CCC table is stated at, ONE ROW PER "
              "TABLE (M4 Rev B section 4.2). R-REF-1: one headnote carries both "
              "datums for every table in the family -- 40 C air and 25 C soil -- "
              "so both are recorded on every row. Without these the ambient "
              "correction factor has no datum and cannot be applied.",
    ),
    TableSpec(
        table_id="cf_ambient_air",
        source="AS/NZS 3008.1.1:2025 Table 3.44 (air ambient correction)",
        filename="cf_ambient_air.csv",
        key_columns=("max_conductor_c", "ambient_c"),
        value_column="cf",
        banded_column="ambient_c",
        band_mode=LookupMode.BAND_CEIL,
        numeric_columns=("max_conductor_c", "ambient_c", "cf"),
        notes="BAND_CEIL: a 43 C ambient uses the 45 C row, never the 40 C row.",
    ),
    TableSpec(
        table_id="cf_ambient_soil",
        source="AS/NZS 3008.1.1:2025 soil ambient correction table",
        filename="cf_ambient_soil.csv",
        key_columns=("max_conductor_c", "ambient_c"),
        value_column="cf",
        banded_column="ambient_c",
        band_mode=LookupMode.BAND_CEIL,
        numeric_columns=("max_conductor_c", "ambient_c", "cf"),
    ),
    TableSpec(
        table_id="cf_grouping",
        source="AS/NZS 3008.1.1:2025 grouping correction tables",
        filename="cf_grouping.csv",
        key_columns=("grouping_code", "circuits"),
        value_column="cf",
        banded_column="circuits",
        band_mode=LookupMode.BAND_CEIL,
        numeric_columns=("circuits", "cf"),
        notes="BAND_CEIL. The factor DECREASES as circuits increase, so rounding "
              "the count down raises it -- anti-conservative. 11 circuits bunched "
              "on a surface takes the 12-circuit entry 0.45, not the 10-circuit "
              "0.48. Rev A rounded down and that was a defect, not a convention "
              "(M4 Rev B R-BAND-2). Note also that Table 3.33 tabulates 1 to 10 "
              "individually, so the Rev A worked example -- 5 circuits taking the "
              "4-circuit row -- was rounding a value that needs no rounding.",
    ),
    TableSpec(
        table_id="cf_depth",
        source="AS/NZS 3008.1.1:2025 depth of burial correction",
        filename="cf_depth.csv",
        key_columns=("table", "axis_value", "depth_m"),
        value_column="cf",
        banded_column="depth_m",
        band_mode=LookupMode.BAND_CEIL,
        numeric_columns=("depth_m", "cf"),
        notes="R-ADM-1. Two tables with DIFFERENT axes share this file and are "
              "kept apart by the `table` key: 3.46 applies to cables buried "
              "direct and is keyed by conductor size band, 3.47 applies to "
              "cables in underground wiring enclosures and is keyed by "
              "single-core versus multicore. `axis_value` carries whichever "
              "the table uses. They are not interchangeable.",
    ),
    TableSpec(
        table_id="cf_soil_resistivity",
        source="AS/NZS 3008.1.1:2025 soil thermal resistivity correction",
        filename="cf_soil_resistivity.csv",
        key_columns=("arrangement", "resistivity_km_w"),
        value_column="cf",
        banded_column="resistivity_km_w",
        band_mode=LookupMode.BAND_CEIL,
        numeric_columns=("resistivity_km_w", "cf"),
    ),
    TableSpec(
        table_id="cf_harmonic",
        source="AS/NZS 3008.1.1:2025 Table 3.4, per Clause 3.5.9",
        filename="cf_harmonic.csv",
        key_columns=("third_harmonic_fraction",),
        value_column="cf",
        banded_column="third_harmonic_fraction",
        band_mode=LookupMode.BAND_FLOOR,
        numeric_columns=("third_harmonic_fraction", "cf"),
        extra_columns=("basis", "band_upper_fraction"),
        notes="Extra column `basis` must read 'phase' or 'neutral' and says which "
              "current the corrected capacity is to be compared against. See "
              "rating_factors.harmonic_treatment.",
    ),
    TableSpec(
        table_id="resistance",
        source="AS/NZS 3008.1.1:2025 Section 4, a.c. resistance tables",
        filename="resistance.csv",
        key_columns=("form_class", "construction", "material", "size_mm2",
                     "temperature_c"),
        value_column="r_ohm_per_km",
        numeric_columns=("size_mm2", "temperature_c", "r_ohm_per_km"),
        extra_columns=("source_table",),
        notes="Tabulated at the standard's stated operating temperatures. "
              "Intermediate temperatures are reached by the alpha-20 correction "
              "in voltage_drop.resistance_at, not by interpolating this table.",
    ),
    TableSpec(
        table_id="reactance",
        source="AS/NZS 3008.1.1:2025 Section 4, reactance tables",
        filename="reactance.csv",
        key_columns=("form_class", "construction", "insulation_class",
                     "size_mm2"),
        value_column="x_ohm_per_km",
        numeric_columns=("size_mm2", "x_ohm_per_km"),
        extra_columns=("source_table",),
        notes="Axes are the standard's own. `form_class` splits Table 4.1 "
              "(fixed wiring) from 4.2 (flexible). `construction` is trefoil "
              "or flat_touching for single-core, circular or shaped for "
              "multicore. `insulation_class` is the table axis "
              "(Elastomer|PVC|XLPE), not the Insulation enum. Tabulated "
              "values are for TOUCHING formation; a spaced single-core "
              "arrangement adds the NOTE 1 correction.",
    ),
    TableSpec(
        table_id="mv_per_a_m",
        source="AS/NZS 3008.1.1:2025 Section 4, three-phase/single-phase mV/A/m tables",
        filename="mv_per_a_m.csv",
        key_columns=("system", "material", "insulation", "construction",
                     "size_mm2", "power_factor"),
        value_column="mv_per_a_m",
        numeric_columns=("size_mm2", "power_factor", "mv_per_a_m"),
        notes="Independent check only. voltage_drop computes from R and X; this "
              "table is used by the verification suite to confirm agreement.",
    ),
    TableSpec(
        table_id="sc_limits",
        source="AS/NZS 3008.1.1:2025 Table 5.2, short-circuit temperature limits",
        filename="sc_limits.csv",
        key_columns=("insulation", "size_max_mm2"),
        value_column="final_temperature_c",
        banded_column="size_max_mm2",
        band_mode=LookupMode.BAND_CEIL,
        numeric_columns=("size_max_mm2", "final_temperature_c",
                         "initial_temperature_c"),
        extra_columns=("initial_temperature_c",),
        notes="This is where the 300 mm2 thermoplastic break lives. size_max_mm2 "
              "is the inclusive upper bound of the band; use 1e9 for 'and above'.",
    ),
    TableSpec(
        table_id="pe_min_size",
        source="AS/NZS 3000 Table 5.1, minimum earthing conductor size",
        filename="pe_min_size.csv",
        key_columns=("material", "active_size_mm2"),
        value_column="pe_size_mm2",
        banded_column="active_size_mm2",
        band_mode=LookupMode.BAND_CEIL,
        numeric_columns=("active_size_mm2", "pe_size_mm2"),
    ),
    TableSpec(
        table_id="max_zs",
        source="AS/NZS 3000 maximum earth fault loop impedance tables",
        filename="max_zs.csv",
        key_columns=("device", "rating_a", "disconnection_time_s"),
        value_column="max_zs_ohm",
        numeric_columns=("rating_a", "disconnection_time_s", "max_zs_ohm"),
    ),
)

MANIFEST_BY_ID = {spec.table_id: spec for spec in MANIFEST}


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

def _coerce(spec: TableSpec, row: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if k is None:
            continue
        k = k.strip()
        v = (v or "").strip()
        if k in spec.numeric_columns:
            if v == "":
                out[k] = None
            else:
                out[k] = float(v)
        else:
            out[k] = v
    return out


def _norm(v: Any) -> Any:
    """Normalise a key value so 4 and 4.0 and '4' all match."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, bool):
        return v
    if hasattr(v, "value"):          # Enum
        return v.value
    return v


@dataclass
class LoadedTable:
    spec: TableSpec
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: exact-key index for the non-banded key columns
    index: dict[tuple, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def fixed_keys(self) -> tuple[str, ...]:
        return tuple(k for k in self.spec.key_columns if k != self.spec.banded_column)

    def build_index(self) -> None:
        self.index = {}
        for row in self.rows:
            k = tuple(_norm(row.get(c)) for c in self.fixed_keys)
            self.index.setdefault(k, []).append(row)
        if self.spec.banded_column:
            for bucket in self.index.values():
                bucket.sort(key=lambda r: r[self.spec.banded_column])


class TableStore:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.tables: dict[str, LoadedTable] = {}

    @classmethod
    def load(cls, data_dir: str | Path) -> "TableStore":
        store = cls(data_dir)
        for spec in MANIFEST:
            path = store.data_dir / spec.filename
            table = LoadedTable(spec=spec)
            if path.exists():
                with path.open(newline="", encoding="utf-8") as fh:
                    reader = csv.DictReader(
                        r for r in fh if r.strip() and not r.lstrip().startswith("#")
                    )
                    for raw in reader:
                        row = _coerce(spec, raw)
                        if row.get(spec.value_column) in (None, ""):
                            continue          # placeholder line, not data
                        table.rows.append(row)
            table.build_index()
            store.tables[spec.table_id] = table
        return store

    # -- lookup ------------------------------------------------------------

    def row(self, table_id: str, **key: Any) -> dict[str, Any]:
        """Return the full matching row. Raises MissingTableData if absent."""
        table = self.tables[table_id]
        spec = table.spec
        fixed = tuple(_norm(key.get(c)) for c in table.fixed_keys)
        bucket = table.index.get(fixed)
        if not bucket:
            raise MissingTableData(table_id, key, spec.source)

        if not spec.banded_column:
            return bucket[0]

        want = key.get(spec.banded_column)
        if want is None:
            raise MissingTableData(table_id, key, spec.source)
        want = float(want)
        bounds = [r[spec.banded_column] for r in bucket]

        if spec.band_mode == LookupMode.BAND_CEIL:
            # smallest bound >= want
            i = 0
            while i < len(bounds) and bounds[i] < want:
                i += 1
            if i == len(bounds):
                raise MissingTableData(
                    table_id,
                    {**key, "_reason": f"{want} exceeds the highest band {bounds[-1]}"},
                    spec.source,
                )
            return bucket[i]

        # BAND_FLOOR: largest bound <= want
        i = bisect_right(bounds, want) - 1
        if i < 0:
            raise MissingTableData(
                table_id,
                {**key, "_reason": f"{want} is below the lowest band {bounds[0]}"},
                spec.source,
            )
        return bucket[i]

    def value(self, table_id: str, **key: Any) -> float:
        spec = MANIFEST_BY_ID[table_id]
        return float(self.row(table_id, **key)[spec.value_column])

    def has(self, table_id: str, **key: Any) -> bool:
        try:
            self.row(table_id, **key)
            return True
        except MissingTableData:
            return False

    def sizes_available(self, table_id: str = "ccc", **key: Any) -> list[float]:
        """Ascending conductor sizes present for a given key, minus size_mm2."""
        table = self.tables[table_id]
        keys = [c for c in table.spec.key_columns if c != "size_mm2"]
        target = tuple(_norm(key.get(c)) for c in keys)
        sizes = {
            row["size_mm2"]
            for row in table.rows
            if tuple(_norm(row.get(c)) for c in keys) == target
        }
        return sorted(sizes)

    def counts(self) -> dict[str, int]:
        return {tid: len(t.rows) for tid, t in self.tables.items()}
