# Publishing the AU01 twin to AWS

## Context

The twin currently runs on a laptop: a Python WebSocket service on `:8765` and a
`SimpleHTTPRequestHandler` on `:8080`, one shared stateful hall, bound to
`127.0.0.1`. The goal is a URL someone can open and drive.

Decisions taken: **fully public, no auth**; **per-session twin** (each visitor
gets their own hall); **a single t4g.small with Caddy** (chosen over
CloudFront/S3 + Fargate/ALB, which cost ~3x more for this workload — the ALB
alone was more than the compute).

**STATUS: DEPLOYED.** Live at <https://au01-twin.dametech.net/>. What follows is
the record of what was built and why, not a forward plan. Sections marked
*(not built)* describe the rejected alternative, kept for the reasoning.

Per-session isolation is what makes an unauthenticated URL tolerable: no visitor
can disturb another's session. Toolchain follows the CFD stream's conventions —
ARM64, bash + `aws` CLI with env-var overrides — but in `ap-southeast-2` rather
than `us-east-2`, since that is the account default and the right region for an
Australian hall.

### One thing to decide with open eyes

Publishing this publishes the AU01 design: the rack schedule with per-rack loads,
the hall geometry, the fan wall selection, and the thermal performance including
where it fails. That is a commercial disclosure decision, not just a security one.
Nothing here depends on it staying public: adding a password is one `basic_auth`
block in the Caddyfile plus a re-run of `provision.sh`. But it should be a
deliberate call rather than a side effect of "no auth is simpler".

## 1. Architecture as built

```
   browser  ──https──>  ┌──────────────────────────────────────────┐
                        │  t4g.small, ap-southeast-2, Ubuntu 24.04 │
   au01-twin            │  arm64, 2 vCPU / 2 GB, elastic IP        │
   .dametech.net        │                                          │
                        │  Caddy :80/:443                          │
                        │   ├─ Let's Encrypt cert, auto-renewed    │
                        │   ├─ HTTP -> HTTPS redirect              │
                        │   └─ reverse_proxy 127.0.0.1:8765        │
                        │        (WebSocket upgrades pass through)  │
                        │                                          │
                        │  dthall.service (systemd, user dthall)   │
                        │   ├─ 127.0.0.1:8765 only                 │
                        │   ├─ GET /        static viewer assets   │
                        │   ├─ GET /healthz status JSON            │
                        │   └─ GET /ws      one twin per connection│
                        └──────────────────────────────────────────┘
```

Everything on one host, one port internally, one domain externally. The solver
never listens on a public interface — Caddy is its only route in.

**No Docker.** The service is pure Python (numpy + websockets), so a venv plus a
systemd unit is less machinery than a container daemon and leaves ~200 MB more RAM
on a 2 GB box. A deploy is an rsync and a restart; there is nothing to build.

**CloudFront/S3 + Fargate/ALB *(not built)*.** The original design put static
assets on CloudFront and the solver in a 0.25 vCPU Fargate task behind an ALB.
It works and is more managed, but at ~$26–32/month against ~$13 it was paying
mostly for an ALB that this workload does not need: one stateful long-lived
process with a few dozen WebSocket clients. Worth revisiting only if the twin
needs multiple tasks or the edge cache for a global audience.

## 2. Why not API Gateway WebSocket + Lambda

Worth stating because it is the reflexive AWS answer and it is the wrong tool
here. Lambda is stateless per invocation; this twin is a *continuously
integrating* simulation — it advances 58 coupled ODE states against a wall clock
and pushes at 10 Hz unprompted. On Lambda you would rehydrate and persist state on
every message, and you would need a separate scheduled invoker to produce frames
nobody asked for. A long-lived container is the natural shape for this workload.

## 3. Code changes this required — all done

Prerequisites, not polish. Each was a genuine blocker; several were only found by
deploying.

### 3.1 Single port, `/ws` path

Today: static on 8080, WebSocket on 8765, viewer hardcodes
`ws://${location.hostname}:8765`. Over HTTPS that is blocked as mixed content, and
it needs two ALB targets.

Change `rom/dthall/server.py` to serve both from one port using the
`websockets.serve(process_request=...)` hook: return an HTTP response for normal
requests, fall through to the WebSocket upgrade for `/ws`. Then:

- viewer default becomes `(location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws'`
- local dev and production become the same shape; the `?ws=` override stays for debugging
- `rom/dthall/viewer.py`'s threaded HTTP server is demoted to a dev convenience
  and is explicitly **not** the public server

Two things bit here. `connection.respond()` takes *text* and fixes
Content-Length from it, so assigning `.body` afterwards serves a 200 with an empty
file — every asset silently zero bytes. The `Response` must be constructed
directly. And `VIEWER_ROOT` was derived relative to the source file, which is
correct in a source tree and wrong for an installed package sitting in
site-packages; it now reads `DTHALL_VIEWER_ROOT` and warns loudly at boot if the
assets are not where it was told.

### 3.2 `/healthz`

`GET /healthz` returns 200 with the session count, sessions served, schema
version and uptime. Falls out of §3.1 for free, and is what `deploy.sh` polls to
decide whether a deploy worked.

### 3.3 Per-session twins

Today `TwinServer` holds one `SimEngine` and broadcasts it. Change to a registry
keyed by connection:

- `SimEngine` per connection, created on connect, destroyed on close
- one physics task and one publish task per session (or a single task iterating
  the registry — simpler to reason about and avoids a task per socket)
- **prewarmed state:** settling a new hall costs **357 ms** of CPU. Settle *once*
  at boot and deep-copy that state into each new session, so connect is ~free and
  a burst of visitors cannot stampede the CPU.
- idle reaper: close sessions with no client after N seconds (belt and braces —
  the socket closing should already remove them)
- `MAX_SESSIONS` cap, returning a polite "at capacity" frame rather than
  degrading everyone

Measured cost per session: **8 KB** of memory, and CPU per §6.

The token bucket for rate limiting must start **full**. Starting it empty meant
the first command of every session was silently dropped — a session could trip a
fan wall and nothing happened, which looks exactly like broken controls.

### 3.4 Vendor the geometry contract

`topology.from_cfd_export()` reads
`../cfd-cabinet-cooling/geometry/CFD_Export_RevE/cfd_export_params.json` — 2.4 KB
outside `digital-twin/`, so the image cannot build from this directory alone. Copy
it to `rom/dthall/au01_export_params.json`, add it to `package-data`, and have
`DEFAULT_CFD_EXPORT` prefer the packaged copy and fall back to the sibling path for
local work. `cfddata.py`'s reads of `case-hall/` and `RESULTS.md` are only used by
`calibrate`/`validate` and are **not** needed at runtime.

### 3.5 Public-endpoint guards

An unauthenticated compute endpoint needs limits. None of these exist today:

| Guard | Why | Suggested |
|---|---|---|
| cap `set_speed` | 200× costs ~2% of a core per session | 60 in public mode |
| command rate limit | a loop of `set_unit` commands is free to send | ~20/s per connection, then ignore |
| max sessions | bounds total CPU and memory | 40, tunable by env |
| max connection lifetime | stops a forgotten tab holding a slot for days | 4 h, then close with a reason |
| frame rate | egress is the main cost driver (§6) | keep 10 Hz, make it env-tunable |

Also review the one place wire input reaches a constructor:
`telemetry.apply_command`'s `auto_config` does `ProfileConfig(**a["config"])`. Bad
keys raise `TypeError` and are caught, so it is not exploitable, but it should
validate against a field allow-list rather than splatting attacker-controlled keys.

### 3.6 Config from environment

`DTHALL_MAX_SESSIONS`, `DTHALL_MAX_SPEED`, `DTHALL_MAX_CMD_RATE`,
`DTHALL_MAX_SESSION_S`, `DTHALL_PUBLISH_HZ`, `DTHALL_MODE`, `DTHALL_SEED`,
`DTHALL_VIEWER_ROOT`. The systemd unit sets them.

Subtlety worth knowing: argparse defaults were shadowing every one of these. The
CLI passed `mode=args.mode` etc. unconditionally, so a unit setting `DTHALL_MODE`
was silently ignored. `dthall run`'s options now default to `None` and only
override when actually given.

### 3.7 Leaving the auth door open

Adding a shared password later is a `basic_auth` block in the Caddyfile and a
re-run of `provision.sh` — no application change. Cheap insurance given §Context.

## 4. Packaging *(no container built)*

The runtime needs **`numpy` and `websockets` only** — verified by importing the
whole service path with `scipy` and `matplotlib` forcibly unimportable. `scipy` is
used by `calibrate.py` and `fields/bake_slices.py`; `matplotlib` only by
`debugview.py` and the plotting tools. `pyproject.toml` now keeps those in a
`[dev]` extra, so the deployed venv is small and the dependency surface with it.

That is also why there is no Dockerfile: `pip install .` into a venv on the host
installs two wheels. A container would add a daemon and an image registry to
manage in exchange for nothing this deployment needs. If it ever moves to
Fargate, build ARM64 (`--platform linux/arm64`) and set `cpuArchitecture: ARM64`
in the task definition — a mismatch fails at task start with an unhelpful message.

## 5. AWS resources as built

| Resource | Detail |
|---|---|
| EC2 instance | `t4g.small`, Ubuntu 24.04 arm64, 12 GB gp3, IMDSv2 required |
| Elastic IP | static, so the DNS record survives stop/start — Let's Encrypt rate-limits issuance per name, so a changing address is expensive |
| Security group | 80 and 443 from anywhere (required: public by decision, and ACME must reach port 80), 22 from `SSH_CIDR` |
| Route53 | `au01-twin.dametech.net` A record, TTL 60 |
| Caddy | TLS termination, automatic Let's Encrypt, HTTP→HTTPS redirect, WebSocket-transparent reverse proxy |
| systemd | `dthall.service`, user `dthall`, `ProtectSystem=strict`, loopback bind only |

Nothing else. No load balancer, no bucket, no registry, no certificate manager.

### Gotchas that actually cost time here

1. **`systemctl enable --now` does not restart a running unit.** apt starts Caddy
   with its default Caddyfile the moment it installs, so writing a new Caddyfile
   and then calling `enable --now` left the default config serving port 80 with no
   HTTPS. The provisioner now `caddy validate`s and then `reload-or-restart`s.
2. **Backticks inside an unquoted heredoc are command substitution.** The
   Caddyfile heredoc is unquoted so `$DOMAIN` expands, which meant a comment
   containing `` `journalctl -u caddy` `` executed it and injected the output into
   the config. There is now a warning in the file next to the heredoc.
3. **Caddy cannot write `/var/log/caddy/access.log`** under the packaged unit
   (`ProtectSystem=full`, user `caddy`) however the directory is owned. The file
   sink was removed; access logs go to the journal, which rotates anyway.
4. **Let's Encrypt needs the DNS record live first.** `up.sh` waits for the name
   to resolve to the new address before provisioning, because Caddy's first
   issuance attempt otherwise fails and backs off.

## 6. Capacity and cost, from measured numbers

Measured on this hall (24 racks), per session:

| Quantity | Measured |
|---|---|
| one physics step (0.5 s sim) | 0.158 ms |
| `encode_state` + `json.dumps` | 0.117 ms |
| frame size | 5,162 bytes |
| memory | 8 KB |
| settle a new session | 357 ms (eliminated by prewarming, §3.3) |

CPU per session, including publishing at 10 Hz:

| Sim speed | CPU | Sessions per vCPU |
|---|---|---|
| 1× | 1.5 ms/s (0.15%) | ~670 |
| 12× (default) | 5.0 ms/s (0.50%) | ~200 |
| 60× (capped max) | 20.1 ms/s (2.0%) | ~49 |

So **0.25 vCPU comfortably holds the 40-session cap** at default speed, and even
all-sessions-at-max-speed stays inside it. Compute is not the constraint.

**Egress is.** 5,162 bytes × 10 Hz = **51.6 KB/s ≈ 186 MB per viewer-hour**. At
CloudFront's ~$0.085/GB that is ~$0.016 per viewer-hour — trivial for a demo
(10 viewers × 1 h ≈ $0.17), but it is the term that grows. If it ever matters:
drop to 5 Hz, or send only changed rack entries.

Standing monthly cost as built, ap-southeast-2, approximate:

| Item | ~$/month |
|---|---|
| t4g.small on demand (~$0.0168/h) | 12 |
| 12 GB gp3 | 1 |
| Elastic IP (free while associated) | 0 |
| Route53 hosted zone (already exists) | 0 |
| Data transfer out at demo traffic | 0–2 |
| **Total** | **~13–15** |

Roughly half the Fargate/ALB design, and the whole difference was the load
balancer. The trade is that this is a server you own and patch; `provision.sh` is
idempotent so re-running it is the upgrade path.

A `t4g.small` is burstable (2 vCPU, CPU credits). At the measured per-session cost
the twin uses a small fraction of baseline, so credits are not a constraint — but
if `max_sessions` is ever raised a long way, check CloudWatch `CPUCreditBalance`
before trusting it.

## 7. Deployment mechanics as built

Matching the CFD stream's style (bash + `aws` CLI, env-var overrides), in
`ap-southeast-2` because that is the account default and the right region for an
Australian hall:

```
digital-twin/deploy/
├── up.sh           create/adopt SG, instance, elastic IP, DNS; provision; deploy
├── provision.sh    runs on the host: packages, Caddy, venv, systemd unit
├── deploy.sh       rsync the tree, pip install, restart, verify health
└── down.sh         terminate, release the IP, delete the DNS record and SG
```

All idempotent. `up.sh` adopts existing resources rather than duplicating them, so
re-running is how you repair a host. `deploy.sh` is the day-to-day command.

Overrides: `REGION`, `TYPE`, `NAME`, `DOMAIN`, `KEYNAME`, `KEYFILE`, `SSH_CIDR`.

**CI (optional, later):** a GitHub Actions job running `pytest` plus
`dthall validate` on every push, and `deploy.sh` on tags. The validation gate is
already a pass/fail exit code, so it works as a deployment gate unchanged.

## 8. Verification performed against the live URL

```
https://au01-twin.dametech.net/healthz
  {"status":"ok","hall":"AU01","schema_v":1,"sessions":0,"max_sessions":40,...}

TLS            Let's Encrypt, CN=au01-twin.dametech.net, valid to 18 Nov 2026
               openssl verify result 0
http -> https  308 redirect
assets         /            7,364 B   text/html
               /app.js     38,954 B   text/javascript
               /geometry/manifest.json   51,050 B  application/json  (no-store)
               /geometry/geometry.bin   169,344 B  application/octet-stream
               /vendor/three.module.js 1,304,820 B text/javascript
path traversal /../pyproject.toml -> 404
wss            upgrade in 0.19 s from Australia
publish rate   10.2 Hz measured over 5 s (after draining the backlog)
isolation      session A: W1 off, speed 40, hot aisle 36.5 C, MARGINAL
               session B: untouched, speed 1, hot aisle 30.3 C, PASS
sessions       returned to 0 after both clients closed
```

Local, before each deploy:

```bash
PYTHONPATH=rom python3 -m pytest rom/tests -q     # 119 tests
PYTHONPATH=rom python3 -m dthall.cli validate      # CFD gate, exit 0
```

Six new tests cover the deployment surface: session isolation, capacity refusal,
`/healthz`, static assets serving a real body, path traversal, speed clamping and
command bursts.

**Not verified from here:** that the 3D scene renders. The headless QA browser has
no GPU, so it hits the WebGL guard — which at least proves the page loads and
`app.js` executes. Rendering was confirmed locally on a GPU-capable browser and
needs a human eye on the public URL.

## 9. Phases — complete

| Phase | State |
|---|---|
| 1. Code changes + tests | done — 119 tests, gate passing |
| 2. Lean runtime deps | done — numpy + websockets, proven by import-blocking |
| 3. Instance, Caddy, TLS | done — cert issued, redirect working |
| 4. Public URL renders and drives | done — assets, wss, isolation verified |
| 5. Guards + teardown | done — caps live in the unit, `down.sh` removes everything |

Remaining, optional: CloudWatch alarm on instance health, and a cron'd
`apt-get upgrade`. Neither blocks use.

## 10. Explicitly out of scope

- Autoscaling. One task holds far more sessions than this will see.
- Multi-region. It is a demo.
- Persisting sessions across restarts. A deploy drops connections; the viewer
  already auto-reconnects and will get a fresh settled hall.
- Recording or replaying visitor sessions.
- Serving the Unreal client. When that exists it consumes the same `/ws` endpoint
  and needs no server change — which is the point of the shared protocol.
