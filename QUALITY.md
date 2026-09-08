# Code quality and test coverage assessment

Measured 2026-09-04, not estimated. Coverage from `coverage.py` on real runs;
structural figures from AST analysis of every tracked `.py` file.

**Verdict: two components are genuinely well tested, six have no tests at all.**
The untested six are 6,447 LOC — 37% of the code that stays after `dc-model`
splits out. Three of them are on the critical path for the work in `PLAN.md`.

---

## 1. Where things stand

| Component | src LOC | test LOC | tests | Coverage | Refactor-ready? |
|---|---:|---:|---:|---:|---|
| `cable-sizing` | 5,434 | 1,116 | 302 checks | **71%** (core 91–100%) | **Yes** |
| `digital-twin` | 4,783 | 1,517 | 119 tests | **70%** (core 98–100%) | **Yes** |
| `piping` | 1,676 | 0 | — | 0% | **No — highest risk** |
| `cable-tray-ezystrut` | 2,433 | 0 | — | 0% | No |
| `cfd-cabinet-cooling` | 1,035 | 0 | — | 0% | No |
| `cables` | 706 | 0 | — | 0% | Low risk (mostly data) |
| `cooling-model` | 313 | 0 | — | 0% | Low risk (small) |
| `vm-setup` | 284 | 0 | — | 0% | Low risk (shell-ish) |
| *`dc-model`* | *6,567* | *0* | — | *0%* | *leaving — see §5* |

Tested: 10,217 LOC at ~70%. Untested: 6,447 LOC.

### Coverage detail, the two that have it

**`cable-sizing`** — 71% combined across both suites. The split matters:

```
standards.py     100%     iec60228.py      100%     openapi.py       100%
install_diagrams  99%     cable_sizing.py   94%     ezystrut.py       94%
service.py        92%     as3008.py         91%     mcp_server.py     69%
server.py          0%  ← the HTTP layer is untested
build_*.py         0%  ← build scripts, acceptable
```

The calculation core and the service layer are well covered. **`server.py` at 0%
is the real gap** — and `PLAN.md` §1a makes HTTP the interface every other
component depends on, so it is about to become load-bearing.

**`digital-twin`** — 70%, and the physics is the well-covered part:

```
rackfan 100%   gap 99%   model 99%   sim 99%   topology 99%   profiles 98%
telemetry 93%  server 84%
cli.py 0%   debugview.py 0%   replay.py 0%   viewer.py 0%   ← tooling/presentation
```

That is a healthy shape: the parts where a bug is silent are covered, the parts
where a bug is obvious are not.

**One caveat on `digital-twin`:** `pytest rom/tests` fails with 10 collection
errors on a clean checkout — `ModuleNotFoundError: No module named 'dthall'`. The
tests are fine (119 pass with `PYTHONPATH=rom`), the package just is not
installed. That is onboarding friction, not test rot, but a contributor will read
it as a broken repo. Fix with `pip install -e '.[dev]'` in the README quickstart
and in CI.

---

## 2. Structural signals

Counts across all tracked Python, by AST.

| Component | files | funcs | >50 ln | >100 ln | complex | no docstring | import-time I/O | print() |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `cable-sizing` | 17 | 168 | 14 | 4 | 1 | 42% | **6** | 53 |
| `digital-twin` | 33 | 291 | 13 | 5 | 1 | 68% | 0 | 61 |
| `piping` | 3 | 49 | **12** | 1 | 2 | 12% | 0 | 0 |
| `cable-tray-ezystrut` | 4 | 49 | 7 | 0 | 0 | 8% | 0 | 95 |
| `cfd-cabinet-cooling` | 5 | 16 | 4 | 2 | 0 | 75% | 0 | 39 |
| `cooling-model` | 1 | 5 | 1 | 1 | 0 | 0% | 0 | 6 |
| `cables` | 1 | 14 | 4 | 2 | 0 | 7% | 0 | 43 |
| `vm-setup` | 2 | 21 | 0 | 0 | 0 | 24% | 0 | 9 |
| *`dc-model`* | *29* | *146* | *33* | *16* | *15* | *73%* | *0* | *312* |

"complex" = more than 15 branch points in one function.

### What stands out

**Import-time I/O in `cable-sizing` — 6 occurrences, and it is self-inflicted.**
`as3008.py:33` does `TABLES = _load_tables()` at module scope, so importing the
module reads JSON off disk. Consequences: a test cannot substitute reference data
without monkeypatching, the import fails outright if the file is missing, and the
module cannot be used against two table sets in one process. This arrived with
the move of reference data into `reference_tables.json` — the provenance win was
real, the coupling was not intended. Fix is a lazy accessor with an injectable
path.

**`piping` has the worst function-length profile of the code that matters** —
12 of 49 functions over 50 lines, in geometry code where an off-by-one in an
elbow tangent is silent. Zero tests. See §3.

**Docstring coverage is bimodal.** `piping` 12%, `cable-tray-ezystrut` 8%,
`cables` 7% are good. `cfd-cabinet-cooling` 75% and `digital-twin` 68% missing is
poor — though much of `digital-twin`'s is small private helpers.

**618 `print()` calls in library code.** Fine in scripts, wrong in anything
`PLAN.md` §1a turns into a service — a library that prints cannot be composed.
`piping` at 0 shows it is achievable.

**Hardcoded absolute paths in 5 tracked files.** Three of them unconditional, so
they break the moment the repo moves — which `TIDY-UP.md` Step 1 is about to do.
`cables/model_cable_system.py:52` shows the correct pattern (derive from
`__file__`, fall back only for FreeCAD's exec context, which has no `__file__`).
Worth fixing everywhere, because a test that depends on the repo living at one
absolute path is a test that only runs on one machine.

---

## 3. `piping` is the one to worry about

It is the highest-risk refactor in the repo, and `PLAN.md` puts it directly on
the critical path — the layout engine's auto-connect calls it for every pipe run.

- 1,676 LOC, zero tests
- 12 functions over 50 lines, 2 over the complexity threshold
- Geometric code: errors are subtle, not loud. A pipe that "looks right" but has
  a 0.4 mm gap between segments fails silently until STEP export
- **2 of its 5 documented scenarios already fail**
- Wrapping it as a service (§1a) means changing its interface

Refactoring this without tests first is the one thing in the plan I would refuse
to do. The good news: it is unusually easy to characterise, because it already
has assertable invariants stated in its own README:

- consecutive parts must chain: `part[i].exit_pos == part[i+1].entry_pos`
- interior segments must exceed `2 × bend_radius`; end segments `1 × BR`
- routes must be orthogonal
- elbow geometry: `centre = entry + turn_dir × BR`, `exit = centre + entry_dir × BR`

Those are property tests, not example tests. Generate random nozzle pairs and
obstacle sets, assert the invariants hold or the router refuses. That is a day's
work and it converts the riskiest component into a safe one.

---

## 4. Test strategy before refactoring

Ordered by risk × how soon `PLAN.md` touches it.

| Priority | Component | What to write | Effort |
|---|---|---|---|
| 1 | `piping` | Property tests on the four invariants above; pin the 3 passing scenarios as regressions; assert the 2 failures fail *for the documented reason* | 1 day |
| 2 | `cable-sizing/server.py` | HTTP-level tests for every route, incl. 4xx paths. It becomes the interface everything else uses | ½ day |
| 3 | `cable-tray-ezystrut` | Golden tests on `tray_catalogue.json` selection + fill; joint rules on known-good/known-bad cases | 1 day |
| 4 | `cables` | Schema validation on the catalogue; a loader test. Mostly data, so validate the data | 2 h |
| 5 | `cfd-cabinet-cooling` | Not unit tests — a fast smoke case that meshes and runs 10 iterations in CI, asserting it converges monotonically | ½ day |
| 6 | `cooling-model` | Geometry builds, STEP exports, bounding box is sane | 2 h |

**Do not chase a coverage number.** The two components that have tests got there
by testing what is hard to see — adiabatic constants, energy balance, gap
closure. Repeat that, rather than covering getters.

**Characterisation before refactor, not after.** For `piping` especially: write
tests that pin current behaviour *including the bugs*, refactor, confirm
unchanged, then fix the bugs as a separate visible change.

### Two structural fixes that make testing easier

1. **Remove the import-time I/O** in `as3008.py`. Lazy-load with an injectable
   path; the existing 302 checks will catch a mistake.
2. **Get `dthall` installable in CI** so `pytest` works on a clean checkout.

Both are small and both unblock everything else.

---

## 5. `dc-model` — measured, for the record

Leaving to its own private repo, but the numbers explain why that is also a
quality decision. 6,567 LOC, **zero tests**, 33 functions over 50 lines, 16 over
100, 15 above the complexity threshold, 73% undocumented, 312 `print()` calls.

It is the largest and least tested body of code here. Its own `RESUME.md` is
honest about the eval noise floor and which numbers are not quotable, which is a
better discipline than most of the code shows — but the acquisition and
extraction pipeline has no automated verification at all.

If `collector/` is extracted as a shared library per `PLAN.md` §3.0, **it needs
tests as part of the extraction**, not afterwards. It will have two consumers,
and it does network I/O, politeness and rate limiting — all things that fail
quietly and matter.

---

## 6. Honest summary

**Good.** The two components carrying the real engineering — cable sizing and the
twin — are well tested where it counts, and their test suites are unusually
thoughtful: validated against published worked examples, with per-field
provenance checks and structural validation of reference data. That is above
typical standard.

**Weak.** Six components with no tests, one of them (`piping`) both risky and on
the critical path. The HTTP layer that `PLAN.md` makes central is untested.
618 `print()` calls in code destined to become services.

**The gap that matters.** Everything in `PLAN.md` assumes these components can be
composed, wrapped as services and called by a layout engine. Composition
multiplies the cost of silent errors. Right now, three of the components that
composition depends on — `piping`, `cable-tray-ezystrut`, `cables` — have no way
to tell you when they break.

Roughly **3.5 days** of test writing closes the gap to the point where the
`PLAN.md` refactors are safe. That is cheap against the cost of finding a
geometry bug after it is wired into a layout engine, a twin and an IFC export.
