"""Section 2 of the spec - the selection procedure.

Nine steps, in order, each recorded. The orchestrator's job is to be boring
and auditable: every step names the size it demands and why, and the final
size is the largest demand rather than the first size that happens to pass.

    1  Validate the declaration (TABULATED vs DERATED) and the inputs.
    2  Establish the design current I_b and, under harmonics, which conductor
       governs - phase or neutral.
    3  Check the protective device: I_b <= I_n.
    4  Resolve the installation conditions for every route segment.
    5  Current-carrying capacity: smallest size with I_n <= I_z.
    6  Voltage drop: smallest size within the permitted drop.
    7  Short-circuit withstand: smallest size with k(S) resolved per candidate.
    8  Earth fault: PE size, and loop impedance at the candidate size.
    9  Governing size = max(5..8). Re-run every check at that size and report.

Step 9 is not decoration. A size chosen for voltage drop changes the
short-circuit k if it crosses the Table 5.2 break, and changes the loop
impedance. The final report is generated at the final size, never assembled
from the intermediate passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import current_capacity, earth_fault, short_circuit, voltage_drop
from .errors import MissingTableData, NoCompliantSize, OpenItem
from .schema import (
    base_table,
    Cable,
    CheckResult,
    DeclaredAs,
    Load,
    Protection,
    Route,
)
from .tables.registry import TableStore


@dataclass
class Step:
    number: int
    name: str
    demanded_size_mm2: float | None
    passed: bool
    detail: dict = field(default_factory=dict)
    note: str = ""

    def __str__(self) -> str:
        size = (f"{self.demanded_size_mm2:g} mm2"
                if self.demanded_size_mm2 else "-")
        return (f"  {self.number}. {self.name:<34} "
                f"{'ok  ' if self.passed else 'FAIL'} {size:>10}"
                + (f"   {self.note}" if self.note else ""))


@dataclass
class Selection:
    cable: Cable
    steps: list[Step]
    governing_step: Step | None
    final_size_mm2: float | None
    checks: list[CheckResult] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)

    @property
    def compliant(self) -> bool:
        return (self.final_size_mm2 is not None
                and all(c.passed for c in self.checks)
                and not self.open_items)

    def report(self) -> str:
        lines = ["Conductor selection - AS/NZS 3008.1.1 procedure", ""]
        lines += [str(s) for s in self.steps]
        lines.append("")
        if self.final_size_mm2:
            gov = self.governing_step.name if self.governing_step else "?"
            lines.append(f"  Governing size: {self.final_size_mm2:g} mm2  (set by {gov})")
        else:
            lines.append("  No compliant size found.")
        if self.checks:
            lines.append("")
            lines.append("  Verification at the selected size:")
            lines += [f"    {c}" for c in self.checks]
        if self.open_items:
            lines.append("")
            lines.append("  OPEN ITEMS - resolve before issue:")
            lines += [f"    - {o}" for o in self.open_items]
        return "\n".join(lines)


def _candidate_sizes(store: TableStore, cable: Cable, route: Route) -> list[float]:
    """Sizes available in the CCC table for every segment of the route."""
    sets = []
    for seg in route.segments:
        sets.append(set(store.sizes_available(
            "ccc",
            table=base_table(cable),
            arrangement=seg.method.arrangement,
            material=cable.material,
        )))
    if not sets:
        return []
    common = set.intersection(*sets)
    return sorted(common)


def select(
    store: TableStore,
    cable: Cable,
    route: Route,
    load: Load,
    protection: Protection,
    *,
    declared_as: DeclaredAs = DeclaredAs.TABULATED,
    u0_v: float | None = None,
    disconnection_current_a: float | None = None,
    exact_voltage_drop: bool = False,
    refine_operating_temperature: bool = False,
    candidate_sizes: list[float] | None = None,
) -> Selection:
    steps: list[Step] = []
    open_items: list[str] = []

    # -- 1 ----------------------------------------------------------------
    if declared_as is DeclaredAs.DERATED:
        raise OpenItem(
            "select() works from tabulated capacities. A DERATED declaration "
            "has no size ladder to iterate over."
        )
    uncovered = [
        seg.label or f"segment {i + 1}"
        for i, seg in enumerate(route.segments)
        if not store.sizes_available(
            "ccc",
            table=base_table(cable),
            arrangement=seg.method.arrangement,
            material=cable.material,
        )
    ]
    sizes = candidate_sizes or _candidate_sizes(store, cable, route)
    ok1 = bool(sizes) and not uncovered
    note1 = ""
    if uncovered:
        note1 = ("no CCC rows for the arrangement on: " + ", ".join(uncovered))
    elif not sizes:
        note1 = "no size is common to every segment of the route"
    steps.append(Step(1, "declaration and inputs", None, ok1,
                      {"candidate_sizes": sizes, "uncovered_segments": uncovered},
                      note1))
    if not ok1:
        return Selection(cable, steps, None, None, [],
                         [f"Step 1: {note1}"])

    # -- 2 ----------------------------------------------------------------
    try:
        harmonic = current_capacity.harmonic_treatment(store, load)
        steps.append(Step(2, "design current and basis", None, True, {
            "phase_a": load.design_current_a,
            "neutral_a": harmonic.neutral_a,
            "basis": harmonic.basis.value,
            "governing_a": harmonic.governing_current_a,
            "harmonic_cf": harmonic.cf,
        }, f"{harmonic.basis.value} basis, {harmonic.governing_current_a:.4g} A"))
    except OpenItem as exc:
        steps.append(Step(2, "design current and basis", None, False, {}, str(exc)))
        return Selection(cable, steps, None, None, [], [str(exc)])

    # -- 3 ----------------------------------------------------------------
    ib = harmonic.governing_current_a
    ok3 = ib <= protection.rating_a
    steps.append(Step(3, "I_b <= I_n", None, ok3,
                      {"i_b": ib, "i_n": protection.rating_a},
                      "" if ok3 else "protective device is smaller than the load"))

    # -- 4 ----------------------------------------------------------------
    steps.append(Step(4, "installation conditions", None, True, {
        "segments": [
            {"label": s.label, "length_m": s.length_m,
             "arrangement": s.method.arrangement.value,
             "ambient_c": s.method.ambient_c,
             "circuits": s.method.circuits_in_group}
            for s in route.segments
        ]
    }))

    # -- 5 ----------------------------------------------------------------
    size_ccc = None
    for s in sizes:
        cand = cable.with_size(s)
        try:
            res = current_capacity.capacity(store, cand, route, load, declared_as)
        except MissingTableData:
            continue
        if protection.rating_a <= res.iz_a:
            size_ccc = s
            break
    steps.append(Step(5, "current-carrying capacity", size_ccc, size_ccc is not None,
                      {}, "" if size_ccc else "no size reaches I_n <= I_z"))

    # -- 6 ----------------------------------------------------------------
    size_vd = None
    for s in sizes:
        cand = cable.with_size(s)
        try:
            iz = None
            if refine_operating_temperature:
                iz = current_capacity.capacity(store, cand, route, load, declared_as).iz_a
            vd = voltage_drop.voltage_drop(
                store, cand, route, load, exact=exact_voltage_drop,
                operating_temperature_from_load=refine_operating_temperature,
                iz_a=iz,
            )
        except MissingTableData:
            continue
        if voltage_drop.check_voltage_drop(vd, load).passed:
            size_vd = s
            break
    steps.append(Step(6, "voltage drop", size_vd, size_vd is not None, {},
                      "" if size_vd else "no size meets the permitted drop"))

    # -- 7 ----------------------------------------------------------------
    size_sc = None
    try:
        size_sc = short_circuit.minimum_size(store, cable, protection, sizes)
        mono, _ = short_circuit.withstand_is_monotonic(store, cable, sizes)
        note = "" if mono else "withstand is NOT monotonic across the Table 5.2 break"
    except (NoCompliantSize, MissingTableData, OpenItem) as exc:
        note = str(exc)
    steps.append(Step(7, "short-circuit withstand", size_sc, size_sc is not None,
                      {}, note))

    # -- 8 ----------------------------------------------------------------
    # Two outputs, kept apart. The PE size is a requirement on the earthing
    # conductor and does NOT by itself demand a larger active. The loop
    # impedance check does, because a longer or thinner run raises Z_s, so it
    # is iterated over the active size ladder like steps 5 to 7.
    size_ef = None
    ef_note = ""
    ef_detail: dict = {}
    interim = max([s for s in (size_ccc, size_vd, size_sc) if s], default=sizes[0])

    pe_required = None
    try:
        pe = earth_fault.pe_minimum_size(store, cable.with_size(interim), protection)
        pe_required = min((s for s in sizes if s >= pe.governing_mm2), default=None)
        ef_detail.update({
            "pe_table_minimum_mm2": pe.table_minimum_mm2,
            "pe_adiabatic_minimum_mm2": pe.adiabatic_minimum_mm2,
            "pe_selected_mm2": pe_required,
        })
        if pe_required is None:
            ef_note = (f"PE must be >= {pe.governing_mm2:.3g} mm2, which is "
                       "larger than any available size")
            open_items.append("Step 8: no available size meets the PE minimum")
        else:
            ef_note = f"PE >= {pe.governing_mm2:.3g} mm2 -> {pe_required:g} mm2"
    except (MissingTableData, OpenItem) as exc:
        ef_note = str(exc)
        open_items.append(f"Step 8 PE sizing: {exc}")

    if u0_v is None:
        ef_note += "; loop impedance not assessed (no U_0 supplied)"
    elif pe_required is not None:
        from dataclasses import replace
        for s_active in sizes:
            if s_active < interim:
                continue
            trial = replace(cable.with_size(s_active),
                            pe_size_mm2=max(pe_required, 0.0))
            try:
                res = earth_fault.check(
                    store, trial, route, protection, u0_v=u0_v,
                    disconnection_current_a=disconnection_current_a)
            except (MissingTableData, OpenItem) as exc:
                ef_note += f"; loop impedance not assessed: {exc}"
                open_items.append(f"Step 8 loop impedance: {exc}")
                break
            if res.passed:
                size_ef = s_active
                ef_detail["z_s_ohm"] = res.governing_value
                ef_detail["max_zs_ohm"] = res.limit
                break
        else:
            ef_note += "; no size brings Z_s within the limit"
            open_items.append("Step 8: earth fault loop impedance not satisfied "
                              "at any available size")

    steps.append(Step(8, "earth fault", size_ef,
                      not any(o.startswith("Step 8") for o in open_items),
                      ef_detail, ef_note))

    # -- 9 ----------------------------------------------------------------
    demanded = [s for s in (size_ccc, size_vd, size_sc, size_ef) if s]
    if not demanded:
        steps.append(Step(9, "governing size", None, False, {},
                          "no step produced a viable size"))
        return Selection(cable, steps, None, None, [], open_items)

    final = max(demanded)
    governing = next(st for st in steps
                     if st.demanded_size_mm2 == final and st.number in (5, 6, 7, 8))
    final_cable = cable.with_size(final)
    if pe_required is not None:
        from dataclasses import replace as _replace
        final_cable = _replace(final_cable, pe_size_mm2=pe_required)

    checks: list[CheckResult] = []
    cap = None
    try:
        cap = current_capacity.capacity(store, final_cable, route, load, declared_as)
        checks += current_capacity.check_capacity(cap, load, protection)
    except (MissingTableData, OpenItem) as exc:
        open_items.append(f"capacity at final size: {exc}")
    try:
        vd = voltage_drop.voltage_drop(
            store, final_cable, route, load, exact=exact_voltage_drop,
            operating_temperature_from_load=refine_operating_temperature,
            iz_a=cap.iz_a if (refine_operating_temperature and cap) else None,
        )
        checks.append(voltage_drop.check_voltage_drop(vd, load))
    except (MissingTableData, OpenItem) as exc:
        open_items.append(f"voltage drop at final size: {exc}")
    try:
        checks.append(short_circuit.check(store, final_cable, protection))
    except (MissingTableData, OpenItem) as exc:
        open_items.append(f"short circuit at final size: {exc}")
    if u0_v is not None and final_cable.pe_size_mm2 is not None:
        try:
            checks.append(earth_fault.check(
                store, final_cable, route, protection, u0_v=u0_v,
                disconnection_current_a=disconnection_current_a))
        except (MissingTableData, OpenItem) as exc:
            open_items.append(f"earth fault loop at final size: {exc}")

    steps.append(Step(9, "governing size", final,
                      bool(checks) and all(c.passed for c in checks)
                      and not open_items,
                      {}, f"set by step {governing.number}" + ("; open items outstanding" if open_items else "")))

    return Selection(final_cable, steps, governing, final, checks, open_items)
