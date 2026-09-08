"""Live matplotlib dashboard — the twin, demonstrable before Unreal exists.

This is deliberately a *WebSocket client*, not an in-process view. It exercises
the identical wire protocol Unreal will use, so by the time the engine work
starts the schema has already been proven against a real consumer. If a field is
missing or misnamed, it shows up here first and cheaply.

    dthall run &                 # the service
    dthall debugview             # this

Four panels:
  * per-rack intake temperature against the ASHRAE recommended/allowable bands,
    with the face-peak overlaid — because the mean alone will mislead you
  * IT load and cooling duty over time, with the training-run phase shaded
  * hot aisle / return / supply temperatures over time
  * per-zone gap flow, signed: the sign is the verdict
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging

log = logging.getLogger("dthall.debugview")

HISTORY = 600  # samples retained per trace


class DebugView:
    def __init__(self, url: str = "ws://127.0.0.1:8765"):
        self.url = url
        self.hello: dict | None = None
        self.latest: dict | None = None
        self.hist: dict[str, collections.deque] = {
            k: collections.deque(maxlen=HISTORY)
            for k in (
                "t",
                "it_kw",
                "cooling_kw",
                "storage_kw",
                "hot",
                "ret",
                "sup",
                "worst",
            )
        }

    # -- data ---------------------------------------------------------------
    async def _consume(self) -> None:
        import websockets

        async for ws in websockets.connect(self.url):
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "hello":
                        self.hello = msg
                        log.info(
                            "connected: %s, %d racks, schema v%d",
                            msg["hall"],
                            len(msg["racks"]),
                            msg["schema_v"],
                        )
                    elif msg.get("type") == "state":
                        self._record(msg)
                    elif msg.get("type") == "err":
                        log.warning("server error: %s", msg.get("reason"))
            except Exception as exc:  # noqa: BLE001 - reconnect rather than die
                log.warning("connection lost (%s), retrying", exc)
                await asyncio.sleep(1.0)

    def _record(self, msg: dict) -> None:
        self.latest = msg
        h, t = self.hist, msg["totals"]
        h["t"].append(msg["t_sim"])
        h["it_kw"].append(t["it_kw"])
        h["cooling_kw"].append(t["cooling_kw"])
        h["storage_kw"].append(t["storage_kw"])
        h["hot"].append(msg["hot_aisle"])
        h["ret"].append(msg["return_air"])
        h["sup"].append(
            sum(u["t_supply"] for u in msg["supply"].values()) / len(msg["supply"])
        )
        h["worst"].append(t["worst_t_in"])

    # -- rendering ----------------------------------------------------------
    @staticmethod
    def make_figure():
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(15, 8.5))
        return fig, axes

    def draw(self, fig, axes) -> None:
        """Render the current state into a 2x2 axes grid.

        Separated from the animation loop so the same drawing code can be
        rendered headlessly for a snapshot or a test, rather than only ever
        existing inside a live window.
        """
        import numpy as np

        ax_rack, ax_load, ax_temp, ax_gap = axes.ravel()
        if self.latest is None:
            return
        msg = self.latest
        limits = (self.hello or {}).get(
            "limits", {"allowable_c": 35.0, "recommended_c": 27.0}
        )

        names = list(msg["racks"])
        means = [msg["racks"][n]["t_in"] for n in names]
        peaks = [msg["racks"][n]["t_in_peak"] for n in names]
        kws = [msg["racks"][n]["kw"] for n in names]
        x = np.arange(len(names))

        ax_rack.clear()
        ax_rack.axhspan(
            0, limits["recommended_c"], color="tab:green", alpha=0.08, zorder=0
        )
        ax_rack.axhspan(
            limits["recommended_c"],
            limits["allowable_c"],
            color="tab:orange",
            alpha=0.10,
            zorder=0,
        )
        ax_rack.axhline(
            limits["allowable_c"], color="tab:red", lw=1.2, ls="--",
            label=f"allowable {limits['allowable_c']:.0f} C",
        )
        ax_rack.axhline(
            limits["recommended_c"], color="tab:green", lw=1.0, ls=":",
            label=f"recommended {limits['recommended_c']:.0f} C",
        )
        ax_rack.bar(x, means, color="tab:blue", label="mean intake")
        ax_rack.plot(x, peaks, "v", color="tab:red", ms=5, label="face peak")
        ax_rack.set_xticks(x)
        ax_rack.set_xticklabels(names, rotation=90, fontsize=7)
        ax_rack.set_ylabel("rack intake [degC]")
        ax_rack.set_ylim(
            min(means + [limits["recommended_c"]]) - 3,
            max(peaks + [limits["allowable_c"]]) + 3,
        )
        ax_rack.set_title(
            f"{msg['verdict']}  -  {msg['verdict_reason']}", fontsize=9,
            color={"PASS": "tab:green", "MARGINAL": "tab:orange", "FAIL": "tab:red"}[
                msg["verdict"]
            ],
        )
        ax_rack.legend(fontsize=7, loc="upper left", ncol=2)

        t = np.array(self.hist["t"])
        ax_load.clear()
        ax_load.plot(t, self.hist["it_kw"], label="IT load", color="tab:red")
        ax_load.plot(
            t, self.hist["cooling_kw"], label="cooling duty", color="tab:blue",
            ls="--",
        )
        # The two traces separate whenever the hall is charging or
        # discharging its thermal mass; this is that difference, and it
        # closes the energy books exactly.
        ax_load.fill_between(
            t, 0, self.hist["storage_kw"], color="tab:grey", alpha=0.35,
            label="into thermal mass",
        )
        profile = msg.get("profile")
        phase = f" - {profile['phase']}" if profile else ""
        util = (
            f" (util {profile['mean_utilisation']:.0%}, "
            f"{profile['checkpoints']} ckpt, {profile['evals']} eval)"
            if profile
            else ""
        )
        ax_load.set_title(
            f"mode={msg['mode']}{phase}{util}  speed={msg['speed']:g}x", fontsize=9
        )
        ax_load.set_ylabel("kW")
        ax_load.legend(fontsize=7, loc="lower right")

        ax_temp.clear()
        ax_temp.plot(t, self.hist["hot"], label="hot aisle", color="tab:red")
        ax_temp.plot(t, self.hist["ret"], label="return", color="tab:orange")
        ax_temp.plot(t, self.hist["sup"], label="supply", color="tab:blue")
        ax_temp.plot(
            t, self.hist["worst"], label="worst rack intake", color="k", lw=1
        )
        ax_temp.axhline(limits["allowable_c"], color="tab:red", lw=0.8, ls="--")
        ax_temp.set_ylabel("degC")
        ax_temp.set_xlabel("simulated time [s]")
        ax_temp.legend(fontsize=7, loc="upper left", ncol=2)

        ax_gap.clear()
        zones = list(msg["gap"])
        nets = [msg["gap"][z]["net_m3h"] for z in zones]
        colours = ["tab:red" if n < 0 else "tab:blue" for n in nets]
        ax_gap.barh(zones, nets, color=colours)
        ax_gap.axvline(0, color="k", lw=1)
        ax_gap.set_xlabel("gap flow [m3/h]   <- recirculating | spilling ->")
        ax_gap.set_title(
            "negative = hot air pulled back into the cold aisle", fontsize=8
        )
        for i, z in enumerate(zones):
            ax_gap.text(
                0, i, f"  {msg['zones'][z]:.1f} C  ", va="center", fontsize=7
            )

        fig.tight_layout()

    def run(self) -> int:
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation

        loop = asyncio.new_event_loop()
        task = loop.create_task(self._consume())

        fig, axes = self.make_figure()
        fig.canvas.manager.set_window_title("dthall - AU01 digital twin")

        def tick(_frame):
            # let the websocket task make progress between renders
            loop.call_soon(loop.stop)
            loop.run_forever()
            self.draw(fig, axes)

        self._anim = FuncAnimation(fig, tick, interval=200, cache_frame_data=False)
        try:
            plt.show()
        finally:
            task.cancel()
            loop.close()
        return 0
