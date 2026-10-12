"""Pipe sizes. Same table as `piping.PipeSpec.from_dn`, without FreeCAD."""
from __future__ import annotations

from dataclasses import dataclass, asdict

#: DN -> (OD mm, wall mm) for Sch 10S. Kept identical to piping.py so a route
#: planned here builds to the same solids there.
SCH10S = {
    25: (33.7, 2.77), 32: (42.4, 2.77), 40: (48.3, 2.77), 50: (60.3, 2.77),
    65: (76.1, 2.77), 80: (88.9, 3.05), 100: (114.3, 3.05), 125: (139.7, 3.40),
    150: (168.3, 3.40), 200: (219.1, 3.76), 250: (273.0, 4.19),
    300: (323.9, 4.57), 350: (355.6, 4.78), 400: (406.4, 4.78),
    450: (457.2, 4.78), 500: (508.0, 5.54), 600: (609.6, 5.54),
}

#: Long-radius elbow, ASME B16.9: centreline bend radius = 1.5 x OD.
LONG_RADIUS = 1.5


@dataclass(frozen=True)
class PipeSpec:
    dn: int
    od: float
    wall: float
    bend_radius: float
    schedule: str = "10S"

    @property
    def radius(self) -> float:
        return self.od / 2

    def as_dict(self) -> dict:
        d = asdict(self)
        d["bend_radius"] = round(self.bend_radius, 2)
        return d


def spec_for(dn: int, schedule: str = "10S") -> PipeSpec:
    if schedule != "10S":
        raise ValueError(f"schedule {schedule!r} not held; only 10S is")
    if dn not in SCH10S:
        raise ValueError(f"DN{dn} not held; available: {sorted(SCH10S)}")
    od, wall = SCH10S[dn]
    return PipeSpec(dn=dn, od=od, wall=wall, bend_radius=LONG_RADIUS * od,
                    schedule=schedule)


def list_specs() -> list[dict]:
    return [spec_for(dn).as_dict() for dn in sorted(SCH10S)]
