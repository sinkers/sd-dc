"""End-to-end over a real socket: the exact path Unreal will take.

Starts the service on an ephemeral port, connects a client, and drives it the way
a HUD would. If this passes, the engine work has a working contract to build
against.
"""

import asyncio
import json

import pytest

from dthall import topology
from dthall.server import ServerConfig, TwinServer

def run(coro, timeout=30.0):
    """Run an async test body without depending on pytest-asyncio."""
    return asyncio.run(asyncio.wait_for(coro, timeout))


class Harness:
    """Serves the twin on a free port for the duration of a `with` block."""

    def __init__(self, **kwargs):
        self.config = ServerConfig(port=0, settle=False, publish_hz=50.0, **kwargs)
        self.server = TwinServer(
            spec=topology.from_cfd_export(), config=self.config
        )

    async def __aenter__(self):
        import websockets

        # Mirror TwinServer.serve()'s listener configuration, including
        # process_request — without it the listener answers every plain HTTP
        # request with 426 Upgrade Required and the health/static routes are
        # untested.
        self._ws_server = await websockets.serve(
            self.server.handler,
            self.config.host,
            0,
            process_request=self.server.process_request,
        )
        self.port = self._ws_server.sockets[0].getsockname()[1]
        self._tasks = [
            asyncio.create_task(self.server._physics()),
            asyncio.create_task(self.server._publish()),
        ]
        return self

    async def __aexit__(self, *exc):
        self.server.stop()
        for t in self._tasks:
            t.cancel()
        self._ws_server.close()
        await self._ws_server.wait_closed()

    def connect(self):
        import websockets

        return websockets.connect(f"ws://127.0.0.1:{self.port}/ws")

    async def http(self, path):
        """Fetch over HTTP from within an async test body.

        Must not block: the server shares this event loop, so a synchronous
        urlopen deadlocks — the request cannot be answered while the caller is
        blocking on the answer.
        """
        import urllib.request

        def fetch():
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}", timeout=5
            ) as r:
                return r.status, r.read(), dict(r.headers)

        return await asyncio.to_thread(fetch)

    @staticmethod
    async def next_of(ws, kind, limit=400):
        for _ in range(limit):
            msg = json.loads(await ws.recv())
            if msg.get("type") == kind:
                return msg
        raise AssertionError(f"no {kind!r} frame arrived")

    @staticmethod
    async def drain_to_latest(ws, kind="state", seconds=0.4):
        """Read past the buffered backlog and return the most recent frame.

        Frames arrive at publish_hz whether or not anyone reads them, so a socket
        left idle for half a second holds a queue of stale ones. Taking `next_of`
        after a sleep returns the OLDEST of those, which reads as "time is not
        advancing" when it is.
        """
        latest = None
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                msg = json.loads(
                    await asyncio.wait_for(ws.recv(), timeout=0.1)
                )
            except asyncio.TimeoutError:
                break
            if msg.get("type") == kind:
                latest = msg
        if latest is None:
            raise AssertionError(f"no {kind!r} frame arrived")
        return latest


def test_client_receives_hello_then_state():
    async def body():
        async with Harness(mode="manual") as h:
            async with h.connect() as ws:
                hello = json.loads(await ws.recv())
                assert hello["type"] == "hello"
                assert hello["schema_v"] == 1
                assert len(hello["racks"]) == 24

                state = await h.next_of(ws, "state")
                assert set(state["racks"]) == {r["name"] for r in hello["racks"]}
                assert state["mode"] == "manual"

    run(body())


def test_a_command_changes_the_twin_and_is_acked():
    async def body():
        async with Harness(mode="manual") as h:
            async with h.connect() as ws:
                await h.next_of(ws, "state")
                await ws.send(
                    json.dumps(
                        {
                            "type": "cmd",
                            "cmd": "set_load",
                            "target": "global",
                            "kw": 10.0,
                        }
                    )
                )
                ack = await h.next_of(ws, "ack")
                assert ack["cmd"] == "set_load"

                state = await h.next_of(ws, "state")
                assert state["racks"]["A05"]["kw"] == pytest.approx(10.0)

    run(body())


def test_turning_off_a_fan_wall_module_shows_up_in_telemetry():
    async def body():
        async with Harness(mode="manual") as h:
            async with h.connect() as ws:
                await h.next_of(ws, "state")
                await ws.send(
                    json.dumps(
                        {"type": "cmd", "cmd": "set_unit", "unit": "W1", "on": False}
                    )
                )
                await h.next_of(ws, "ack")
                state = await h.next_of(ws, "state")
                assert state["supply"]["W1"]["on"] is False
                assert state["supply"]["W1"]["flow_m3h"] == 0.0
                assert state["supply"]["E1"]["on"] is True

    run(body())


def test_a_bad_command_returns_an_error_and_keeps_the_run_alive():
    async def body():
        async with Harness(mode="manual") as h:
            async with h.connect() as ws:
                await h.next_of(ws, "state")
                await ws.send(json.dumps({"type": "cmd", "cmd": "explode"}))
                err = await h.next_of(ws, "err")
                assert "unknown command" in err["reason"]

                await ws.send("not json at all")
                err = await h.next_of(ws, "err")
                assert "invalid JSON" in err["reason"]

                # still serving
                assert await h.next_of(ws, "state")

    run(body())


def test_two_clients_get_independent_twins():
    """The premise of publishing this without authentication.

    Each connection owns its own hall, so one visitor tripping a fan wall cannot
    disturb another's session. Before per-session twins this test asserted the
    opposite — that a command propagated to every client — which was the right
    behaviour for a single shared demo and the wrong one for a public URL.
    """
    async def body():
        async with Harness(mode="manual") as h:
            async with h.connect() as a, h.connect() as b:
                await h.next_of(a, "state")
                await h.next_of(b, "state")

                for unit in ("W1", "W2"):
                    await a.send(json.dumps(
                        {"type": "cmd", "cmd": "set_unit", "unit": unit, "on": False}))
                    await h.next_of(a, "ack")

                fa = await h.drain_to_latest(a)
                fb = await h.drain_to_latest(b)
                assert fa["supply"]["W1"]["on"] is False
                assert fa["supply"]["W2"]["on"] is False
                assert fb["supply"]["W1"]["on"] is True, "sessions are not isolated"
                assert fb["supply"]["W2"]["on"] is True

    run(body())


def test_capacity_is_refused_politely():
    async def body():
        async with Harness(mode="manual", max_sessions=2) as h:
            async with h.connect() as a, h.connect() as b:
                await h.next_of(a, "state")
                await h.next_of(b, "state")
                async with h.connect() as c:
                    msg = await h.next_of(c, "err")
                    assert "capacity" in msg["reason"]

    run(body())


def test_healthz_reports_session_count():
    async def body():
        async with Harness(mode="manual") as h:
            status, body_bytes, headers = await h.http("/healthz")
            assert status == 200
            assert headers["Content-Type"] == "application/json"
            first = json.loads(body_bytes)
            assert first["status"] == "ok" and first["sessions"] == 0
            async with h.connect() as ws:
                await h.next_of(ws, "state")
                assert json.loads((await h.http("/healthz"))[1])["sessions"] == 1

    run(body())


def test_static_assets_serve_with_a_real_body():
    """`connection.respond()` fixes Content-Length from its text argument, so
    assigning `.body` afterwards serves an empty file with a 200. These asserts
    exist because that is exactly what happened."""
    async def body():
        async with Harness(mode="manual") as h:
            for path, needle in (("/", b"<!DOCTYPE html>"), ("/app.js", b"THREE")):
                status, payload, headers = await h.http(path)
                assert status == 200
                assert len(payload) > 1000, f"{path} served {len(payload)} bytes"
                assert needle in payload
            manifest = await h.http("/geometry/manifest.json")
            assert manifest[2]["Cache-Control"] == "no-store"

    run(body())


def test_path_traversal_is_refused():
    async def body():
        import urllib.error

        async with Harness(mode="manual") as h:
            for bad in ("/../pyproject.toml", "/../../etc/passwd", "/nope.js"):
                try:
                    await h.http(bad)
                except urllib.error.HTTPError as exc:
                    assert exc.code == 404
                else:
                    raise AssertionError(f"{bad} was served")

    run(body())


def test_speed_is_clamped_not_rejected():
    """A visitor dragging a slider should not get an error, and CPU per session
    scales with speed, so the server clamps."""
    async def body():
        async with Harness(mode="manual", max_speed=30.0) as h:
            async with h.connect() as ws:
                await h.next_of(ws, "state")
                await ws.send(json.dumps({"type": "cmd", "cmd": "set_speed", "x": 900}))
                await h.next_of(ws, "ack")
                assert (await h.drain_to_latest(ws))["speed"] == 30.0

    run(body())


def test_a_burst_of_commands_is_allowed():
    """The token bucket must start full. Starting it empty silently dropped the
    first command of every session, which looked exactly like broken controls —
    and the viewer legitimately bursts (the fan slider sends one per module)."""
    async def body():
        async with Harness(mode="manual") as h:
            async with h.connect() as ws:
                await h.next_of(ws, "state")
                for unit in ("W1", "W2", "E1", "E2"):
                    await ws.send(json.dumps({
                        "type": "cmd", "cmd": "set_unit_airflow",
                        "unit": unit, "fraction": 0.5}))
                for _ in range(4):
                    await h.next_of(ws, "ack")
                frame = await h.drain_to_latest(ws)
                for unit in ("W1", "W2", "E1", "E2"):
                    assert frame["supply"][unit]["airflow_fraction"] == 0.5

    run(body())


def test_the_twin_advances_in_simulated_time():
    async def body():
        async with Harness(mode="auto", speed=20.0) as h:
            async with h.connect() as ws:
                first = await h.next_of(ws, "state")
                later = await h.drain_to_latest(ws, seconds=0.6)
                assert later["t_sim"] > first["t_sim"]
                assert later["speed"] == pytest.approx(20.0)

    run(body())
