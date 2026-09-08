"""Wire format between the Python solver and any client (Unreal, the debug view).

Design rules, because a schema is a contract:

  * Versioned. `hello` carries `schema_v`; a client that does not recognise it
    should refuse rather than misinterpret fields.
  * Names, not indices. Every rack and module is keyed by its name, which is the
    same string as the FreeCAD solid (`rack_A05`) and the CFD function object.
    Unreal binds actors to telemetry by that name, so adding a rack does not
    silently shift a client's array indexing.
  * Celsius and m3/h on the wire. The solver works in kelvin and kg/s; nobody
    reading a HUD wants either. Conversion happens once, here.
  * Flat and dumb on the client side. Anything a renderer would otherwise have
    to derive — verdict, recirculation fraction, field remap scalars — is
    computed here so the engine only has to interpolate and draw.

See docs/TELEMETRY.md for the reference and an example frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .constants import kgs_to_m3h, to_celsius
from .sim import Snapshot
from .topology import HallSpec

SCHEMA_VERSION = 1

VALID_COMMANDS = {
    "set_mode",
    "set_load",
    "clear_load",
    "set_unit",
    "set_unit_airflow",
    "set_supply_temp",
    "set_speed",
    "auto_config",
    "reset",
}


def _f(x: Any) -> float:
    """Round for the wire: 3 decimals is well inside the model's accuracy and
    keeps frames small and diffable."""
    return round(float(x), 3)


def encode_hello(spec: HallSpec, dt: float, publish_hz: float) -> dict:
    """Sent once on connect so a client can build its scene bindings."""
    return {
        "type": "hello",
        "schema_v": SCHEMA_VERSION,
        "hall": spec.name,
        "dt": dt,
        "publish_hz": publish_hz,
        "racks": [
            {
                "name": r.name,
                "row": r.row,
                "position": r.position,
                "design_kw": r.design_kw,
                "class": r.rack_class,
                "zone": r.zone,
            }
            for r in spec.racks
        ],
        "modules": [
            {
                "name": m.name,
                "end": m.end,
                "airflow_m3h": m.airflow_m3h,
                "capacity_kw": m.capacity_kw,
            }
            for m in spec.modules
        ],
        "zones": [z.name for z in spec.zones],
        "limits": {
            "allowable_c": spec.allowable_max_c,
            "recommended_c": spec.recommended_max_c,
        },
        "design_load_kw": _f(spec.design_load_kw),
        "installed_capacity_kw": _f(spec.installed_capacity_kw),
    }


def encode_state(snap: Snapshot, spec: HallSpec) -> dict:
    """One telemetry frame."""
    obs, st = snap.obs, snap.state
    inlet_c = to_celsius(obs.rack_inlet_k)
    peak_c = to_celsius(obs.rack_inlet_peak_k)
    exhaust_c = to_celsius(obs.rack_exhaust_k)

    racks = {}
    for i, r in enumerate(spec.racks):
        over_allowable = inlet_c[i] > spec.allowable_max_c
        over_recommended = inlet_c[i] > spec.recommended_max_c
        racks[r.name] = {
            "kw": _f(obs.rack_kw[i]),
            "t_in": _f(inlet_c[i]),
            "t_in_peak": _f(peak_c[i]),
            "t_out": _f(exhaust_c[i]),
            "flow_m3h": _f(kgs_to_m3h(obs.rack_flow[i], obs.rack_inlet_k[i])),
            "recirc": _f(obs.rack_recirc_fraction[i]),
            "status": (
                "over_allowable"
                if over_allowable
                else "over_recommended"
                if over_recommended
                else "ok"
            ),
        }

    supply = {}
    for i, m in enumerate(spec.modules):
        supply[m.name] = {
            "on": bool(snap.inputs.unit_on[i]),
            "t_supply": _f(to_celsius(st.T_sup[i])),
            "flow_m3h": _f(kgs_to_m3h(obs.module_flow[i], st.T_sup[i])),
            "airflow_fraction": _f(snap.inputs.airflow_fraction[i]),
            "duty_kw": _f(obs.module_duty_kw[i]),
            "capacity_kw": m.capacity_kw,
            "saturated": bool(obs.module_saturated[i]),
        }

    zones = {z.name: _f(to_celsius(st.T_cold[i])) for i, z in enumerate(spec.zones)}
    gap = {
        z.name: {
            "net_m3h": _f(kgs_to_m3h(obs.zone_net_flow[i], st.T_cold[i])),
            "spill_m3h": _f(kgs_to_m3h(obs.zone_spill[i], st.T_cold[i])),
            "recirculating": bool(obs.zone_net_flow[i] < 0),
        }
        for i, z in enumerate(spec.zones)
    }

    live = obs.rack_kw > 0.0
    if live.any():
        idx = int(np.argmax(np.where(live, inlet_c, -np.inf)))
        worst_name = spec.rack_names[idx]
        worst_mean = float(inlet_c[idx])
        worst_peak = float(peak_c[live].max())
    else:
        worst_name, worst_mean, worst_peak = "", float("nan"), float("nan")

    frame: dict[str, Any] = {
        "type": "state",
        "v": SCHEMA_VERSION,
        "t_sim": _f(snap.t),
        "speed": _f(snap.speed),
        "mode": snap.mode,
        "verdict": snap.verdict,
        "verdict_reason": snap.verdict_reason,
        "supply": supply,
        "zones": zones,
        "hot_aisle": _f(to_celsius(st.T_hot)),
        "return_air": _f(to_celsius(st.T_ret)),
        # The commanded coil setpoint, distinct from the achieved `t_supply` above
        # (they differ whenever a coil is saturated, or mid-lag). A HUD slider
        # needs the setpoint, or it drifts away from what the operator asked for.
        "supply_setpoint_c": _f(snap.inputs.supply_temp_c),
        # What the load controls are currently holding the driven racks at, so a
        # client can show its slider at the right place instead of a stale default.
        "b300_setpoint_kw": _f(snap.extras.get("b300_setpoint_kw", 0.0)),
        "gap": gap,
        "racks": racks,
        "fields": {
            "scale": _f(obs.field_scale),
            "offset_k": _f(obs.field_offset_k),
        },
        "totals": {
            "it_kw": _f(obs.it_load_kw),
            "cooling_kw": _f(obs.cooling_kw),
            # Heat going into the hall's thermal mass. The books read
            #   it_kw = cooling_kw + storage_kw
            # at every instant; storage_kw is zero only at equilibrium, so
            # comparing load against duty alone is a steady-state check, not a
            # live one. A HUD showing "IT 700 kW / cooling 500 kW" during a load
            # ramp is not an error — the other 200 kW is warming the metal.
            "storage_kw": _f(obs.storage_kw),
            "balance_err": _f(
                abs(obs.it_load_kw - obs.cooling_kw - obs.storage_kw)
                / max(obs.it_load_kw, 1e-9)
            ),
            "supply_m3h": _f(kgs_to_m3h(float(obs.module_flow.sum()), st.T_sup.mean())),
            "rack_m3h": _f(
                kgs_to_m3h(float(obs.rack_flow.sum()), float(obs.rack_inlet_k.mean()))
            ),
            "recirc_m3h": _f(
                kgs_to_m3h(obs.extras["recirc_total"], st.T_hot)
            ),
            # Worst *populated* rack, matching the verdict's own rule. An empty
            # cabinet position still has an air temperature, but naming it as the
            # hall's worst rack would put a position with no IT in it at the top
            # of the HUD while the verdict talked about a different rack.
            "worst_rack": worst_name,
            "worst_t_in": _f(worst_mean),
            "worst_t_in_peak": _f(worst_peak),
            "populated_racks": int(live.sum()),
        },
    }

    if snap.profile is not None:
        frame["profile"] = {
            "phase": snap.profile.phase,
            "progress": _f(snap.profile.progress),
            "mean_utilisation": _f(snap.profile.mean_utilisation),
            "checkpoints": snap.profile.checkpoints,
            "evals": snap.profile.evals,
            "straggler": (
                None
                if snap.profile.straggler is None
                else spec.racks[
                    [
                        i
                        for i, r in enumerate(spec.racks)
                        if r.rack_class == "b300"
                    ][snap.profile.straggler]
                ].name
            ),
        }
    return frame


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


@dataclass
class Command:
    cmd: str
    args: dict


def parse_command(msg: dict) -> Command:
    """Validate an inbound message. Raises ValueError with a usable reason —
    clients get that text back in an `err` frame rather than silence."""
    if not isinstance(msg, dict):
        raise ValueError("message must be a JSON object")
    if msg.get("type") != "cmd":
        raise ValueError(f"unexpected message type {msg.get('type')!r}, expected 'cmd'")
    cmd = msg.get("cmd")
    if cmd not in VALID_COMMANDS:
        raise ValueError(
            f"unknown command {cmd!r}; expected one of {sorted(VALID_COMMANDS)}"
        )
    return Command(cmd=cmd, args={k: v for k, v in msg.items() if k not in ("type", "cmd")})


def apply_command(engine, command: Command) -> dict:
    """Dispatch a parsed command onto a SimEngine. Returns an ack payload."""
    a = command.args
    match command.cmd:
        case "set_mode":
            engine.set_mode(_require(a, "mode"))
        case "set_load":
            engine.set_load(a.get("target", "global"), float(_require(a, "kw")))
        case "clear_load":
            engine.clear_override(_require(a, "target"))
        case "set_unit":
            engine.set_unit(_require(a, "unit"), bool(_require(a, "on")))
        case "set_unit_airflow":
            engine.set_unit_airflow(
                _require(a, "unit"), float(_require(a, "fraction"))
            )
        case "set_supply_temp":
            engine.set_supply_temp(float(_require(a, "celsius")))
        case "set_speed":
            engine.set_speed(float(_require(a, "x")))
        case "auto_config":
            from .profiles import ProfileConfig

            config = None
            if "config" in a:
                config = ProfileConfig(**a["config"])
            engine.configure_auto(seed=a.get("seed"), config=config)
        case "reset":
            engine.settle()
    return {"type": "ack", "cmd": command.cmd, "args": a}


def _require(args: dict, key: str):
    if key not in args:
        raise ValueError(f"missing required field {key!r}")
    return args[key]


def error(reason: str) -> dict:
    return {"type": "err", "reason": reason}
