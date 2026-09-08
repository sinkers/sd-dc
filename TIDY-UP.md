# Tidy-up — move, split, and publish

Ordered plan to get this repo out of `~/Downloads`, its bulk into S3, and the
result publishable. Findings in [`PUBLISH-REVIEW.md`](PUBLISH-REVIEW.md), code
quality in [`QUALITY.md`](QUALITY.md), next phase in [`PLAN.md`](PLAN.md).

**Done means:** a repo at `~/workspace/sd-dc` that a stranger can clone,
understand and run, containing nothing we lack the right to publish, with its
2.4 GB of solver output in S3 where cluster workers can reach it.

Rough total: **1.5 days**, plus the Step 0 decisions.

---

## Step 0 — Three decisions (blocking)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Monorepo or separate repos? | **Monorepo** at `~/workspace/sd-dc`, `dc-model` split out privately. See §D1 below |
| D2 | Split `dc-model` to its own private repo? | **Yes** — removes 3 of 4 publication blockers, and `QUALITY.md` §5 shows it is also the least tested code |
| D3 | Keep `AU01` (84 files) and `dametech.net` (6 files)? | **Keep** — the twin is already public at that domain. Not a security finding |

### D1 — why monorepo, for now

`PLAN.md` §1a makes every component an independent service, which sounds like an
argument for separate repos. It is the opposite, for three reasons:

- **The interfaces are about to change weekly.** The catalogue schema and the IR
  do not exist yet, and every component will consume them. Cross-repo version
  coordination on an interface that is still moving is pure friction.
- **It is small.** 664 tracked files, ~40 MB after the S3 move. Nothing about
  this needs splitting on size grounds.
- **The service pattern makes splitting cheap later.** That is the point of §1a.
  Once a component talks HTTP and owns its data, `git subtree split` moves it out
  in an afternoon.

So: one repo, structured so that splitting is a decision you can defer until the
interfaces stabilise. Two exceptions, both now: `dc-model` (private, D2) and
`collector/` extracted as a shared library (`PLAN.md` §3.0).

```
~/workspace/
├── sd-dc/              this repo, public
└── dc-model/           private — training corpus, crawlers, DC-1
```

---

## Step 1 — Move to the workspace  ·  ✅ DONE 2026-09-04

Moved to `~/workspace/sd-dc`. Same device, so the move was a rename.

Verified after: HEAD unchanged (`7876578`), 664 tracked files, 85 status lines —
all identical to before. **421 tests green** (152 + 150 cable-sizing, 119
digital-twin). MCP server re-registered at the new path and reconnected.

Also done: deleted the two virtualenvs (1.3 GB, regenerable) — repo 4.3 GB → 3.1 GB.

Path fixes applied, all four files syntax-checked:

| File | Fix |
|---|---|
| `generate_verification_report.py` | `BASE_DIR` → `__file__`-derived |
| `generate_joint_reference_sheet.py` | `OUTPUT_PATH` → `__file__`-derived, `import os` added |
| `model_joint_examples.py` | `save_path` → `_THIS_DIR`; defined `_THIS_DIR` with the FreeCAD-exec fallback |
| `cables/model_cable_system.py`, `MCP.md` | fallback paths repointed |

The FreeCAD-console fallbacks are kept deliberately — that context has no
`__file__` — but now point at `~/workspace/sd-dc`.

<details><summary>Original instructions</summary>

Mechanical, no code change, so it is safe to do before any test work.

```bash
git -C ~/Downloads/sd-dc status --short      # confirm nothing uncommitted matters
mv ~/Downloads/sd-dc ~/workspace/sd-dc
```

Then fix the five tracked files that hard-code the absolute path:

| File | Line | Breaks on move? |
|---|---|---|
| `cable-tray-ezystrut/generate_verification_report.py` | 15 — `BASE_DIR = "/Users/.../cable-tray-ezystrut"` | **Yes, unconditional** |
| `cable-tray-ezystrut/generate_joint_reference_sheet.py` | 10 — `OUTPUT_PATH` | **Yes** |
| `cable-tray-ezystrut/model_joint_examples.py` | 12, 665 — exec hint + `save_path` | 665 yes; 12 is a FreeCAD-console usage hint |
| `cables/model_cable_system.py` | 8, 52 | No — 52 falls back only when `__file__` is absent (FreeCAD exec context) |
| `cable-sizing/MCP.md` | 14, 25 — registration command | Docs only, but the live registration does break |

Replace the unconditional ones with the `os.path.dirname(os.path.abspath(__file__))`
pattern `cables/model_cable_system.py:52` already uses correctly. Then:

```bash
claude mcp remove cable-sizing
claude mcp add cable-sizing -- python3 ~/workspace/sd-dc/cable-sizing/mcp_server.py
grep -rn "Downloads/sd-dc" . --exclude-dir=.git     # should return nothing
```

</details>

---

## Step 2 — Large data to S3  ·  ✅ DONE 2026-09-04

Bucket **`s3://sd-dc-artifacts-730335486558-apse2`** created in ap-southeast-2:
versioning on, public access blocked, SSE-S3 default encryption, lifecycle
(IA at 90 d, non-current expiry 180 d, abort stale multipart at 7 d).

Tooling written and validated:

| File | Purpose |
|---|---|
| `cfd-cabinet-cooling/tools/data_push.sh` | push a solved case + manifest |
| `cfd-cabinet-cooling/tools/data_pull.sh` | `--list`, `--info`, or fetch |
| `cfd-cabinet-cooling/tools/iam-worker-readonly.json` | read-only worker policy |

`case` pushed and verified: 47 objects, 130 MiB, SHA-256 byte-identical on
round-trip. Note 130 MiB from a 358 MB directory — the exclusions (`log.*`, `0/`,
`0.orig/`, `postProcessing/`, `uniform/`) are 60% of the bytes.

All three cases pushed and verified — **185 objects, 1.7 GiB**, no errors, no
stale multipart uploads:

| Case | Objects | Size in S3 | On disk |
|---|---:|---:|---:|
| `case` | 47 | 137 MB | 375 MB |
| `case-au01` | 20 | 906 MB | 956 MB |
| `case-hall` | 118 | 758 MB | 1,153 MB |

SHA-256 round-trip verified on a mesh file, a temperature field and the 138 MB
`case-hall/4000/U` — all byte-identical.

**Design point that earned itself immediately.** `data_push.sh` refuses to file a
solution under a sha whose `system/` or `constant/` is modified — and on the very
first run it caught exactly that, because the case dictionaries are currently
dirty. All three cases are therefore filed as `7876578008ca-dirty`, and the
manifest carries `dictionaries_dirty: true`. Re-push under a clean sha once the
dictionary changes are committed.

<details><summary>Original plan</summary>


2.37 GB of OpenFOAM output, none of it in git, all of it needed by cluster
workers.

| Case | Total | Mesh | Solutions | Keep? |
|---|---:|---:|---:|---|
| `case` | 358 MB | 64 MB | 67 MB | Yes |
| `case-au01` | 913 MB | 376 MB | 489 MB | Yes |
| `case-hall` | 1,101 MB | 104 MB | 620 MB | Yes |

**Solutions are the expensive artifact** — hours of solve each. Meshes are
regenerable but slow. Both worth keeping; logs and intermediate iterations are
not.

### Layout

Reuse the pattern `dc-model/DATA-PLATFORM.md` §2 already established —
content-addressed, immutable, provenance sidecar — but a separate bucket, since
the corpus bucket goes private with `dc-model`.

```
s3://sd-dc-artifacts-<acct>-apse2/
├── cfd/<case>/<git-sha>/
│   ├── manifest.json        solver version, wall time, convergence, host
│   ├── constant/polyMesh/
│   └── <time>/              solution fields
└── geometry/<sha256>/       STL/STEP exports, content-addressed
```

**CFD is keyed by case + git sha, not content hash.** A solution is only
meaningful against the case dictionaries that produced it, and content-addressing
a 600 MB directory buys nothing. Geometry is small and dedupes well, so it gets
content-addressing.

`manifest.json` is what lets a worker decide whether a solution is usable
without downloading it. Do not skip it.

### Work

1. Create the bucket, `apse2`, versioning on, lifecycle to IA after 90 days.
2. `tools/data_push.sh` and `tools/data_pull.sh` — `aws s3 sync` plus manifest
   write/verify.
3. IAM: read-only role for cluster workers, read-write for your user.
4. `cfd-cabinet-cooling/README.md` — document how to fetch a case before solving.
5. Confirm a pull works from a cluster node, not just your laptop.

Do **not** store: `.venv`, `log.*`, intermediate time directories, anything
`./run.sh` regenerates in under a minute.

</details>

---

## Step 3 — Split out `dc-model`  ·  ✅ DONE 2026-09-04

Three repos now, not one. `git subtree split` preserved dc-model's 33 commits in
the private repo — the right home for that history, since the drawings in it are
exactly what makes it private.

Results: **sd-dc 664 → 244 tracked files, 3.1 GB → 2.4 GB.** Blockers **B1**
(third-party DA drawings) and **L1** (personal email) cleared outright. **B4**
(AWS account id) went from 61 files to zero outside the review docs — the
scripts now require `SDDC_ARTIFACTS_BUCKET` and the IAM policy ships an
`<ACCOUNT_ID>` placeholder.

`collector/` was extracted to `sddc-collector` first, with the tests
`QUALITY.md` §5 asked for: **69 tests, `core.py` at 99%**, no network, no AWS.

Two things found on the way:
- dc-model's `.gitignore` had `dc-model/status/` and `dc-model/out/` — paths
  relative to the old parent, so they never matched. 44 generated status
  snapshots had been tracked as a result. Fixed and untracked in the new repo.
- All 421 sd-dc tests still green after the split.

<details><summary>Original plan</summary>


Removes blockers **B1** (third-party DA drawings, one stamped `Confidential`) and
**B4** (AWS account id), plus **L1** and most of **L3**.

1. Extract `collector/` into a shared library first — both repos need it
   (`PLAN.md` §3.0), and it is cheapest while `dc-model` is its only consumer.
   Per `QUALITY.md` §5, **write its tests as part of the extraction**: it does
   network I/O, politeness and rate limiting, all of which fail quietly.
2. Move `dc-model/` into `~/workspace/dc-model`, fresh private repo.
3. Leave a stub `dc-model/README.md` here pointing at it, so the architecture
   still reads coherently.
4. Update `README.md` and `PLAN.md` to describe it as external.

</details>

---

## Step 4 — Remove vendor copyright material  ·  ✅ DONE 2026-09-04

**B2 cleared.** 3 Ezystrut PDFs and 8 STEP models untracked and gitignored;
`datasheets/README.md` explains what they were and where to get them free.
`tray_catalogue.json` keeps the transcribed dimensions.

Beyond the plan: Ezystrut is now **crawled**, not just removed. 10 catalogues
(53.5 MB) plus the 3 local datasheets and 8 STEP models are in
`s3://.../catalogue/ezystrut/`, fetched by `catalogue/crawl.py` through
`sddc-collector` — the first use of the extracted library for the catalogue path.

Korvest's terms turned out stronger than ABB's: they name PDFs, prohibit
commercial use without written permission, and prohibit reposting to other
websites. Recorded verbatim in `catalogue/sources.yaml` with `redistribute:
false`, which the provenance sidecar carries onto every object.

<details><summary>Original plan</summary>


Blocker **B2**.

```bash
git rm -r --cached cable-tray-ezystrut/datasheets            # 3 Ezystrut PDFs
git rm -r --cached cable-tray-ezystrut/models/step-files     # 8 Ezystrut STEP
```

Keep `tray_catalogue.json`, `INDEX.md`, `JOINING_RULES.md`, `GUIDELINES.md` —
transcribed facts are ours, the documents are not. Add
`cable-tray-ezystrut/datasheets/README.md` naming each document and where to get
it, so the catalogue stays traceable.

`piping/` and `cooling-model/` STEP files are our own output. Leave them.

</details>

---

## Step 5 — Small fixes  ·  ✅ DONE 2026-09-04

| Item | Action |
|---|---|
| ~~`k.html` — 288 KB stray scraped Korean page~~ | ✅ deleted |
| ~~`freecad123`~~ | ✅ done. Was **5 occurrences in 3 files**, not 3 in 2 — `AGENT_INSTRUCTIONS.md` was missed by the original scan. `INSTALL.md` now carries a generate-your-own placeholder, `create-vm.sh` points at the SSH key, the redundant password line is gone |
| `andrew.sinclair@dame.com.au`, 44 tracked `status-*.html` | only in `dc-model` — resolved by Step 3. Verify after |

---

## Step 6 — Fresh repo with a curated first commit  ·  ✅ DONE 2026-09-08

**B1 and B2 are in git history**, so deleting files is not enough. With 48
commits there is little to lose, and a fresh repo cannot leave a missed blob
behind the way `filter-repo` can.

```bash
cd ~/workspace/sd-dc
rm -rf .git
git init && git add -A && git status      # READ THIS LIST IN FULL
git commit -m "SD-DC: toolkit for AI-led data centre design"
```

That `git status` listing is the last gate before publication.

**What the gate caught.** 442 files staged on the first pass. Reading the list in
full found two things no scan had:

- `.claude/scheduled_tasks.json` — Claude Code session state. It had been in
  `.git/info/exclude`, which `rm -rf .git` discarded. Now in `.gitignore`, where
  a re-init cannot lose it again.
- Eight third-party calculator captures under `cable-sizing/reference/` — ELEK
  page captures carrying their copyright line, a jcalc capture, Tricab's own JS,
  and a screenshot of the ELEK UI. Logged as **B7** in `PUBLISH-REVIEW.md`.

Both excluded, leaving **433 files, 20.9 MB**. Committed to a fresh `main` and
pushed to `github.com/sinkers/sd-dc`, public.

The index had also drifted badly before this step: only 205 of 442 present files
were tracked, root `README.md` and `PLAN.md` among the missing. The fresh init
fixed that as a side effect, and it is another argument for having done Step 6
rather than `filter-repo`.

---

## Step 7 — Publication furniture  ·  ✅ DONE 2026-09-04

`LICENSE` (MIT, with scope carve-outs for manufacturer data and the standards),
`CONTRIBUTING.md`, `run-tests.sh`, `.github/workflows/test.yml` on 3.9 and 3.12.
The README gained a "Purpose and use" section stating this is private study and
research, not commercial use — framed as intent, with a paragraph making clear it
is not a licence and binds nobody who clones the repo.

<details><summary>Original plan</summary>


None of this exists.

- **`LICENSE`** — the code is ours; note it does not extend to vendor data.
- **Data licensing note** in `README.md` — catalogue *values* are transcribed
  from vendor documentation for interoperability; the documents are not
  redistributed. Already the practice, needs saying.
- **`CONTRIBUTING.md`** — short. The rule worth stating is the provenance
  discipline: new reference data lands `verified: false` with a source string.
- **`.github/workflows/test.yml`** — run `cable-sizing` (302 checks) and
  `digital-twin` (119 tests). Both near-stdlib, so CI is cheap and it proves the
  repo works on a machine that is not yours.

</details>

---

## Step 8 — Documentation gaps  ·  ✅ DONE 2026-09-04

All eight components now have a README. `cooling-model/` had none at all and got
a real one, including why `piping/` superseded it. `cable-tray-ezystrut/` and
`vm-setup/` got READMEs pointing at their existing `INDEX.md` / `INSTALL.md`.
`SPEC.md` now says at the top that it is the original vision, and its file-structure
section is marked aspirational — it listed five directories that never existed.

Also: 40.7 MB of stageable junk down to 12.5 MB by gitignoring generated MP4s and
reports, and `constant/triSurface/` was missing from `data_push.sh` — without it
you cannot re-mesh. Fixed and pushed.

<details><summary>Original plan</summary>


| Gap | Fix |
|---|---|
| `cooling-model/` has **no documentation at all** | Write a README. Smallest real gap, most visible to a stranger |
| `cable-tray-ezystrut/`, `vm-setup/` have no `README.md` | They have `INDEX.md` / `INSTALL.md`. Rename, or add a README pointing at them |
| `digital-twin` tests fail on a clean checkout — `No module named 'dthall'` | Add `pip install -e '.[dev]'` to the README quickstart and CI. The 119 tests pass once installed |
| `SPEC.md` lists `components/`, `engine/`, `specs/`, `output/`, `sddc/` — **none exist** | Mark aspirational or delete. It reads as a description of the repo and is wrong |
| No top-level test runner | `Makefile` or `run-tests.sh` covering both suites |

</details>

---

## Step 9 — Verify  ·  ✅ DONE 2026-09-08

```bash
# Check what WOULD be staged, not just what is tracked. B6 was found this way:
# four vendor screenshots were untracked, so every tracked-file scan missed them.
git ls-files --cached --others --exclude-standard -z | xargs -0 du -ck | tail -1
git ls-files --others --exclude-standard -z | xargs -0 du -k | sort -rn | head -20

git ls-files | grep -E 'drawing_locate/img|drawing_read|datasheets/.*\.pdf'
git ls-files -z | xargs -0 grep -lI '730335486558'
git ls-files -z | xargs -0 grep -lI 'dame.com.au'
git ls-files -z | xargs -0 grep -lInE \
  'AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE|api[_-]?key.*[:=]|password.*[:=]'
git log --all --diff-filter=D --name-only --pretty=format: | \
  grep -iE '\.env|\.pem$|\.key$|credential|id_rsa'
```

Last four should be empty. **They were**, on 2026-09-08. The only secrets-pattern
hit was `vm-setup/INSTALL.md:61,66` — two `<GENERATED-PASSWORD>` placeholders, a
false positive.

Size checks passed too: 20.9 MB across 433 files, against a 40 MB expectation.

**What the scans did not catch, and why.** Every check above is either a
fixed-string search or a scan of paths a previous blocker taught us to look at.
None of them would find third-party material in a directory no earlier blocker
had implicated — which is exactly what B7 turned out to be. Reading the staged
listing in full is not a formality on top of these greps; it is the only step
that found anything this time.

---

## Already done

- Root `.gitignore` extended: `.venv/`, `*.sqlite`, `*.egg-info/`, generated
  `out/` and `status-*.html`, corpus and third-party document paths.
- `cfd-cabinet-cooling/.gitignore` generalised `case/` → `case*/`, which was the
  whole leak. **1,918 untracked files / 2.0 GB → 169 / 41 MB.**

---

## Not blocking publication

- **The test gap.** `QUALITY.md` costs it at ~3.5 days and it gates the `PLAN.md`
  *refactors*, not publication. Steps 1–9 are mechanical: moving directories,
  deleting files and writing docs, none of which changes behaviour. **The §1a
  service refactor is a different matter — do not start it before `piping` has
  tests.**
- **`piping`'s 2 failing scenarios.** Documented honestly in its README and
  report. A repo that says what does not work is more trustworthy than one that
  hides it.
- **Anything else in `PLAN.md`.** That is the next phase.
