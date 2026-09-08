# Telemetry reference — schema v1

The contract between the Python solver and any client. `rom/dthall/telemetry.py`
is the implementation; `rom/tests/test_telemetry_schema.py` is the enforcement.

Transport is WebSocket, default `ws://127.0.0.1:8765`. Not UDP: the client is on
localhost so latency is identical either way, but commands must not be lost or
reordered — dropping "unit W1 off" leaves the twin and the HUD disagreeing
forever. Unreal also ships WebSocket support in-engine, so there is no plugin to
build.

## Design rules

- **Versioned.** `hello.schema_v` is the contract number. A client that does not
  recognise it should refuse rather than misinterpret fields.
- **Keyed by name, never by index.** Every rack and module is keyed by the same
  string used for the FreeCAD solid (`rack_A05`) and the CFD function object.
  Adding or removing a rack cannot silently shift a client's array indexing.
- **Celsius and m³/h on the wire.** The solver works in kelvin and kg/s. Nobody
  reading a HUD wants either, so conversion happens once, in `telemetry.py`.
- **Dumb client.** Anything a renderer would otherwise derive — the verdict,
  recirculation fractions, the field remap scalars, which rack is worst — is
  computed server-side. Unreal interpolates and draws; it does not do thermal
  reasoning.

## `hello` — sent once on connect

```json
{
  "type": "hello", "schema_v": 1, "hall": "AU01",
  "dt": 0.5, "publish_hz": 10.0,
  "racks": [
    {"name": "A01", "row": "A", "position": 0, "design_kw": 0.0,
     "class": "spare", "zone": "cold_A_west"},
    {"name": "A02", "row": "A", "position": 1, "design_kw": 36.75,
     "class": "b300", "zone": "cold_A_west"}
  ],
  "modules": [
    {"name": "W1", "end": "west", "airflow_m3h": 65000.0, "capacity_kw": 237.5}
  ],
  "zones": ["cold_A_west", "cold_A_east", "cold_B_west", "cold_B_east"],
  "limits": {"allowable_c": 35.0, "recommended_c": 27.0},
  "design_load_kw": 741.8, "installed_capacity_kw": 950.0
}
```

Bind scene actors from `racks[].name` here rather than assuming a rack list.
`class` is one of `b300`, `ib_leaf`, `ib_spine`, `ethernet`, `net`, `storage`,
`spare` — only `b300` racks are driven by the load controls.

## `state` — published at `publish_hz` (default 10 Hz)

A real frame, mid-training-run with a straggler, trimmed to two racks and one
module for readability:

```json
{
  "type": "state", "v": 1,
  "t_sim": 1831.0, "speed": 1.0, "mode": "auto",
  "verdict": "PASS",
  "verdict_reason": "worst rack mean 28.93 C is inside the 35 C allowable envelope",
  "supply": {
    "W1": {"on": true, "t_supply": 28.0, "flow_m3h": 67703.232,
           "airflow_fraction": 1.0, "duty_kw": 150.167,
           "capacity_kw": 237.5, "saturated": false}
  },
  "zones": {"cold_A_west": 28.0, "cold_A_east": 28.0,
            "cold_B_west": 28.0, "cold_B_east": 28.0},
  "hot_aisle": 34.76,
  "return_air": 34.778,
  "gap": {
    "cold_A_west": {"net_m3h": 30312.752, "spill_m3h": 31193.559,
                    "recirculating": false}
  },
  "racks": {
    "A01": {"kw": 0.0, "t_in": 28.926, "t_in_peak": 33.81, "t_out": 28.926,
            "flow_m3h": 0.0, "recirc": 0.137, "status": "over_recommended"},
    "A02": {"kw": 26.546, "t_in": 28.261, "t_in_peak": 29.636, "t_out": 41.101,
            "flow_m3h": 6835.224, "recirc": 0.039, "status": "over_recommended"}
  },
  "fields": {"scale": 0.451, "offset_k": 0.0},
  "totals": {
    "it_kw": 552.817, "cooling_kw": 600.669, "storage_kw": -47.852,
    "balance_err": 0.0,
    "supply_m3h": 270812.927, "rack_m3h": 143965.502, "recirc_m3h": 3944.751,
    "worst_rack": "A12", "worst_t_in": 28.926, "worst_t_in_peak": 33.81,
    "populated_racks": 21
  },
  "profile": {
    "phase": "straggler", "progress": 0.55, "mean_utilisation": 0.679,
    "checkpoints": 0, "evals": 0, "straggler": "A08"
  }
}
```

### Field notes

| Field | Meaning |
|---|---|
| `t_sim` | simulated seconds since the run started, **not** wall clock |
| `speed` | simulated seconds per real second |
| `verdict` | `PASS` / `MARGINAL` / `FAIL`, on the same rule `plot_hall.py` uses: FAIL on any populated rack's mean above allowable, MARGINAL on any face peak above allowable |
| `racks[].t_in` vs `t_in_peak` | mean and worst-face intake. **Read both.** The mean can look comfortable while the top of the rack ingests exhaust — this is the single most important lesson from the CFD sweep |
| `racks[].recirc` | fraction of intake air entrained from the hot aisle, 0–1. The direct driver for a recirculation VFX |
| `racks[].status` | `ok` / `over_recommended` / `over_allowable` — precomputed banding for materials |
| `gap[].net_m3h` | signed. Negative means hot air is being pulled back into that cold zone; the sign **is** the verdict |
| `supply[].saturated` | the coil is at nameplate capacity and can no longer hold its setpoint |
| `totals.storage_kw` | rate heat is going into the hall's thermal mass. `it_kw = cooling_kw + storage_kw` holds at every instant; it is zero only at equilibrium |
| `totals.balance_err` | residual of that identity — a model-health indicator, should stay ~0 |
| `totals.worst_rack` | worst **populated** rack, consistent with `verdict_reason`. Empty positions have a real air temperature but no IT to protect |
| `fields.scale` / `offset_k` | how to remap the baked CFD slice textures — see below |
| `profile` | present in `auto` mode only. `straggler` is a rack name or `null` |

### Remapping the baked field textures

Telemetry carries two scalars so Unreal can animate a static baked texture:

```
T_displayed(x) = reference_supply_c + fields.offset_k
               + (T_baked(x) - reference_supply_c) * fields.scale
```

`reference_supply_c` and the per-plane decode range come from
`fields/slice_manifest.json`. Lowering the supply temperature slides the whole
field; dropping the IT load compresses it toward supply temperature. The
limitation is that the *pattern* is fixed — see `docs/ROM.md`.

## Commands — client to server

All take the form `{"type": "cmd", "cmd": "<name>", ...}`. The server replies
`{"type": "ack", "cmd": ..., "args": {...}}` or
`{"type": "err", "reason": "<usable text>"}`, and publishes a fresh `state`
frame immediately so a control action feels instant rather than waiting up to a
publish interval.

| Command | Arguments | Effect |
|---|---|---|
| `set_mode` | `mode`: `auto` \| `manual` | switching *to* auto restarts the training run from its ramp |
| `set_load` | `target`: `global` \| rack name, `kw` | `global` sets every B300 rack; a rack name overrides that one. **`global` also switches the twin to manual** — otherwise the profile would overwrite the operator's slider on the next tick |
| `clear_load` | `target`: rack name | drop a per-rack override |
| `set_unit` | `unit`: `W1`…`E2`, `on`: bool | trip or restore a fan-wall module |
| `set_unit_airflow` | `unit`, `fraction`: 0–1.2 | VFD turndown |
| `set_supply_temp` | `celsius`: 5–40 | coil setpoint; reaches the air through a 45 s lag |
| `set_speed` | `x`: 0–200 | simulated seconds per real second; 0 pauses |
| `auto_config` | `seed`, `config` (optional `ProfileConfig` fields) | reseed or retune the training-run generator |
| `reset` | — | re-settle the hall to equilibrium at current inputs |

Invalid input is rejected with a reason rather than silently clamped. There is
no authority model: with several clients connected, commands are last-write-wins.

## Testing against it without Unreal

```bash
dthall run &
dthall debugview                 # the reference client, same protocol
```

Or by hand:

```bash
npx wscat -c ws://127.0.0.1:8765
> {"type":"cmd","cmd":"set_unit","unit":"W1","on":false}
```
