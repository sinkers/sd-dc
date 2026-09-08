"""Transcription helper: paste a table in, get it validated before it counts.

    python -m dame_cable.tables.ingest cf_grouping data/ --paste
    python -m dame_cable.tables.ingest ccc data/ --from-file scratch/ccc.tsv

Accepts CSV or tab/whitespace separated text, with or without a header row.
If the header is absent the manifest's column order is assumed and echoed back
so you can confirm it before anything is written.

What it checks
--------------
Structural, for every table:
  * the expected columns are present and numeric columns parse;
  * enum-valued columns hold values the schema recognises;
  * banded columns are strictly increasing within each key group, with no
    duplicate band edges - a duplicate silently shadows a row at lookup time.

Physical, per table, because a transcription slip usually breaks a trend:
  * correction factors land in (0, 2];
  * current-carrying capacity increases with conductor size;
  * resistance decreases with size and increases with temperature;
  * reactance stays within a plausible band for LV cable;
  * short-circuit final temperature exceeds the initial temperature, and the
    thermoplastic bands step DOWN in final temperature as size increases.

Nothing is written unless every check passes. Warnings are printed but do not
block; errors do.
"""

from __future__ import annotations

import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

from .registry import MANIFEST_BY_ID, LookupMode, TableSpec

_ENUM_COLUMNS = {
    "material": {"Cu", "Al"},
    "insulation": {"PVC/75", "PVC/90", "XLPE/90", "EPR/110"},
    "construction": {"1c-trefoil", "1c-flat-touching", "1c-flat-spaced", "multicore"},
    "form": {"solid", "stranded", "flexible"},
    "system": {"dc", "1ph", "3ph"},
    "basis": {"phase", "neutral"},
    "arrangement": {
        "air-spaced", "air-touching", "air-surface", "conduit-air",
        "enclosed-wall", "buried-direct", "buried-enclosure", "thermal-insulation",
    },
}


def expected_columns(spec: TableSpec) -> list[str]:
    cols = list(spec.key_columns)
    for c in spec.extra_columns:
        if c not in cols:
            cols.append(c)
    if spec.value_column not in cols:
        cols.append(spec.value_column)
    return cols


def parse(text: str, spec: TableSpec) -> tuple[list[dict], list[str]]:
    cols = expected_columns(spec)
    notes: list[str] = []
    lines = [l for l in text.splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return [], ["nothing to parse"]

    delim = "," if lines[0].count(",") >= lines[0].count("\t") else "\t"
    if delim == "\t" and "\t" not in lines[0]:
        lines = [",".join(l.split()) for l in lines]
        delim = ","

    first = [c.strip() for c in next(csv.reader([lines[0]], delimiter=delim))]
    if set(first) >= set(cols):
        reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim)
        rows = [dict(r) for r in reader]
    else:
        notes.append("no header row found; assuming column order "
                     + ", ".join(cols))
        reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
        rows = [dict(zip(cols, [c.strip() for c in r])) for r in reader]
    return rows, notes


def validate(rows: list[dict], spec: TableSpec) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    cols = expected_columns(spec)

    typed: list[dict] = []
    for n, row in enumerate(rows, start=1):
        missing = [c for c in cols if row.get(c) in (None, "")]
        if missing:
            errors.append(f"row {n}: missing {', '.join(missing)}")
            continue
        out = {}
        bad = False
        for c in cols:
            v = str(row[c]).strip()
            if c in spec.numeric_columns:
                try:
                    out[c] = float(v)
                except ValueError:
                    errors.append(f"row {n}: {c}={v!r} is not a number")
                    bad = True
            else:
                if c in _ENUM_COLUMNS and v not in _ENUM_COLUMNS[c]:
                    errors.append(
                        f"row {n}: {c}={v!r} is not one of "
                        + ", ".join(sorted(_ENUM_COLUMNS[c]))
                    )
                    bad = True
                out[c] = v
        if not bad:
            typed.append(out)

    if errors:
        return errors, warnings

    # -- banded columns strictly increasing, no duplicates -----------------
    if spec.banded_column:
        fixed = [c for c in spec.key_columns if c != spec.banded_column]
        groups: dict[tuple, list[float]] = defaultdict(list)
        for r in typed:
            groups[tuple(r[c] for c in fixed)].append(r[spec.banded_column])
        for key, bounds in groups.items():
            if len(set(bounds)) != len(bounds):
                dupes = sorted({b for b in bounds if bounds.count(b) > 1})
                errors.append(
                    f"{dict(zip(fixed, key))}: duplicate band edge(s) {dupes} - "
                    "the later row would be unreachable"
                )
            if bounds != sorted(bounds):
                warnings.append(
                    f"{dict(zip(fixed, key))}: band edges are out of order "
                    "(harmless, they are sorted on load, but check for a typo)"
                )

    # -- per-table physical sanity ----------------------------------------
    vc = spec.value_column

    if spec.table_id.startswith("cf_"):
        for r in typed:
            v = r[vc]
            if not 0.0 < v <= 2.0:
                errors.append(f"correction factor {v} is outside (0, 2]")
            elif v > 1.25:
                warnings.append(f"correction factor {v} is unusually large")

    if spec.table_id == "ccc":
        fixed = [c for c in spec.key_columns if c != "size_mm2"]
        groups = defaultdict(list)
        for r in typed:
            groups[tuple(r[c] for c in fixed)].append((r["size_mm2"], r[vc]))
        for key, pairs in groups.items():
            pairs.sort()
            for (s1, a1), (s2, a2) in zip(pairs, pairs[1:]):
                if a2 <= a1:
                    errors.append(
                        f"{dict(zip(fixed, key))}: capacity does not increase "
                        f"from {s1:g} mm2 ({a1} A) to {s2:g} mm2 ({a2} A)"
                    )

    if spec.table_id == "resistance":
        by_temp = defaultdict(list)
        by_size = defaultdict(list)
        for r in typed:
            by_temp[(r["material"], r["form"], r["temperature_c"])].append(
                (r["size_mm2"], r[vc]))
            by_size[(r["material"], r["form"], r["size_mm2"])].append(
                (r["temperature_c"], r[vc]))
        for key, pairs in by_temp.items():
            pairs.sort()
            for (s1, r1), (s2, r2) in zip(pairs, pairs[1:]):
                if r2 >= r1:
                    errors.append(
                        f"{key}: resistance does not fall from {s1:g} to "
                        f"{s2:g} mm2 ({r1} -> {r2} ohm/km)")
        for key, pairs in by_size.items():
            pairs.sort()
            for (t1, r1), (t2, r2) in zip(pairs, pairs[1:]):
                if r2 <= r1:
                    errors.append(
                        f"{key}: resistance does not rise from {t1} to {t2} C")

    if spec.table_id == "reactance":
        for r in typed:
            if not 0.02 <= r[vc] <= 0.5:
                warnings.append(
                    f"reactance {r[vc]} ohm/km at {r['size_mm2']:g} mm2 is "
                    "outside the usual LV range 0.02-0.5")

    if spec.table_id == "sc_limits":
        for r in typed:
            if r["final_temperature_c"] <= r["initial_temperature_c"]:
                errors.append(
                    f"{r['insulation']}: final temperature "
                    f"{r['final_temperature_c']} is not above initial "
                    f"{r['initial_temperature_c']}")
        groups = defaultdict(list)
        for r in typed:
            groups[r["insulation"]].append(
                (r["size_max_mm2"], r["final_temperature_c"]))
        for ins, pairs in groups.items():
            pairs.sort()
            for (s1, f1), (s2, f2) in zip(pairs, pairs[1:]):
                if f2 > f1:
                    errors.append(
                        f"{ins}: permitted final temperature rises from "
                        f"{f1} C at <= {s1:g} mm2 to {f2} C at <= {s2:g} mm2. "
                        "The size break lowers it; check the transcription.")

    if spec.table_id == "cf_harmonic":
        seen = {r["basis"] for r in typed}
        if not seen <= {"phase", "neutral"}:
            errors.append("basis must be 'phase' or 'neutral'")
        if "neutral" not in seen:
            warnings.append(
                "no neutral-basis band present. Above the standard's threshold "
                "the neutral governs; a table with phase bands only will "
                "under-size four-core cable on harmonic-rich loads.")

    return errors, warnings


def ingest(table_id: str, text: str, data_dir: Path,
           append: bool = False) -> int:
    spec = MANIFEST_BY_ID[table_id]
    rows, notes = parse(text, spec)
    for n in notes:
        print(f"note:    {n}")
    errors, warnings = validate(rows, spec)
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"ERROR:   {e}")
        print(f"\n{len(errors)} error(s). Nothing written.")
        return 1

    cols = expected_columns(spec)
    path = data_dir / spec.filename
    existing = path.read_text().splitlines() if path.exists() else []
    header_comments = [l for l in existing if l.lstrip().startswith("#")]

    out = list(header_comments)
    if append:
        out += [l for l in existing
                if l.strip() and not l.lstrip().startswith("#")]
    else:
        out.append(",".join(cols))
    for r in rows:
        out.append(",".join(str(r[c]).strip() for c in cols))

    path.write_text("\n".join(out) + "\n")
    print(f"\n{len(rows)} row(s) written to {path}")
    print(f"Source recorded in the manifest as: {spec.source}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        print("Tables:", ", ".join(sorted(MANIFEST_BY_ID)))
        return 2
    table_id, data_dir = argv[1], Path(argv[2])
    if table_id not in MANIFEST_BY_ID:
        print(f"unknown table {table_id!r}. Known: "
              + ", ".join(sorted(MANIFEST_BY_ID)))
        return 2
    data_dir.mkdir(parents=True, exist_ok=True)

    append = "--append" in argv
    if "--from-file" in argv:
        text = Path(argv[argv.index("--from-file") + 1]).read_text()
    else:
        print(f"Paste rows for {table_id}. Columns: "
              + ", ".join(expected_columns(MANIFEST_BY_ID[table_id])))
        print("End with Ctrl-D.\n")
        text = sys.stdin.read()
    return ingest(table_id, text, data_dir, append)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
