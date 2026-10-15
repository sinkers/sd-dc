"""Cut the case-hall CFD probes down to what the validation gate reads.

    python3 tools/extract_cfd_reference.py [CASE_DIR]

The ROM is calibrated and validated against case-hall's function-object output
(`postProcessing/<tag>/<time>/surfaceFieldValue.dat`). The full output is
15 MB and lives in S3 with the rest of the solved case, so a fresh checkout
and CI cannot run the gate. The gate only reads the last 500 iterations of each
channel (cfddata.WINDOW_ROWS samples at writeInterval 20), so this keeps the
last KEEP samples of every channel, with its header, in
rom/dthall/data/case_hall_reference/<tag>.dat.

cfddata reads the full case when it is on disk and falls back to this extract
when it is not. Re-run after a new case-hall solve, and commit the result.
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1] / "cfd-cabinet-cooling" / "case-hall"
OUT = HERE.parent / "rom" / "dthall" / "data" / "case_hall_reference"

#: Four times the validation window, so a wider window can be tried without
#: going back to S3.
KEEP = 100


def extract(case: Path = CASE, out: Path = OUT, keep: int = KEEP) -> int:
    post = case / "postProcessing"
    if not post.is_dir():
        raise SystemExit(f"no postProcessing under {case}; pull the solved case "
                         "from S3 first (cfd-cabinet-cooling/README.md)")
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for tag_dir in sorted(p for p in post.iterdir() if p.is_dir()):
        files = sorted(glob.glob(str(tag_dir / "*" / "surfaceFieldValue.dat")))
        if not files:
            continue                        # e.g. limits/: not a probe
        header: list[str] = []
        rows: dict[float, str] = {}
        for fn in files:
            with open(fn) as fh:
                for line in fh:
                    if line.startswith("#"):
                        if not rows and line not in header:
                            header.append(line)
                    elif line.split():
                        rows[float(line.split()[0])] = line
        kept = [rows[k] for k in sorted(rows)][-keep:]
        (out / f"{tag_dir.name}.dat").write_text("".join(header + kept))
        n += 1
    return n


if __name__ == "__main__":
    case = Path(sys.argv[1]) if len(sys.argv) > 1 else CASE
    print(f"{extract(case)} channels written to {OUT}")
