# Where to run these simulations

Investigation of remote/GPU execution for the cabinet cooling case, with
measurements taken on the current case rather than estimates.

## Bottom line

**GPU is the wrong lever for this workload.** The measured hard ceiling on any
GPU acceleration is **1.39×**, and that is with a hypothetical infinitely fast
GPU linear solver. GPU instances also give you *fewer* usable CPU cores per
dollar, which is what this solver actually needs.

The right lever is **more CPU cores plus running cases concurrently**. On
`c8g.48xlarge` Spot (192 Arm cores, $1.75/hr) the entire 6-point 3D sweep from
`PLAN-3D.md` costs about **$0.18 and finishes in ~10 minutes**.

Recommendation: skip GPU entirely, use Arm CPU Spot instances, and keep the 2D
case local.

---

## Evidence 1 — where the time actually goes

Runtime profile, 200 iterations, serial, 107,520 cells (OpenFOAM `profiling`):

| Item | Self time | % of run | What it is |
|---|---|---|---|
| `time.run()` untracked | 35.2 s | **70.2 %** | matrix assembly, gradients, divergence, interpolation, thermophysical update, turbulence, boundary conditions |
| `coarsestLevelCorr` | 7.6 s | 15.1 % | GAMG coarsest-level solve for `p_rgh` |
| `Ux`,`Uy`,`Uz`,`h`,`k`,`omega` | 6.1 s | 12.2 % | six segregated PBiCGStab+DILU solves, ~1.0 s each |
| `fvMatrix::solve.U`, misc | 0.5 s | 1.0 % | |
| **Total** | **50.2 s** | | |

Linear algebra is **~28 %** of the run. A PETSc/AmgX GPU offload moves only that
28 %; the other 70 % stays on the CPU by construction.

Amdahl's law with p = 0.28 gives a ceiling of **1/(1−0.28) = 1.39×** — for a
solver that takes zero time. Realistic AmgX speedups on the pressure solve are
2–4× at large scale, which here would yield roughly **1.1×** overall, before
counting host↔device transfer.

## Evidence 2 — the solves are too small to ship to a device

Each segregated solve is **1.02 s / 200 calls ≈ 5 ms**. Per SIMPLE iteration
there are six of them plus the pressure solve. Moving a 5 ms kernel to a GPU
means a host→device copy, a launch, and a device→host copy every time; PCIe
latency and transfer alone would consume most of the win. GPU linear solvers pay
off when a single solve takes hundreds of milliseconds, i.e. meshes of ~10 M+
cells.

## Evidence 3 — nothing is installed, and it is not a flag

`opencfd/openfoam-default:2406` contains **no** `petsc4Foam`, AmgX, CUDA or cuSPARSE
libraries, and no `modules` directory. Enabling GPU offload means building PETSc
with CUDA, building `petsc4Foam` against it, and rebuilding the image — a
multi-day project with a version-matching maintenance burden, to chase ~1.1×.

For completeness: `RapidCFD` (a CUDA fork of OpenFOAM) is pinned to OpenFOAM 2.3,
unmaintained, and does not contain a modern `buoyantSimpleFoam`. It is a dead end.

## Evidence 4 — measured scaling, and a correction

Strong scaling, 107,520 cells, 200 iterations, `scotch` decomposition, on this
laptop (14 cores, Docker Desktop VM):

| ranks | wall s | speedup | efficiency | cells/rank |
|---|---|---|---|---|
| 1 | 50 | 1.00 | 100 % | 107,520 |
| 2 | 26 | 1.92 | 96 % | 53,760 |
| 4 | 14 | 3.57 | 89 % | 26,880 |
| 6 | 9 | 5.56 | 93 % | 17,920 |
| 8 | 8 | 6.25 | 78 % | 13,440 |
| 10 | 13 | 3.85 | 38 % | 10,752 |
| 12 | 17 | 2.94 | 25 % | 8,960 |

Scaling **peaks at 8 ranks and then collapses** — 12 ranks is 1.9× *slower* than
6. Below ~13 k cells/rank, communication dominates, and the macOS Docker VM makes
it worse.

> **This corrects `PLAN-3D.md`,** which recommended `numberOfSubdomains 12`. That
> would have been slower, not faster, on this machine. The rule is
> **ranks ≈ cells / 20,000**, capped by physical cores. For the 1.72 M-cell 3D
> row, ~85 ranks is the right target — which is exactly why a bigger CPU box
> earns its keep and the laptop does not.

Useful derived constant: **2.33 µs per cell per iteration per core**
(0.25 s/iter ÷ 107,520 cells). Everything below is costed from this.

---

## AWS options — real prices, queried today

Specs from `describe-instance-types`, prices from the Pricing API (Linux, shared
tenancy, on-demand) and `describe-spot-price-history`.

| Instance | Physical cores | Arch | RAM | On-demand | Spot (us-east-2) | $/core-hr (spot) |
|---|---|---|---|---|---|---|
| **c8g.48xlarge** | **192** | **arm64** | 384 GB | $7.66 | **$1.75** | **$0.0091** |
| c7g.16xlarge | 64 | arm64 | 128 GB | $2.32 | $0.65 | $0.0102 |
| c7a.48xlarge | 192 | x86_64 | 384 GB | $9.85 | $2.70 | $0.0141 |
| hpc6a.48xlarge | 96 | x86_64 | 384 GB | $2.88 | no Spot | $0.0300 (on-dem) |
| hpc7a.96xlarge | 192 | x86_64 | 768 GB | $7.20 | no Spot | $0.0375 (on-dem) |
| c7i.48xlarge | 96 (192 vCPU) | x86_64 | 384 GB | $8.57 | — | — |

And the GPU instances, for the comparison that settles it:

| Instance | Cores | GPUs | On-demand |
|---|---|---|---|
| g6e.48xlarge | 96 | 8× L40S | **$30.13** |
| p5.48xlarge | 96 | 8× H100 | $55.04 |
| p4d.24xlarge | 48 | 8× A100 | $21.96 |
| **hpc6a.48xlarge** | **96** | none | **$2.88** |

`g6e.48xlarge` and `hpc6a.48xlarge` have the **same 96 cores**. The GPU box costs
**10.5× more** for GPUs that could, at absolute best, deliver 1.39× on 28 % of the
runtime. There is no reading of these numbers where GPU wins.

Note also that small GPU instances are actively harmful: `g5.xlarge` ($1.01/hr)
has **2 cores**. You would be trading 96 cores for 2 cores plus an accelerator
this solver cannot use.

### Two notes on instance choice

- **Arm is both cheapest and most convenient.** `c8g`/`c7g` are arm64, the same
  architecture as this laptop, so the existing `opencfd/openfoam-default:2406`
  image runs natively with no rebuild — `run.sh` already auto-detects platform.
  It also keeps results bit-comparable with local runs; x86 and Arm differ in
  FMA and vectorisation, so cross-arch runs can disagree in the last digits and
  muddy the Phase-1/2 equivalence checks in `PLAN-3D.md`.
- **`hpc6a` is only worth it for multi-node.** Its advantages are 100 Gb EFA and
  cluster placement, which matter beyond one node. For a single 192-core box,
  `c8g` Spot is cheaper per core and Arm-native. HPC instances also do not offer
  Spot, so on-demand `hpc6a` is 3.3× the cost of `c8g` Spot per core.

---

## Cost model

From the measured 2.33 µs per cell-iteration-core, one 3D run
(1,720,320 cells × 3,000 iterations) is **3.33 core-hours**.

| Job | Core-hours | c8g Spot cost | Wall time on 192 cores |
|---|---|---|---|
| One 3D row run | 3.3 | **$0.03** | ~2–4 min |
| 6-point 3D sweep | 20.0 | **$0.18** | ~10 min |
| Fan-failure scenario set (4 cases) | 13.3 | $0.12 | ~7 min |
| Whole `PLAN-3D.md` programme, ~30 runs | 100 | **$0.91** | ~1 hour |

Even tripling these for scaling inefficiency and instance start-up, the entire 3D
programme is **under $3**. Storage is negligible: a 200 GB gp3 volume is
$0.016/GB-month, i.e. cents for the hours it exists.

**Concurrency vs rank count.** Both give the same core-hours, so pick by need:
run one case across ~85 ranks when you want a single answer fast; run six cases
at 16–32 ranks each when you want a whole sweep, since low rank counts have
almost no communication overhead. For sweeps, concurrency is slightly more
efficient and much simpler — no MPI tuning.

---

## Recommendation

**Tier 1 — stay local for 2D.** The 0.6 m slab case is 2.5 minutes on 6 ranks.
Nothing to gain from remote execution; keep it as the fast regression test.
Set `numberOfSubdomains 6` (not 12).

**Tier 2 — one Spot instance for 3D.** `c8g.48xlarge` Spot in us-east-2, 192 Arm
cores, ~$1.75/hr. Lifecycle: launch → `rsync` the case → run → `rsync` results
back → terminate. Minutes of runtime means Spot interruption risk is
inconsequential, and OpenFOAM's time directories make any run restartable anyway.

Deliberately **not** recommending AWS Batch, ParallelCluster or EKS. At 30 runs
totalling an hour of compute, orchestration would cost more effort than the
compute it manages. Revisit if this becomes a routine design-loop tool.

**Tier 3 — use the Spheron B300 as a CPU box.** See below.

---

## Spheron B300 — probed, and it is not a compute upgrade

`ssh ubuntu@89.124.37.173` with `~/.ssh/gpu-power-lab`. Measured:

| | |
|---|---|
| CPU | Intel Xeon 6776P, **12 physical cores** (24 threads), 1 socket, 1 NUMA node |
| RAM | **340 GB** |
| Disk | 248 GB, 203 GB free |
| GPU | 1x B300 SXM6, 275 GB |
| OS | Ubuntu 22.04.5, x86_64 |
| Containers | none — no Docker, no Apptainer (passwordless sudo available) |

**It has 12 physical cores against this laptop's 14.** For a solver that wants
`cells / 20,000` ranks, that is not an upgrade — it is a sidestep. The B300 sits
idle, as established above.

It is still worth having, for three reasons that are not core count:

- **340 GB of RAM** removes the binding constraint. Docker Desktop here caps at
  12.6 GB, which limits meshing to roughly 3–4 M cells; the Spheron box could
  mesh and run a 20 M-cell case, just slowly. If a big 3D mesh is wanted, build
  it there.
- **Native Linux MPI, no hypervisor.** The laptop's scaling collapse past 8 ranks
  is partly the Docker Desktop VM. Expect all 12 ranks to scale properly here.
- **It is already paid for**, and it is a persistent box, unlike a Spot instance.

It is x86_64, so results will differ from local Arm runs in the last digits.
Keep the Phase 1/2 equivalence checks on one architecture.

### Provisioned and scripted

OpenFOAM v2406 is installed (`/usr/lib/openfoam/openfoam2406`). Because this is
a **Spot instance that will be recycled**, the install is scripted rather than
manual:

```bash
./remote/provision-openfoam.sh ubuntu@89.124.37.173 ~/.ssh/gpu-power-lab
./remote/run-remote.sh        ubuntu@89.124.37.173 ~/.ssh/gpu-power-lab
```

`provision-openfoam.sh` is idempotent — it exits in seconds if OpenFOAM is
already there, waits out any `unattended-upgrades` dpkg lock, and runs detached
under `setsid nohup` so a dropped SSH connection cannot abort a half-finished apt
transaction. That last point is not hypothetical: the first attempt died exactly
that way, leaving a partially unpacked dpkg state.

`run-remote.sh` rsyncs the case up, sets `numberOfSubdomains` from the box's
**physical** core count, runs `Allrun`, and brings `postProcessing/`, the logs
and the latest time directory back, so every local plotting script works
unchanged on the result.

## When GPU *would* become the right answer

Worth revisiting if any of these change:

- **Mesh grows past ~10 M cells.** Individual solves get big enough to amortise
  transfer, and the linear-solve fraction rises with mesh size.
- **The case goes transient.** `buoyantPimpleFoam` for the fan-failure question
  solves pressure many times per timestep across thousands of timesteps, pushing
  the linear-algebra fraction well above 28 % and total cost into the hours. That
  is the first point where a GPU build could pay for itself.
- **A different solver entirely.** GPU-native CFD (lattice-Boltzmann codes, or
  commercial multi-GPU solvers like Fluent's) is genuinely fast, but it means
  leaving OpenFOAM and revalidating everything.
- **ML surrogate.** If this becomes an inner loop of the SD-DC layout optimiser,
  training a surrogate on a few hundred CFD runs is a GPU workload — but the
  training data still comes from CPU runs.

## Immediate next step

If you want this built, the smallest useful piece is a `run-remote.sh` that
mirrors `run.sh`: takes a host (or launches a Spot instance), rsyncs `case/`,
runs `Allrun` in the container, rsyncs `postProcessing/` and the latest time
directory back, and tears down. Everything downstream — `plot_metrics.py`,
`plot_slice.py`, `sweep.sh` — then works unchanged on the returned data.
