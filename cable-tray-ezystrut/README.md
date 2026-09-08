# Cable tray — Ezystrut

Catalogue and parametric geometry for Ezystrut cable support systems, plus the
joining rules that make a generated tray run buildable rather than merely drawn.

## Start here

| File | What |
|---|---|
| `INDEX.md` | **not in this repo** — vendor reference library, see below |
| `tray_catalogue.json` | **not in this repo** — the machine-readable catalogue, 5 families. Fetch it, or use `../cable-sizing/fixtures/tray_catalogue.json` |
| [`JOINING_RULES.md`](JOINING_RULES.md) | which joints are valid where, and why |
| `GUIDELINES.md` | **not in this repo** — carries Ezystrut product data, see below |
| [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) | what was checked against what |
| `cable_tray_router.py` | scripted routing |
| `model_joint_examples.py` | parametric joint geometry in FreeCAD |

Families: **ET5, ET3, ET** (cable tray), **CT**, **NEMA3**.

## Vendor content is not here

Korvest's terms prohibit copying for distribution or reposting to other websites,
and that applies to a markdown transcription exactly as it applies to the PDF.
Removed and held in the private bucket under `vendor/ezystrut/`:

| | What it was |
|---|---|
| `datasheets/*.pdf`, `models/step-files/` | the source documents and CAD |
| `INDEX.md` | reference library built from their datasheets |
| `GUIDELINES.md` | design guidance carrying their ET3/ET5/CT depths and load-span tables |
| `tray_catalogue.json` | the machine-readable catalogue |

**What stayed, because it is ours:** `JOINING_RULES.md` — why raised side rails
mean you cannot butt two components together, and what follows from that — and
`VERIFICATION_REPORT.md`, which records bugs found in our own FreeCAD model.
Both are engineering analysis, not transcription.

Fetch the rest with `../tools/data_pull_vendor.sh`, or get the datasheets free
from <https://www.ezystrut.com.au/catalogues-and-downloads/>. See
[`datasheets/README.md`](datasheets/README.md).

The product pages are now crawled as well as the PDFs, so the next transcription
is reproducible and diffable against its source rather than being a hand copy
with no captured original.

## Status

Working. 2,433 lines, **no tests** — `QUALITY.md` puts golden tests on catalogue
selection and joint rules at priority 3, roughly a day. Worth doing before the
layout engine starts calling this for tray fill.
