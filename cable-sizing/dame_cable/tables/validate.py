"""Coverage report - what still has to come out of the licensed copy.

`python -m dame_cable.tables.validate data/` prints, per table, how many rows
are loaded and which standard reference they come from, and flags the tables
that are empty. A calculation cannot start against an empty table; this turns
that from a runtime surprise into a checklist.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .registry import MANIFEST, TableStore


def coverage(store: TableStore) -> list[dict]:
    out = []
    for spec in MANIFEST:
        table = store.tables[spec.table_id]
        path = store.data_dir / spec.filename
        out.append({
            "table_id": spec.table_id,
            "rows": len(table.rows),
            "file_present": path.exists(),
            "source": spec.source,
            "notes": spec.notes,
        })
    return out


def render(store: TableStore) -> str:
    rows = coverage(store)
    width = max(len(r["table_id"]) for r in rows)
    lines = [f"Table coverage in {store.data_dir}", ""]
    empty = []
    for r in rows:
        state = "missing file" if not r["file_present"] else (
            f'{r["rows"]} rows' if r["rows"] else "EMPTY")
        if r["rows"] == 0:
            empty.append(r)
        lines.append(f"  {r['table_id']:<{width}}  {state:<14}  {r['source']}")
    lines.append("")
    if empty:
        lines.append(f"{len(empty)} table(s) still to transcribe:")
        for r in empty:
            lines.append(f"  - {r['table_id']}: {r['source']}")
            if r["notes"]:
                lines.append(f"      {r['notes']}")
    else:
        lines.append("All tables have data.")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    data_dir = Path(argv[1]) if len(argv) > 1 else Path("data")
    store = TableStore.load(data_dir)
    print(render(store))
    return 0 if all(c["rows"] for c in coverage(store)) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
