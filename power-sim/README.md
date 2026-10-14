# Power sim: composable electrical simulations

Drop-in electrical components (grid, BESS, UPS, GPU servers, a demand-response
controller) that wire together into simulations of a site's point of
connection. Each component is an IndustroML asset kind, so a simulation is an
IndustroML model with parameters attached, and the viewer draws it from that
model.

**Status: simulation 01 of 2 built.** Grid, BESS and UPS with price-driven
demand response, grid disturbance ride-through and a standby generator, 146
tests. Simulation 02 (bidirectional UPS replacing the BESS) is next.

```bash
./serve.sh                       # viewer and API on http://127.0.0.1:8780/
cd model && python3 -m pytest -q tests

python3 -m dtpower scenarios bess-dr
python3 -m dtpower run bess-dr --scenario nsw-spike --set BESS-1.capacity_kwh=800
python3 -m dtpower model bess-dr # the IndustroML model, as JSON
```

The standard library only: no numpy, no websockets, nothing to install.

**Live: <https://au01-twin.dametech.net/power/>**, public with no login, like
the air twin and the loop viewer beside it. `./deploy/deploy.sh` runs the tests,
then rsyncs the model and viewer to `/opt/dtpower` on the twin box. It runs
them as `dtpower.service` on `127.0.0.1:8780`, capped at half a core and 256
MB so it cannot crowd out the air twin, and adds the Caddy route
`sites.d/30-power.caddy`. The route is validated before Caddy reloads.

## Simulation 01: grid, BESS and UPS

```
UTIL ── MSB ──┬── BESS-1        DR-1 sets its power over a data link
              └── UPS-1 ── GPU-1
```

A GPU fleet behind a UPS, and a BESS beside the UPS on the same switchboard.
The controller charges the BESS when power is cheap and discharges it when power
is dear. The GPUs can also be power capped, either all the time or only while
the price is high. The viewer shows the day on a single-line diagram with
animated power flow, a card of dials and settings per asset, and trends for
price, power, state of charge and saving. Every slider re-runs the day (about
30 ms).

**What "$ saved" means.** The day is run three times: no BESS and no
price-triggered cap (the baseline), BESS only, and everything. The saving is

    baseline bill − bill − BESS wear ± change in stored energy

and it splits exactly into what the BESS earned and what the cap earned. The
stored-energy term values the difference between the battery's SoC at midnight
and at the start, at the day's median price. Without it, a strategy can look
good simply by ending the day emptier than it started.

### Scenarios

| Scenario | Price | Saving (defaults) |
|---|---|---|
| NSW1, 12 Oct 2026: $13,017 afternoon spike | AEMO, recorded | $1,724 |
| Same day with a 70 % GPU cap above $300 | AEMO, recorded | $1,763 (cap $39, costs 3.1 server-hours) |
| NSW1, 9 Oct 2026: morning and evening peaks | AEMO, recorded | $30 |
| NSW1, 10 Oct 2026: one $4,091 spike, perfect foresight | AEMO, recorded | $310 |
| SA1, 8 Oct 2026: negative prices all afternoon | AEMO, recorded | $15; the BESS is paid to charge, at −$84/MWh on average |
| Time-of-use tariff, evening peak | synthetic | $78 |
| Grid outage, 25 minutes at 18:00 | synthetic | UPS rides 17 min, then 18.5 kWh unserved |
| Flat $100/MWh | synthetic | negative: the control case |

### Grid disturbances

Seven scenarios run a 45-minute window at two-second steps around an event at
14:00. A sag is modelled as an event with a depth and a duration, not as a
sample, so a 150 ms dip inside a two-second step still counts as 150 ms.

| Scenario | What it shows |
|---|---|
| Sag to 70 % for 150 ms, UPS without ride-through | UPS on battery for 190 s, through a 3-minute resync, down to 83 %. Recharge at 20 % takes the UPS input to 194 kW, a new site peak |
| Same sag, UPS with ride-through | Inside the envelope (500 ms, down to 50 %), so nothing happens |
| Same sag, UPS max demand 160 kW | Recharge only gets the ~15 kW headroom above the load; UPS input never exceeds 160 kW |
| Same sag, BESS covers the recharge | BESS peak-shaves to 160 kW; the UPS recharges at full rate and the grid never sees it |
| Same sag, BESS without fault ride-through | BESS trips, waits 60 s, ramps back; the site goes over 160 kW until it catches up |
| Storm: four sags in seven minutes | Each sag restarts the resync, so ten minutes on battery and down to 47 % |
| Two-second interruption | No ride-through setting covers it; UPS to battery and BESS trips regardless |

The settings that compensate:

- **UPS:** ride-through on or off, plus input window, ride-through time and
  floor; resync time; walk-in time; recharge rate; max demand.
- **BESS:** fault ride-through (LVRT) on or off, with its envelope;
  reconnect delay; reconnect ramp.
- **DR controller:** hold the site to a max demand by discharging, whatever
  the price.

The BESS defaults (60 s reconnect, 16.67 % per minute ramp) are AS/NZS 4777.2
figures as commonly quoted, and the UPS ride-through envelope is typical rather
than any vendor's. All are `verified: false`.

### Generator

`GEN-1` lands on the main switchboard through its transfer switch. It's rated
in prime kVA with a power factor (250 kVA × 0.8 = 200 kW by default) and is
off unless a scenario turns it on. It starts on a grid outage, or on price
(at or above $500/MWh by default, with a 30-minute minimum run). After its
start delay (30 s by default) it either forms the bus on its own or runs in
parallel with the grid. Retransfer to the grid waits for the grid to be
healthy, then makes a 100 ms open-transition break. Islanded, it trips on
overload (110 %).

Fuel is costed into the bill at 0.27 L/kWh and $2/L, about $540/MWh, plus an
idle burn. The BESS dispatches before the generator, since stored energy is
cheaper. In parallel the generator always carries a 30 % minimum load.

| Scenario | What it shows |
|---|---|
| Grid outage, generator starts in 30 s | UPS on battery for 30 s, resync to the generator, recharge from it, then the retransfer break |
| Outage, UPS recharge trips the generator | 35 % recharge takes load to ~235 kW on a 200 kW set; it trips and the load drops |
| Outage, UPS max demand keeps the generator on | Same recharge held to 185 kW; the set stays inside its rating |
| NSW1 spike, generator above $500/MWh, no BESS | $1,567 saved after $172 of fuel. With the BESS on, the BESS covers the spike alone and the generator adds only fuel cost |

The flat-price case loses money (auxiliaries and no-load losses, nothing to
arbitrage). Read every other number against it.

Recorded prices are AEMO regional reference prices (public market data), at 30
minutes, in `model/dtpower/data/nem_prices.json` with a provenance block
(`verified: false`: whether an interval is labelled by its start or its end is not
yet confirmed, so a price could sit one interval early).

## Components

Each one lives in `model/dtpower/components/` and knows nothing about any
simulation. It declares:

| | |
|---|---|
| `kind` | its IndustroML asset kind; `components.REGISTRY` maps kind to class |
| `role` | how the network steps it: `source`, `bus`, `conversion`, `storage`, `load`, `controller` |
| `ports` | its IndustroML interfaces (name, medium) |
| `schema` | its parameters: label, unit, range, default. The viewer builds its controls from this |
| `step(...)`, `snapshot()` | the physics, and what it reports each step |

| Component | Kind | Role | Model |
|---|---|---|---|
| `Grid` | `utility_supply` | source | capacity limit, spot price plus flat adder, optional export |
| `Busbar` | `switchboard` | bus | lossless node |
| `BESS` | `bess` (proposed) | storage | `Battery` behind a `Converter`, aux load, modes, grid-following: trips on outage |
| `UPS` | `ups` | conversion | load-dependent loss curve, eco mode, static bypass on overload, `Battery` ride-through, recharge |
| `GPUServerLoad` | `server` | load | fleet of DGX H100/B200/B300, GB200 NVL72, Vera Rubin NVL72 (Max-Q or Max-P), or generic; workload profiles; fixed or price-triggered power cap |
| `PriceController` | `plc` | controller | price thresholds, or an optimal perfect-foresight schedule |
| `Battery`, `Converter` | | parts | cells at the DC terminals; bidirectional PCS. Both are reused by BESS and UPS |
| `PriceSignal` | | input | recorded NEM day, time-of-use, or flat |

`Battery` and `Converter` are the parts the next simulation recombines: a UPS
whose rectifier is a bidirectional `Converter` can push its battery back onto the
bus, which is what would let it replace the BESS.

### The network

`dtpower/network.py` runs any radial IndustroML-shaped model: assets by kind,
cables from supply end to load end, a `data_link` from a controller to the
storage it drives. Parameters go in each asset's `attributes.simulation`. Each
step it walks the tree from the supply. Loads report demand, conversions turn
output into input, and at each bus the passive feeders are summed before the
storage's controller decides, so the controller knows what the site draws. The
grid takes the remainder. It rejects double feeds, unknown kinds and assets
with no supply.

**Telemetry.** `Network(..., measurements={asset_id: fn(t) -> dict})` hands an
asset its measured values through `observe()` instead of modelling it. It is
implemented for the GPU load (measured kW) and is the seam for running these
same components against a live site.

## IndustroML alignment

The kinds used are IndustroML's own (`utility_supply`, `switchboard`, `ups`,
`server`, `plc`), except **`bess`, which IndustroML does not have yet.** Nor
does it have `battery` or `inverter`. The BESS is marked `kind_proposed` and
flagged in the viewer and the API. Adding `bess` (and probably `battery_string`
and `inverter`) to `industroml.schema.json` is the change that would let these
models validate.

The model also leans on two things IndustroML only has as free-form
`attributes`: the simulation parameters, and the assumption that a cable's
`from` is the supply end. A typed ratings block (IndustroML's own known gap)
would let `UPS` read `power_kva` straight from a design model instead of its own
`rated_kw`.

## Where this goes

1. **Simulation 02:** UPS with a bidirectional inverter in place of the BESS.
   The same day, the same scenarios, and the question is whether a larger UPS
   battery doing double duty (ride-through and arbitrage) beats a separate BESS,
   and what reserve it must hold back for the outage case.
2. **Drag-and-drop composition.** The pieces are already model-driven: `GET
   /api/components` lists every kind with its role, ports and schema (the
   palette), the network accepts any radial model (the canvas), and the
   single-line diagram is laid out from the connections. What is missing is the
   editor, and the generalisation of the summary from asset ids to roles.
3. **Telemetry.** Extend `observe()` to the grid meter, BESS (SoC, kW) and UPS,
   and add a measurement source that reads the site historian.

## Assumptions to know about

All `verified: false`. These are the numbers to replace with measured or
datasheet values before quoting anything:

- **UPS loss curve.** About 96 % at full load and 94 to 95 % at quarter load in
  double conversion, 99 % in eco. The shape of published curves, not any one
  vendor's.
- **GPU power.** Idle is estimated for every model. DGX H100 and B200 maximums are NVIDIA datasheet figures. DGX B300 (14.5 kW) is from reseller listings. Vera Rubin NVL72 (190 kW Max-Q, 230 kW Max-P) comes from supply-chain estimates; NVIDIA has published no figure.
- **Throughput under a power cap.** (capped dynamic power / uncapped) ^ 0.35.
  A cap to 70 % of maximum keeps about 85 % of throughput. To calibrate.
- **Battery wear.** $25/MWh discharged. A round number in the range a pack
  cost spread over its lifetime throughput gives, not a figure from a quote.
- **Generator.** 0.27 L/kWh near full load, $2/L diesel, 10 % idle burn, 30 %
  minimum load in parallel, 110 % overload trip. Typical diesel figures, not
  any one set's.
- **BESS reconnect.** 60 s delay and 16.67 % per minute ramp, AS/NZS 4777.2 as
  commonly quoted; not checked against the standard.
- **No demand charges, no reactive power, no cable losses.** Everything is kW
  at unity power factor, and the bill is energy only.
- **Optimal is near-optimal.** It plans at full power on a grid of SoC levels.
  Where the site holds discharge below full power, it can trail well-tuned
  thresholds by a few percent.
