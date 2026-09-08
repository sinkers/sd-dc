# Pre-publication review — public GitHub

Review of this working copy against publication as a **public** repository.
Run 2026-09-03 against branch `digital-twin`, 664 tracked files, 48 commits.

**Verdict: NOT READY.** Four blockers, all fixable. Three are concentrated in
`dc-model/`, and the cleanest fix is the split that `PLAN.md` §3.0 already argues
for on architectural grounds.

Method: scanned tracked files and full git history for secret-shaped strings,
key and credential files, third-party documents, client identifiers,
infrastructure identifiers and oversized blobs.

---

## Good news first

- **No secrets in git history.** No `.env`, `.pem`, `.key`, `id_rsa` or
  credential file has ever been committed. 48 commits, all checked.
- **No API keys or tokens** anywhere in tracked files.
- **No oversized blobs in history.** Largest is a 1.6 MB SVG.
- **Six of nine components are clean** or need only trivial fixes:
  `cable-sizing`, `cables`, `digital-twin`, `piping`, `cooling-model`, `vm-setup`.

---

## Blockers

### B1 — Third-party engineering drawings from real projects

**60 PNG page renders** under `dc-model/eval/drawing_locate/img/`, plus **243 eval
items** in `dc-model/eval/drawing_read/items.jsonl`, derived from three named real
projects:

- Mamre Road – Kemps Creek DC (SSD-10101987)
- Cloud Carrier SHDC – Moss Vale (NSW)
- Firmus Bell Bay

One item transcribes a stamp whose answer is literally **`Confidential`**, from
`Mamre Road - Kemps Creek DC (SSD-10101987)/03 EIS & Appendices/018_Appendix 19`.

`portals.yaml` already states the licensing position correctly: the NSW CC-BY 4.0
grant *"explicitly does NOT extend to third-party IP including photographs,
illustrations, drawings, plans, artwork and maps"* — the State publishes drawings
for consultation but cannot license them onward.

**These are in git history as well as the working tree.** Deleting the files is
not sufficient.

### B2 — Vendor copyright material

| Item | Count |
|---|---|
| Ezystrut datasheet PDFs (`cable-tray-ezystrut/datasheets/`) | 3 |
| Ezystrut STEP models (`cable-tray-ezystrut/models/step-files/`) | 8 |

Collected for internal engineering use as a customer. Redistribution from a public
repo is a different act and is not covered. The transcribed `tray_catalogue.json`
is fine — facts and dimensions are not the document.

*(The STEP files under `piping/` and `cooling-model/` are our own generated
output, not vendor CAD. Those are fine.)*

### B3 — Repository size and GitHub hard limits

Before the fix in this change: **2.0 GB across 1,918 untracked-but-unignored
files.** A `git add -A` would have committed OpenFOAM meshes and field data,
including single files above GitHub's 100 MB hard limit:

```
204 MB  cfd-cabinet-cooling/case-au01/constant/polyMesh/faces
139 MB  cfd-cabinet-cooling/case-hall/4000/phi
138 MB  cfd-cabinet-cooling/case-hall/4000/U
```

Root cause: `cfd-cabinet-cooling/.gitignore` patterned only `case/`, and the
newer `case-au01/` and `case-hall/` were never added.

**Fixed in this change** — patterns generalised to `case*/`, and the root
`.gitignore` extended. Now **41 MB across 169 files**.

### B4 — AWS account identifier

`730335486558` appears in **~60 tracked files**, including `dc-model/infra/main.tf`
and 44 generated `dc-model/status/status-*.html` snapshots, as part of the bucket
name `s3://dame-dc-corpus-730335486558-apse2`.

Not a credential, but it identifies the account and assists targeting. The status
snapshots are build artifacts that should not be tracked at all — now gitignored.

---

## Lower severity

| # | Finding | Where | Fix |
|---|---|---|---|
| L1 | Personal email `andrew.sinclair@dame.com.au` | `dc-model/RESUME.md`, `dc-model/deploy/collector-cronjobs.yaml` | Replace with a role address or remove |
| L2 | ~~Default VM password `freecad123`~~ | `INSTALL.md` (×3), `create-vm.sh`, `AGENT_INSTRUCTIONS.md` | ✅ **Fixed 2026-09-04.** My original scan said 3 occurrences in 2 files; it was **5 in 3** — the `AGENT_INSTRUCTIONS.md` one was missed because I grepped only secret-shaped `password[:=]` patterns |
| L3 | Internal OneDrive / SharePoint paths | 54 and 38 files | Redact to a placeholder root |
| L4 | Client site designation `AU01` | 84 files | Decide: publish as-is, or rename to a neutral `HALL-A` |
| L5 | `dametech.net`, `DAME` org | 6 and 5 files | Reveals the client engagement. A judgement call, not a leak |
| L6 | Real project names in prose | `CORPUS.md`, `portals.yaml`, `RESUME.md` | Public planning records, so naming is defensible; the *drawings* are not |
| L7 | ~~`k.html` — stray scraped Korean page, 288 KB~~ | repo root, untracked | ✅ **Deleted 2026-09-04** |

**L4 and L5 are your call, not a security finding.** Publishing `AU01` and
`dametech.net` tells the world you are doing data centre engineering for a
specific client. That may be exactly what you want — the digital twin is already
publicly deployed at `au01-twin.dametech.net`.

---

## Where the problems live

| Component | Issues |
|---|---|
| `dc-model` | **B1, B4**, L1, L3 |
| `cable-tray-ezystrut` | **B2** |
| `cfd-cabinet-cooling` | **B3** (fixed), L3 |
| `vm-setup` | L2 |
| `digital-twin` | L4, L5 |
| `cable-sizing`, `cables`, `piping`, `cooling-model` | clean |

---

## B7 — Third-party calculator captures (found and fixed 2026-09-08)

Eight files under `cable-sizing/reference/`, captured while the standards
comparison was being built:

| File | What it is |
|---|---|
| `elek-cable-sizing-{as,nz,iec,bs,nec}.txt` | Five full page captures from elek.com, each ending `© 2026 ELEK® Software. All Rights Reserved.` |
| `elek-calculator.png` | Screenshot of their calculator UI |
| `jcalc-cable-sizing-as3008.txt` | Page capture from jcalc.com.au |
| `tricab-cable-calc.js` | Tricab's own JavaScript source, header and all |

Same copyright category as B6, and found the same way — untracked, so every
`git ls-files` scan missed them — but in a directory B6 never looked at. B6's
lesson was "check what would be staged"; the part that did not carry over was
"check *every* `reference/` directory, not the one that failed last time."

Unlike B5, withholding them breaks nothing. Every mention in `standards.py`,
`cable_sizing.py` and `test_cable_sizing.py` is a provenance comment or an
`EVIDENCE` string, not a file that gets opened, so a clean checkout still passes.
`compare_elek.py`, `compare_au_nz.py` and `build_tricab_families.py` are our own
work and stay tracked.

Now gitignored; to go to S3 under `vendor/calculators/` with the same
`redistribute: false` sidecar as the B6 material.

## B6 — Vendor screenshots (found and fixed 2026-09-04)

Four PNGs under `cable-tray-ezystrut/reference/`, 3.1 MB, captured from
ezystrut.com.au on 2026-08-16 while the tray catalogue was being built. They are
**Korvest's own product illustrations** — rendered artwork of bends, tees,
crosses, risers and reducers — not our diagrams.

Same copyright category as the datasheets removed in B2, and they were untracked
rather than tracked, so the earlier scans that looked at `git ls-files` missed
them entirely. They would have gone into the first public commit.

Now in `catalogue/ezystrut/local/` in S3, content-addressed with a provenance
sidecar recording `redistribute: false`, and gitignored.

**Lesson for the verify step:** scanning tracked files is not enough when the
next action is `git add -A`. Step 9 now checks what *would* be staged, not just
what is.

## B5 — Standards tables, and a live clean-checkout failure

**Scope corrected 2026-09-04 after the cable-sizing agent pushed back. It is five
files, not one, and the repo is currently broken on a clean checkout.**

Policy: code open source, all data private. Four AS/NZS 3008 table files were
moved to `s3://.../standards/as-nzs-3008/` and gitignored. That was correct — and
incomplete, because the code cannot start without them.

### The live breakage

`as3008_2025.py:36-38` loads three of those files at module scope, and
`as3008.py:22` imports `as3008_2025` at module scope. Verified by hiding the four
files and importing:

```
FileNotFoundError: .../cable-sizing/as3008_impedance_tables.json
```

So a fresh clone fails at `import as3008` — not at first table use. Every test,
the MCP server, the REST API and CI. It works locally only because the files are
still on disk.

**This one is mine.** I moved the data and gitignored it without checking the
code could survive without it. The CI workflow added in Step 7 would fail on its
first run.

### Five files, one fix

| File | Loaded at import by | Size |
|---|---|---|
| `reference_tables.json` | `as3008.py:35` | 40 K |
| `as3008_impedance_tables.json` | `as3008_2025.py:36` | 84 K |
| `as3008_vc_tables.json` | `as3008_2025.py:37` | 188 K |
| `as3008_short_circuit.json` | `as3008_2025.py:38` | 4 K |
| `as3008_ratings.json` | via `as3008_2025` | 4 K |

Same defect class throughout — the import-time I/O flagged in `QUALITY.md` §2,
now in two modules. One lazy `TableStore` covers all five; doing it per-file
would be two changes and two fixtures.

### Fix, in order

1. **One lazy, injectable store** for all five. No module-scope loads.
2. **Split** verbatim table bodies to S3; keep structure, provenance flags,
   clause numbers and single limits (5% / 7% / 11%) public.
3. **Synthetic fixture with stubs for all five**, so CI runs without credentials.
   Tests asserting real AS/NZS values go behind a marker that skips without data.

**Infrastructure is ready** so B5 is a code-only change:
`tools/data_pull_standards.sh` fetches all five files (`--list`, `--check`, or
fetch). Four are already in `s3://.../standards/as-nzs-3008/`; the AS/NZS 3000
split lands in `standards/as-nzs-3000/` when the file is split.

Owner: the cable-sizing agent. Estimate ~45 min once started. They are currently
mid-review of dame-cable and blocked on two decisions from Andrew.

**Do not publish before this lands.** Not only would the tables be in the public
history permanently, the repo would not import.

## Recommended path

**Split `dc-model` into its own private repository.** This removes B1 and B4
entirely, and L1 and most of L3 with them. `PLAN.md` §3.0 already argues for the
split on architectural grounds — the crawlers were built to feed the drawing LLM
and collect *documents*, while the catalogue needs *typed specifications*. One
move, two problems solved.

That leaves this repo as the engineering toolkit, which is the part worth
publishing anyway.

### Steps

1. **Move `dc-model/` to a private repo.** Extract `collector/` first as a shared
   library, per `PLAN.md` §3.0, since both repos will need it.
2. **Remove B2.** Delete the three Ezystrut PDFs and eight STEP files. Keep
   `tray_catalogue.json`, `INDEX.md` and `JOINING_RULES.md` — the transcribed
   facts are ours. Add a `datasheets/README.md` naming the documents and where to
   obtain them from Ezystrut.
3. **Rewrite history, or start fresh.** B1 and B2 are both in history. With only
   48 commits, a fresh repo with a curated initial commit is simpler and safer
   than `git filter-repo`, and loses little.
4. **Fix L1, L2, L7** — three small edits and one deletion.
5. **Decide L4/L5** — keep `AU01` and `dametech.net`, or neutralise.
6. **Add publication furniture** — `LICENSE`, and a `CONTRIBUTING.md` or README
   note stating that catalogue *data* is transcribed from vendor documents under
   fair-dealing for interoperability, with the documents themselves not
   redistributed.
7. **Re-run this review** on the curated tree before the first push.

### Already fixed in this change

- Root `.gitignore` extended: `.venv/`, `*.sqlite`, `*.egg-info/`, generated
  `out/` and `status-*.html`, and corpus/third-party document paths.
- `cfd-cabinet-cooling/.gitignore` generalised from `case/` to `case*/`, closing
  the 2 GB leak — 1,918 untracked files / 2.0 GB down to 169 / 41 MB.

**`.gitignore` does not untrack what is already committed.** The new rules stop
future additions only. These remain tracked and need explicit removal:

```bash
git rm --cached -r dc-model/eval/drawing_locate/img          # 60 files, B1
git rm --cached    dc-model/eval/drawing_read/items.jsonl    # 243 items, B1
git rm --cached -r cable-tray-ezystrut/datasheets            # 3 PDFs, B2
git rm --cached -r 'cable-tray-ezystrut/models/step-files'   # 8 STEP, B2
git rm --cached    dc-model/status/status-*.html             # 44 snapshots, B4
```

And because B1 and B2 are also in history, that still leaves step 3 below.

---

## Verification commands

```bash
# Size and count of anything a `git add -A` would sweep in
git ls-files --others --exclude-standard | wc -l
git ls-files --others --exclude-standard -z | xargs -0 du -ch | tail -1

# Nothing over GitHub's 100 MB limit is stageable
git ls-files --others --exclude-standard -z | xargs -0 du -h | sort -rh | head

# Secret-shaped strings in tracked files
git ls-files -z | xargs -0 grep -lInE \
  'AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE|api[_-]?key.*[:=]|password.*[:=]'

# Account id, email, third-party drawings
git ls-files -z | xargs -0 grep -lI '730335486558'
git ls-files -z | xargs -0 grep -lI 'dame.com.au'
git ls-files | grep -E 'drawing_locate/img|drawing_read|datasheets/.*\.pdf'
```
