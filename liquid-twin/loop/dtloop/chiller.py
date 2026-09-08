"""Free-cooling chillers, and the ambient at which they stop being dry coolers.

RD110's heat rejection is four Uniflair XRAF4242A **EHT free-cooling** chillers.
The name matters: below a crossover ambient the unit is a dry cooler - fans only,
no compressors, and a power draw a factor of ten below rated - and above it the
compressors engage to make up whatever the air cannot take. It is one machine
with two operating regimes, not a choice between two machines.

That resolves a framing error in the first pass at SPEC.md section 7.1. The
arithmetic there - "a dry cooler cannot make water colder than the air, so
holding 37 C constrains ambient to 37 minus the approach" - is not an argument
against dry coolers. It is the **free-cooling mode boundary of the chillers
RD110 already specifies**. Below it the plant runs on fan power; above it, on
compressors. Nothing is ruled out; what changes is the electricity bill and
where the design's attention belongs.

## The three regimes

Free-cooling capacity comes from the temperature difference between the return
water and the ambient air across the free-cooling coil:

    Q_free = UA_free * (T_return - T_ambient)        [kW]

with three consequences, in ambient order:

  * **free** - `Q_free >= load`. Compressors off. Fan power only.
  * **mixed** - `0 < Q_free < load`. The coil pre-cools the return water and the
    compressors carry the remainder. This is the band that matters most,
    because a plant spends most of a temperate year in it and the marginal
    saving per degree is largest here.
  * **mechanical** - `T_ambient >= T_return`. The coil can do nothing (air
    hotter than the water it would cool) and the compressors carry the lot.

The crossover between the first two is the number to design around:

    T_crossover = T_return - load / UA_free

which falls as load rises - a fully loaded plant loses free cooling at a *lower*
ambient than a half-loaded one. That is the opposite of the intuition that a
lightly loaded plant is the one at risk, and it is why `crossover_ambient_c`
takes the load as an argument rather than being a constant.

## Confidence

`UA_free`, the fan power fraction and the compressor COP curve are **engineering
judgement (grade L)**, not RD110 figures - RD110 gives capacity at two reference
climates and nothing about part load. The structure here is right and the
constants are placeholders; `loop_params.json` marks them so. What is worth
trusting before a vendor selection arrives is the *shape*: which regime the plant
is in, and which direction each lever moves it.
"""

from __future__ import annotations

from dataclasses import dataclass

MODE_FREE = "free"
MODE_MIXED = "mixed"
MODE_MECHANICAL = "mechanical"
MODE_OFF = "off"

MODES = (MODE_OFF, MODE_FREE, MODE_MIXED, MODE_MECHANICAL)


@dataclass
class FreeCoolingChiller:
    """One free-cooling chiller.

    `ua_free_kw_per_k` is the free-cooling coil's capacity per kelvin of
    (return water - ambient). Rather than being guessed directly it is derived
    from the ambient at which the unit achieves full free cooling at rated
    capacity - a single number a vendor will quote, and the one an engineer
    reviewing this will want to change first. See `from_full_free_cooling_at`.
    """

    name: str
    rated_kw: float
    ua_free_kw_per_k: float
    fan_kw_full: float
    cop_ref: float = 6.0           # at cop_ref_ambient_c, making 37 C water
    cop_ref_ambient_c: float = 25.0
    cop_per_k: float = -0.11       # COP falls as ambient rises
    cop_floor: float = 2.0

    @classmethod
    def from_full_free_cooling_at(
        cls,
        name: str,
        rated_kw: float,
        full_free_ambient_c: float,
        return_water_c: float,
        fan_kw_full: float | None = None,
        **kw,
    ) -> "FreeCoolingChiller":
        """Size the coil from the ambient at which it carries the rated load alone.

        `UA = rated / (T_return - T_full_free)`. If a vendor says the unit free
        cools fully at 20 C with 47 C return water, the coil is worth
        rated/27 kW per kelvin, and everything else follows.
        """
        span = return_water_c - full_free_ambient_c
        if span <= 0:
            raise ValueError(
                "full free cooling must occur below the return water temperature; "
                f"got {full_free_ambient_c} C against {return_water_c} C return"
            )
        return cls(
            name=name,
            rated_kw=rated_kw,
            ua_free_kw_per_k=rated_kw / span,
            fan_kw_full=rated_kw * 0.035 if fan_kw_full is None else fan_kw_full,
            **kw,
        )

    # -- capacity ---------------------------------------------------------

    def free_cooling_kw(self, ambient_c: float, return_water_c: float) -> float:
        """What the coil can take at this ambient. Never negative."""
        return max(0.0, self.ua_free_kw_per_k * (return_water_c - ambient_c))

    def crossover_ambient_c(self, load_kw: float, return_water_c: float) -> float:
        """Ambient at which the compressors first have to start.

        Falls as load rises: a fully loaded plant loses free cooling sooner than
        a lightly loaded one.
        """
        return return_water_c - load_kw / self.ua_free_kw_per_k

    def mode(self, ambient_c: float, load_kw: float, return_water_c: float) -> str:
        if load_kw <= 0:
            return MODE_OFF
        if ambient_c >= return_water_c:
            return MODE_MECHANICAL
        return MODE_FREE if self.free_cooling_kw(ambient_c, return_water_c) >= load_kw else MODE_MIXED

    def free_fraction(self, ambient_c: float, load_kw: float, return_water_c: float) -> float:
        """Share of the load the coil carries, 0 to 1."""
        if load_kw <= 0:
            return 0.0
        return min(1.0, self.free_cooling_kw(ambient_c, return_water_c) / load_kw)

    # -- power ------------------------------------------------------------

    def cop(self, ambient_c: float) -> float:
        """Compressor COP, declining with ambient. Grade L - see the module docstring."""
        return max(self.cop_floor, self.cop_ref + self.cop_per_k * (ambient_c - self.cop_ref_ambient_c))

    def power_kw(self, ambient_c: float, load_kw: float, return_water_c: float) -> dict:
        """Fan and compressor power, and the mode that produced them.

        Fans run at full speed whenever the unit is on. Head-pressure control
        does modulate them in reality, and modelling that would lower the free
        cooling figures a little; it is left out until there is vendor part-load
        data to model it against, and flagged here rather than buried.
        """
        mode = self.mode(ambient_c, load_kw, return_water_c)
        if mode == MODE_OFF:
            return {"mode": mode, "fans_kw": 0.0, "compressors_kw": 0.0,
                    "total_kw": 0.0, "free_fraction": 0.0, "cop": 0.0}

        free = self.free_cooling_kw(ambient_c, return_water_c)
        mechanical_kw = max(0.0, load_kw - free)
        cop = self.cop(ambient_c)
        compressors = mechanical_kw / cop
        fans = self.fan_kw_full
        return {
            "mode": mode,
            "fans_kw": fans,
            "compressors_kw": compressors,
            "total_kw": fans + compressors,
            "free_fraction": min(1.0, free / load_kw),
            "cop": cop,
        }


@dataclass
class ChillerPlant:
    """N+1 free-cooling chillers sharing a load.

    Load is split evenly across the running units, which is what a plant
    controller with equal sequencing does and is the case worth modelling first.
    Staging - running fewer units harder to keep them out of poor part-load
    efficiency, or more units softer to gain free cooling coil area - is a real
    lever and a later question.
    """

    units: list[FreeCoolingChiller]
    standby: int = 1

    @property
    def running(self) -> int:
        return max(1, len(self.units) - self.standby)

    @property
    def capacity_kw(self) -> float:
        return sum(u.rated_kw for u in self.units[: self.running])

    def power_kw(self, ambient_c: float, load_kw: float, return_water_c: float) -> dict:
        per_unit = load_kw / self.running
        results = [u.power_kw(ambient_c, per_unit, return_water_c) for u in self.units[: self.running]]
        total = sum(r["total_kw"] for r in results)
        modes = {r["mode"] for r in results}
        return {
            "mode": modes.pop() if len(modes) == 1 else "mixed",
            "fans_kw": sum(r["fans_kw"] for r in results),
            "compressors_kw": sum(r["compressors_kw"] for r in results),
            "total_kw": total,
            "free_fraction": sum(r["free_fraction"] for r in results) / len(results),
            "cop_effective": load_kw / total if total > 0 else 0.0,
            "units_running": self.running,
        }

    def crossover_ambient_c(self, load_kw: float, return_water_c: float) -> float:
        return self.units[0].crossover_ambient_c(load_kw / self.running, return_water_c)

    def capability_sweep(self, return_water_c: float, lo: float = -10.0,
                         hi: float = 48.0, step: float = 0.5) -> list[dict]:
        """Per-ambient coil capability and COP, with no load in it.

        The load-independent half of the model, so a caller can vary load
        without re-solving anything:

            compressors_kw = max(0, load - q_free_kw) / cop
            mode           = free if q_free >= load else
                             mechanical if q_free <= 0 else mixed

        Both lines are definitional - an energy balance and the mode boundaries
        this module states - rather than a second implementation of the physics.
        UA sizing, the COP curve and the fan power stay here, which is what
        keeps the browser a lookup rather than a fork.
        """
        out = []
        t = lo
        while t <= hi + 1e-9:
            out.append({
                "ambient_c": round(t, 2),
                "q_free_kw": round(sum(u.free_cooling_kw(t, return_water_c)
                                       for u in self.units[: self.running]), 2),
                "cop": round(self.units[0].cop(t), 3),
                "fans_kw": round(sum(u.fan_kw_full for u in self.units[: self.running]), 2),
            })
            t += step
        return out

    def sweep(self, load_kw: float, return_water_c: float,
              lo: float = -10.0, hi: float = 45.0, step: float = 0.5) -> list[dict]:
        """Power against ambient, for the viewer and for annual-hours work.

        Returned as a table rather than computed in the browser so there is one
        implementation of the physics and JavaScript only looks things up.
        """
        out = []
        t = lo
        while t <= hi + 1e-9:
            row = self.power_kw(t, load_kw, return_water_c)
            row["ambient_c"] = round(t, 2)
            out.append(row)
            t += step
        return out


def rd110_plant(full_free_ambient_c: float = 20.0) -> ChillerPlant:
    """RD110's four HT chillers, at its Paris capacity.

    2075 kW per unit is RD110's Paris figure (2386 kW at Singapore); N+1 of four
    means three run. `full_free_ambient_c` is the free argument and the one to
    revisit first - it is judgement, not RD110.
    """
    return ChillerPlant(
        units=[
            FreeCoolingChiller.from_full_free_cooling_at(
                name=f"HT_CH-{i + 1}",
                rated_kw=2075.0,
                full_free_ambient_c=full_free_ambient_c,
                return_water_c=47.0,
            )
            for i in range(4)
        ],
        standby=1,
    )
