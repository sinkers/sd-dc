"""The twin service: static assets, health, and a twin per visitor, on one port.

Why WebSocket rather than raw UDP: commands must arrive in order and none may be
dropped — losing "unit W1 off" leaves the twin and the HUD disagreeing forever.
Unreal also ships WebSocket support in-engine, so there is no plugin to build.

## One port, three jobs

`websockets.serve` is given a `process_request` hook, so a single listener handles

    GET /healthz    -> 200, JSON status (the load balancer / Docker health check)
    GET /ws         -> WebSocket upgrade, one twin per connection
    GET /*          -> static viewer assets, when serving them locally

Doing it on one port is not tidiness. Two ports means the browser connecting to
`ws://host:8765` from a page served over HTTPS, which is blocked as mixed content,
and it means two targets to route and health-check in front. One port and a `/ws`
path makes local development and the deployed service the same shape.

## A twin per visitor

Each connection gets its own `SimEngine`, so one visitor tripping a fan wall
cannot disturb another's session. That is what makes an unauthenticated URL
tolerable. Settling a fresh hall costs ~350 ms of CPU, so the settled state is
computed **once** at boot and deep-copied per session: a burst of visitors cannot
stampede the processor.

One physics task walks the whole session registry rather than a task per socket —
fewer moving parts, and the per-session cost is small enough (about 5 ms of CPU per
second at the default speed) that iterating a few dozen is nothing.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import mimetypes
import os
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path

from . import telemetry
from .params import RomParams
from .profiles import ProfileConfig
from .sim import SimEngine
from .topology import HallSpec, from_cfd_export

log = logging.getLogger("dthall.server")

# Where the viewer's static assets live. Relative to the source tree during
# development, but an installed package sits in site-packages, where there is no
# sibling viewer/ directory — so a deployment must say where it put them.
# Getting this wrong serves a working API and a 404 for every asset.
VIEWER_ROOT = Path(
    os.environ.get(
        "DTHALL_VIEWER_ROOT", Path(__file__).resolve().parents[2] / "viewer"
    )
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    publish_hz: float = field(default_factory=lambda: _env_float("DTHALL_PUBLISH_HZ", 10.0))
    dt: float = 0.5
    speed: float = 1.0
    mode: str = field(default_factory=lambda: os.environ.get("DTHALL_MODE", "auto"))
    seed: int = field(default_factory=lambda: _env_int("DTHALL_SEED", 0))
    settle: bool = True
    serve_static: bool = True

    # -- public-endpoint guards ---------------------------------------------
    # This service is reachable without authentication, so every one of these is
    # load-bearing rather than decorative.
    max_sessions: int = field(default_factory=lambda: _env_int("DTHALL_MAX_SESSIONS", 40))
    max_speed: float = field(default_factory=lambda: _env_float("DTHALL_MAX_SPEED", 60.0))
    max_commands_per_s: float = field(
        default_factory=lambda: _env_float("DTHALL_MAX_CMD_RATE", 20.0)
    )
    max_session_seconds: float = field(
        default_factory=lambda: _env_float("DTHALL_MAX_SESSION_S", 4 * 3600.0)
    )


class Session:
    """One visitor's hall."""

    __slots__ = ("ws", "engine", "started", "tokens", "last_refill", "latest", "peer")

    def __init__(self, ws, engine: SimEngine, peer: str, cmd_rate: float = 20.0):
        self.ws = ws
        self.engine = engine
        self.peer = peer
        self.started = time.monotonic()
        # Start the bucket FULL. Starting it empty means the first command a client
        # sends is silently dropped, because no time has passed for tokens to
        # accrue — which looks exactly like the control being broken. The bucket
        # depth doubles as the allowed burst, and the viewer legitimately bursts
        # (the fan slider issues one command per module).
        self.tokens = float(cmd_rate)
        self.last_refill = self.started
        self.latest: dict | None = None

    def allow_command(self, rate: float) -> bool:
        """Token bucket, so a client cannot spin the solver with a command loop."""
        now = time.monotonic()
        self.tokens = min(rate, self.tokens + (now - self.last_refill) * rate)
        self.last_refill = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True

    def expired(self, limit: float) -> bool:
        return limit > 0 and (time.monotonic() - self.started) > limit


class TwinServer:
    def __init__(
        self,
        spec: HallSpec | None = None,
        params: RomParams | None = None,
        config: ServerConfig | None = None,
        profile_config: ProfileConfig | None = None,
    ):
        self.config = config or ServerConfig()
        self.spec = spec or from_cfd_export()
        self.params = params or RomParams.load()
        self.profile_config = profile_config
        self.sessions: dict[int, Session] = {}
        self._settled_state = None
        self._boot = time.monotonic()
        self._stop = asyncio.Event()
        self._served = 0

    # -- session lifecycle ---------------------------------------------------
    def _prewarm(self) -> None:
        """Settle one hall at boot; every session starts from a copy of it."""
        engine = self._new_engine()
        snap = engine.settle()
        self._settled_state = copy.deepcopy(engine.state)
        log.info(
            "prewarmed: %.1f kW IT, worst rack intake %.2f C, verdict %s",
            snap.obs.it_load_kw,
            max(
                r["t_in"]
                for r in telemetry.encode_state(snap, self.spec)["racks"].values()
            ),
            snap.verdict,
        )

    def _new_engine(self) -> SimEngine:
        return SimEngine(
            self.spec,
            params=self.params,
            dt=self.config.dt,
            speed=self.config.speed,
            mode=self.config.mode,
            seed=self.config.seed,
            profile_config=self.profile_config,
        )

    def new_session(self, ws, peer: str = "-") -> Session | None:
        if len(self.sessions) >= self.config.max_sessions:
            return None
        engine = self._new_engine()
        if self._settled_state is not None:
            engine.state = copy.deepcopy(self._settled_state)
        session = Session(ws, engine, peer, self.config.max_commands_per_s)
        self.sessions[id(ws)] = session
        self._served += 1
        return session

    def drop_session(self, ws) -> None:
        self.sessions.pop(id(ws), None)

    # -- tasks ---------------------------------------------------------------
    async def _physics(self) -> None:
        """Advance every session against the wall clock, scaled by its own speed."""
        last = time.monotonic()
        interval = 1.0 / max(self.config.publish_hz * 2.0, 1.0)
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            now = time.monotonic()
            elapsed, last = now - last, now
            for session in tuple(self.sessions.values()):
                try:
                    snap = session.engine.advance(elapsed * session.engine.speed)
                    session.latest = telemetry.encode_state(snap, self.spec)
                except Exception:  # noqa: BLE001 - one bad session must not stop the rest
                    log.exception("session %s failed to advance", session.peer)
                    self.drop_session(session.ws)

    async def _publish(self) -> None:
        interval = 1.0 / self.config.publish_hz
        while not self._stop.is_set():
            await asyncio.sleep(interval)
            for session in tuple(self.sessions.values()):
                if session.expired(self.config.max_session_seconds):
                    log.info("session %s hit its lifetime limit", session.peer)
                    await self._send(
                        session.ws,
                        json.dumps(
                            telemetry.error(
                                "session lifetime limit reached — reload to continue"
                            )
                        ),
                    )
                    await self._close(session.ws)
                    continue
                if session.latest is not None:
                    await self._send(session.ws, json.dumps(session.latest))

    @staticmethod
    async def _send(ws, payload: str) -> None:
        try:
            await ws.send(payload)
        except Exception:  # a client that went away is not an error worth raising
            pass

    @staticmethod
    async def _close(ws) -> None:
        try:
            await ws.close()
        except Exception:
            pass

    # -- HTTP ---------------------------------------------------------------
    def _status(self) -> dict:
        return {
            "status": "ok",
            "hall": self.spec.name,
            "schema_v": telemetry.SCHEMA_VERSION,
            "sessions": len(self.sessions),
            "max_sessions": self.config.max_sessions,
            "sessions_served": self._served,
            "uptime_s": round(time.monotonic() - self._boot, 1),
            "prewarmed": self._settled_state is not None,
        }

    @staticmethod
    def _http(
        status: HTTPStatus,
        body: bytes,
        content_type: str = "text/plain; charset=utf-8",
        cache: str = "no-store",
    ):
        """Build an HTTP response with a binary body.

        Not `connection.respond()`: that helper takes *text* and fixes
        Content-Length from it, so assigning `.body` afterwards leaves the length
        at zero and the client reads an empty file. Constructing the Response
        directly is the only way to serve bytes.
        """
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        headers = Headers(
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", cache),
                ("X-Content-Type-Options", "nosniff"),
            ]
        )
        return Response(int(status), status.phrase, headers, body)

    async def process_request(self, connection, request):
        """Serve health and static assets; let /ws fall through to the upgrade.

        Returning None hands the connection to the WebSocket handler; returning a
        response short-circuits it.
        """
        path = request.path.split("?", 1)[0]

        if path == "/ws":
            return None  # upgrade

        if path in ("/healthz", "/health"):
            body = (json.dumps(self._status()) + "\n").encode()
            return self._http(HTTPStatus.OK, body, "application/json")

        if not self.config.serve_static:
            return self._http(HTTPStatus.NOT_FOUND, b"not found\n")

        return self._static(path)

    def _static(self, path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        root = VIEWER_ROOT.resolve()
        target = (root / rel).resolve()
        # Refuse anything that escapes the viewer directory.
        if not target.is_relative_to(root) or not target.is_file():
            return self._http(HTTPStatus.NOT_FOUND, b"not found\n")

        ctype, _ = mimetypes.guess_type(str(target))
        # The geometry bundle is regenerated by prepare_geometry.py; caching it is
        # the difference between "my edit did nothing" and a long detour.
        cache = "no-store" if rel.startswith("geometry/") else "max-age=300"
        return self._http(
            HTTPStatus.OK,
            target.read_bytes(),
            ctype or "application/octet-stream",
            cache,
        )

    # -- WebSocket ----------------------------------------------------------
    async def handler(self, ws) -> None:
        peer = str(getattr(ws, "remote_address", ("-",))[0])
        session = self.new_session(ws, peer)
        if session is None:
            log.warning("refused %s: at capacity (%d)", peer, self.config.max_sessions)
            await self._send(
                ws,
                json.dumps(
                    telemetry.error(
                        f"at capacity ({self.config.max_sessions} sessions) — try shortly"
                    )
                ),
            )
            await self._close(ws)
            return

        log.info("session opened for %s (%d active)", peer, len(self.sessions))
        try:
            await ws.send(
                json.dumps(
                    telemetry.encode_hello(
                        self.spec, self.config.dt, self.config.publish_hz
                    )
                )
            )
            snap = session.engine.snapshot()
            session.latest = telemetry.encode_state(snap, self.spec)
            await ws.send(json.dumps(session.latest))
            async for raw in ws:
                await self._handle_message(session, raw)
        except Exception as exc:  # noqa: BLE001 - a dropped client must not kill the run
            log.debug("session error for %s: %s", peer, exc)
        finally:
            self.drop_session(ws)
            log.info("session closed for %s (%d active)", peer, len(self.sessions))

    async def _handle_message(self, session: Session, raw: str) -> None:
        if not session.allow_command(self.config.max_commands_per_s):
            return  # silently drop; telling a flooder about it invites more
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            await self._send(
                session.ws, json.dumps(telemetry.error(f"invalid JSON: {exc}"))
            )
            return
        try:
            command = telemetry.parse_command(msg)
            if command.cmd == "set_speed":
                # Clamp rather than reject: a visitor dragging a slider should not
                # get an error, and CPU per session scales with speed.
                x = float(command.args.get("x", 1.0))
                command.args["x"] = max(0.0, min(x, self.config.max_speed))
            ack = telemetry.apply_command(session.engine, command)
        except (ValueError, TypeError) as exc:
            await self._send(session.ws, json.dumps(telemetry.error(str(exc))))
            return
        # Publish immediately so a control action feels instant, rather than
        # waiting up to a publish interval.
        session.latest = telemetry.encode_state(session.engine.snapshot(), self.spec)
        await self._send(session.ws, json.dumps(ack))

    # -- lifecycle -----------------------------------------------------------
    async def serve(self) -> None:
        import websockets

        if self.config.serve_static and not (VIEWER_ROOT / "index.html").is_file():
            # Say so loudly at boot rather than 404 every asset silently.
            log.warning(
                "no viewer assets at %s — set DTHALL_VIEWER_ROOT. The API and "
                "/healthz still work; the page will not load.",
                VIEWER_ROOT,
            )

        if self.config.settle:
            log.info("settling one hall to reuse for every session")
            self._prewarm()

        async with websockets.serve(
            self.handler,
            self.config.host,
            self.config.port,
            process_request=self.process_request,
            ping_interval=20,
            ping_timeout=20,
            max_size=64 * 1024,
        ):
            log.info(
                "dthall serving %s on http://%s:%d  (ws at /ws, health at /healthz, "
                "mode=%s speed=%gx, max %d sessions)",
                self.spec.name,
                self.config.host,
                self.config.port,
                self.config.mode,
                self.config.speed,
                self.config.max_sessions,
            )
            await asyncio.gather(self._physics(), self._publish(), self._stop.wait())

    def stop(self) -> None:
        self._stop.set()


def run(
    spec: HallSpec | None = None,
    config: ServerConfig | None = None,
    params: RomParams | None = None,
) -> None:
    server = TwinServer(spec=spec, config=config, params=params)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        log.info("stopped")
