"""`dthall` command line.

    dthall run            start the twin service (WebSocket)
    dthall debugview      live dashboard, as a WebSocket client
    dthall calibrate      fit the ROM against the hall CFD
    dthall validate       score the committed parameters against the CFD
    dthall replay         run a scripted scenario headlessly, write CSV
    dthall info           print the hall topology the twin is built from
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import topology


def _spec(args):
    if getattr(args, "hall", "au01") == "case-hall":
        return topology.from_hall_parameters()
    return topology.from_cfd_export()


def _add_hall_arg(p):
    p.add_argument(
        "--hall",
        choices=("au01", "case-hall"),
        default="au01",
        help="which hall to model (default: the as-built AU01 room)",
    )


def cmd_run(args) -> int:
    from .server import ServerConfig, run

    # Only pass options that were given on the command line. ServerConfig reads
    # DTHALL_* from the environment for its defaults, and passing argparse's own
    # defaults here would silently shadow them — so a systemd unit setting
    # DTHALL_MODE would be ignored with no indication why.
    overrides = {
        name: value
        for name, value in (
            ("host", args.host),
            ("port", args.port),
            ("dt", args.dt),
            ("speed", args.speed),
            ("mode", args.mode),
            ("seed", args.seed),
            ("publish_hz", args.publish_hz),
        )
        if value is not None
    }
    run(
        spec=_spec(args),
        config=ServerConfig(settle=not args.no_settle, **overrides),
    )
    return 0


def cmd_debugview(args) -> int:
    from .debugview import DebugView

    return DebugView(args.connect).run()


def cmd_viewer(args) -> int:
    from .viewer import run

    run(
        spec=_spec(args),
        http_port=args.port,
        ws_port=args.ws_port,
        speed=args.speed,
        mode=args.mode,
        seed=args.seed,
        dt=args.dt,
        open_browser=not args.no_browser,
    )
    return 0


def cmd_calibrate(args) -> int:
    from . import calibrate as cal

    return cal.main(["--out", str(args.out)] if args.out else [])


def cmd_validate(args) -> int:
    from . import calibrate as cal

    card = cal.validate()
    print(card.report())
    return 0 if card.passed else 1


def cmd_info(args) -> int:
    spec = _spec(args)
    print(f"{spec.name}")
    print(f"  racks                 {len(spec.racks)}")
    print(f"  design air load       {spec.design_load_kw:.1f} kW")
    print(f"  installed capacity    {spec.installed_capacity_kw:.1f} kW")
    print(f"  supply air            {spec.supply_temp_c:.1f} C")
    print(f"  design rack rise      {spec.design_delta_t_k:.1f} K")
    print(f"  envelope              {spec.recommended_max_c:.0f} / {spec.allowable_max_c:.0f} C")
    print(f"  hot aisle volume      {spec.hot_aisle_volume_m3:.1f} m3")
    print(f"  return volume         {spec.return_volume_m3:.1f} m3")
    print("  fan wall modules")
    for m in spec.modules:
        print(
            f"    {m.name:4s} {m.end:5s} {m.airflow_m3h:>8.0f} m3/h  "
            f"{m.capacity_kw:>6.1f} kW"
        )
    print("  cold zones")
    for z in spec.zones:
        print(f"    {z.name:14s} {z.volume_m3:>7.1f} m3")
    print("  racks")
    for r in spec.racks:
        print(
            f"    {r.name:8s} row {r.row} pos {r.position:2d}  "
            f"{r.design_kw:>6.2f} kW  {r.rack_class:<9s} {r.zone}"
        )
    if args.json:
        print(json.dumps(spec.notes, indent=2))
    return 0


def cmd_replay(args) -> int:
    from .replay import run_scenario

    return run_scenario(
        _spec(args), Path(args.script), Path(args.out) if args.out else None
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dthall", description=__doc__.splitlines()[0])
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="start the twin service")
    _add_hall_arg(p)
    # Defaults are None on purpose: unset means "use ServerConfig's default,
    # which may come from a DTHALL_* environment variable".
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--dt", type=float, default=None, help="physics timestep [s]")
    p.add_argument("--speed", type=float, default=None, help="sim seconds per real second")
    p.add_argument("--mode", choices=("auto", "manual"), default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--publish-hz", type=float, default=None)
    p.add_argument(
        "--no-settle",
        action="store_true",
        help="publish from a cold start instead of settling to equilibrium first",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("viewer", help="3D viewer + twin, opens in a browser")
    _add_hall_arg(p)
    p.add_argument("--port", type=int, default=8080, help="HTTP port for the viewer")
    p.add_argument("--ws-port", type=int, default=8765, help="telemetry port")
    p.add_argument("--speed", type=float, default=10.0)
    p.add_argument("--mode", choices=("auto", "manual"), default="auto")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--dt", type=float, default=0.5)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(func=cmd_viewer)

    p = sub.add_parser("debugview", help="live 2D dashboard (WebSocket client)")
    p.add_argument("--connect", default="ws://127.0.0.1:8765")
    p.set_defaults(func=cmd_debugview)

    p = sub.add_parser("calibrate", help="fit the ROM against the hall CFD")
    p.add_argument("--out", type=Path, default=None)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("validate", help="score committed parameters against the CFD")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("info", help="print the hall topology")
    _add_hall_arg(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("replay", help="run a scripted scenario headlessly")
    _add_hall_arg(p)
    p.add_argument("--script", required=True, help="scenario JSON")
    p.add_argument("--out", default=None, help="CSV output path")
    p.set_defaults(func=cmd_replay)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
