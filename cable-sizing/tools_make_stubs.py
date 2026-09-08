"""Generate empty CSV stubs from the manifest, one per table."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dame_cable.tables.registry import MANIFEST

out = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
out.mkdir(parents=True, exist_ok=True)
for spec in MANIFEST:
    cols = list(spec.key_columns)
    for c in spec.extra_columns:
        if c not in cols:
            cols.append(c)
    if spec.value_column not in cols:
        cols.append(spec.value_column)
    path = out / spec.filename
    if path.exists():
        continue
    lines = [
        f"# {spec.table_id}",
        f"# Source: {spec.source}",
        f"# Lookup: {spec.band_mode} on {spec.banded_column or '(no banded column)'}",
    ]
    if spec.notes:
        for chunk in spec.notes.split(". "):
            if chunk.strip():
                lines.append(f"# {chunk.strip().rstrip('.')}.")
    lines.append("# Transcribe from the licensed copy. Rows with an empty value "
                 "column are ignored.")
    lines.append(",".join(cols))
    path.write_text("\n".join(lines) + "\n")
    print("wrote", path)
