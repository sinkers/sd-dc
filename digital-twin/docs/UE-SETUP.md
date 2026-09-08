# Unreal Engine 5 setup runbook

Manual steps are marked **[you]** — they need a GUI, a login, or a licence
acceptance and cannot be scripted from here.

Nothing in this document is required to run or develop the twin. The solver, the
telemetry protocol and the debug dashboard all work without Unreal installed; see
the README's quickstart. This is the presentation layer.

## 1. Install

**[you]**

1. Download the Epic Games Launcher for macOS from
   <https://www.epicgames.com/store/download> and sign in (a free Epic account is
   enough; accepting the UE EULA is part of first run).
2. *Unreal Engine* tab → *Library* → **+** → install **UE 5.4 or later**.
   Native Apple Silicon since 5.2. Budget ~60 GB of disk and a long download.
3. Install Xcode from the App Store, then:
   ```bash
   sudo xcode-select --install
   sudo xcodebuild -license accept
   ```
   Blueprint-only work does not strictly need it, but the WebSocket fallback in
   step 3 does, and the editor complains without it.
4. Sanity check: launch the editor, create a throwaway *Blank* project, confirm
   the viewport renders and *Edit → Project Settings → Platforms → Mac* shows
   Metal. If Lumen looks black, your GPU tier may need
   *Project Settings → Engine → Rendering → Global Illumination → Lumen* checked
   explicitly.

## 2. Create the project

**[you]** *Games → Blank*, **Blueprint**, no starter content, project name
`AU01Twin`, location `digital-twin/ue/`.

Then:

1. *Edit → Plugins*, enable and restart:
   - **glTF Importer** (built in, off by default) — needed for the geometry
   - **WebSocket Networking** (built in) — the telemetry transport
   - **Niagara** (on by default) — airflow VFX
   - **JSON Blueprint Utilities** (built in) — parse frames in Blueprints
2. Add a `.gitignore` at `digital-twin/ue/AU01Twin/`:
   ```
   Binaries/
   Intermediate/
   Saved/
   DerivedDataCache/
   *.xcworkspace/
   ```
   The `Content/` and `Config/` directories are the parts worth committing.
3. *Project Settings → Engine → General Settings → Framerate*: uncap smoothing,
   set a fixed 60 fps target. A twin that stutters reads as a broken simulation.

### On WebSockets in Blueprint

UE's `FWebSocketsModule` is C++; Blueprint node coverage for it varies by
version. Check first — if 5.4+ exposes usable *Create WebSocket* nodes, stay in
Blueprint. If not, the fallback is a ~60-line `UGameInstanceSubsystem` wrapping
`FWebSocketsModule::Get().CreateWebSocket()`, exposing `OnFrameReceived(FString)`
as a `BlueprintAssignable` delegate and a `SendCommand(FString)` UFUNCTION. That
is the only C++ the scene needs, and it makes the Xcode install in step 1
non-optional. Decide this once, at the start of the scene work, rather than
discovering it halfway through.

## 3. Export the geometry

The CFD's STLs are unnamed triangle soup — no object names, no hierarchy. The
whole binding strategy depends on names, so geometry is re-exported from the
source FreeCAD model as glTF, which preserves them.

Bring up the FreeCAD VM (see `vm-setup/`), open
`DAME_AU01_Building.FCStd`, and run through the MCP bridge:

```python
exec(open('/path/to/digital-twin/ue-export/export_gltf.py').read())
manifest = export_all('/path/to/digital-twin/ue-export/assets')
```

This writes one `.glb` per group — `shell`, `racks`, `fanwalls`, `hac`, `gantry`,
`dressing` — plus `export_manifest.json`, the actor-name → telemetry-key table.
It deliberately exports **more** than the CFD needs: full gantry detail, separate
door leaves, per-module fan wall bodies. The CFD export is reduced for meshing;
this one is for looking at.

The script then cross-checks itself against `cfd_export_params.json`: that all 24
scheduled racks are present, that each is a 600 × 1200 × 2000 box, and that every
rack centre falls inside the 24.13 × 8.2 m room. That last check is the one that
catches a millimetre/metre mix-up, which otherwise shows up as a scene that is
1000× too large and takes an afternoon to diagnose.

### Import into UE

**[you]** Drag the `.glb` files into `Content/Geometry/`. In the import dialog:
- *Scale*: leave at 1.0 — the glTF is already in metres and the importer converts
  to UE centimetres.
- *Generate Lightmap UVs*: on for `shell` and `dressing`, off for `gantry` (too
  many parts, and Lumen does not need them).
- *Combine Meshes*: **off** for `racks` and `fanwalls` — the per-node split is
  the binding mechanism. On is fine for `gantry`.

Verify placement before going further: drop a 24.13 × 8.2 m box brush at the
origin and confirm the shell matches it. Rack `A01` should sit at the west end of
row A near `pod_origin` (8.435, 2.0) m.

## 4. Scene structure

```
BP_TwinClient      (GameInstance subsystem or a persistent actor)
  ├─ connects ws://127.0.0.1:8765
  ├─ on hello  -> spawn/bind actors from racks[].name
  ├─ on state  -> broadcast a TwinState struct via an event dispatcher
  └─ SendCommand(json) for HUD controls

BP_Rack            (24 instances, one per hello.racks[])
  ├─ TelemetryKey  (FName, e.g. "A05")  <- set at bind time, not hand-authored
  ├─ front/rear panel material: emissive colour from t_in / t_out via a LUT
  ├─ Niagara exhaust plume: rate from flow_m3h, colour from t_out
  ├─ warning pulse when status != "ok" or recirc > threshold
  └─ nameplate decal from the key

BP_FanWall         (4 instances, W1 W2 E1 E2)
  ├─ fan rotation rate from flow_m3h
  ├─ supply/intake Niagara volumes, off when on == false
  └─ amber state when saturated == true

BP_GapFlow         (4 instances, one per cold zone)
  └─ Niagara curl-noise sheet over the HAC top edge; direction and rate from
     gap[zone].net_m3h. This is the money shot: it visualises the sign flip the
     whole model turns on.

BP_FieldPlane      (3 instances)
  └─ translucent quad at the baked slice location, sampling
     fields/baked/T_<plane>.png, remapped live by fields.scale / fields.offset_k
     (formula in docs/TELEMETRY.md). Placement comes from
     fields/slice_manifest.json. Toggleable — it is a diagnostic overlay, not
     always-on decoration.

WBP_HUD
  ├─ mode toggle (auto / manual)
  ├─ B300 load slider -> set_load global
  ├─ per-rack override panel -> set_load <rack>
  ├─ W1/W2/E1/E2 switches -> set_unit
  ├─ supply temp + speed sliders
  ├─ 24-row rack table: kw, t_in, t_in_peak, status
  └─ verdict banner from verdict / verdict_reason
```

Bind actors from `hello`, never from a hand-maintained list — a rack added to the
schedule should appear without touching the Blueprint. Log any telemetry key that
finds no actor, and any actor that finds no key; both are silent-failure modes
that otherwise look like "that one rack never lights up".

## 5. Verification

Before calling the scene done:

| Check | How |
|---|---|
| geometry scale | measure the shell in-editor against 24.13 × 8.2 × 4.09 m |
| rack placement | `A01` at the west end of row A; `B12` at the east end of row B |
| all racks bound | 24/24, with unbound keys logged as warnings |
| numbers agree | run `dthall debugview` next to the packaged scene; the HUD's worst rack and temperature must match the dashboard's for the same session |
| control latency | HUD slider → visible material change in < 300 ms |
| determinism | `dthall replay --script scenarios/west_fanwall_trip.json` and the same scenario driven through the HUD should reach the same temperatures |

The last one matters most. The dashboard and the scene are two clients of the
same solver, so any disagreement between them is a bug in the client that
disagrees — not a difference of opinion about the physics.

## 6. A demo that shows the physics

`scenarios/west_fanwall_trip.json` is the sequence worth rehearsing:

1. Auto mode, training run at full B300 load. Hall is green, gap flow spilling
   cold air into the hot aisle (blue).
2. Trip **W1**, then **W2**. Installed capacity falls to 475 kW against 742 kW of
   IT — there is no steady state.
3. Watch the west cold zones go negative, the recirculation VFX reverse over the
   containment, and the west racks heat while the east racks stay comfortable.
   The verdict walks PASS → MARGINAL → FAIL.
4. Shed the job to 20 kW/rack. It stabilises — but at a hot-aisle temperature in
   the seventies, because the two remaining modules are at their capacity limit.
5. Restore W1 and W2. Recovery to PASS takes a couple of minutes of simulated
   time, which is the thermal mass discharging.

Run it at `speed=8` or more; at 1× it takes 40 minutes.
