"""Section 4 of the spec - I_z, the derated current-carrying capacity.

    I_z = I_t * product(rating factors) * parallel_sets

and the circuit is acceptable on capacity when I_b <= I_n <= I_z.

Two rules that are easy to get wrong and are enforced here:

  * Along a route, capacity is set by the WORST segment. A cable is a series
    element; its hottest metre limits the whole run. Voltage drop accumulates,
    capacity does not.

  * With cables in parallel, the total capacity is n * I_z_each, but each set
    is a separate circuit for grouping purposes. This module does not infer
    that for you - it checks that InstallationMethod.circuits_in_group is at
    least parallel_sets and refuses the calculation otherwise, because
    silently getting grouping wrong is the classic way a parallel run ends up
    undersized.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import InvalidDeclaration
from .rating_factors import (
    FactorSet,
    HarmonicBasis,
    HarmonicOutcome,
    build_factor_set,
    harmonic_treatment,
)
from .schema import (
    arrangements_for,
    base_table,
    InvalidInstallation,
    Cable,
    CheckResult,
    DeclaredAs,
    InstallationMethod,
    Load,
    Protection,
    Route,
    RouteSegment,
)
from .tables.registry import TableStore


@dataclass
class SegmentCapacity:
    segment: RouteSegment
    tabulated_a: float
    factors: FactorSet
    capacity_a: float

    def __str__(self) -> str:
        tag = self.segment.label or "segment"
        return (f"{tag}: I_t={self.tabulated_a:.4g} A x {self.factors.product:.4g} "
                f"= {self.capacity_a:.4g} A  [{self.factors}]")


@dataclass
class CapacityResult:
    cable: Cable
    per_segment: list[SegmentCapacity]
    governing: SegmentCapacity
    harmonic: HarmonicOutcome
    iz_a: float
    parallel_sets: int
    detail: dict = field(default_factory=dict)


def tabulated_capacity(store: TableStore, cable: Cable,
                       method: InstallationMethod) -> float:
    """I_t from the base table, at that table's reference conditions.

    The table is resolved from the cable by R-TBL-1, not passed in, so
    insulation and construction cannot disagree with it. The arrangement must
    be one the table family actually tabulates: a request for
    `air_spaced_from_surface` against a multicore table raises rather than
    silently resolving to `air_touching` (R-ARR-1).
    """
    table = base_table(cable)
    if method.arrangement not in arrangements_for(cable):
        raise InvalidInstallation(
            f"arrangement {method.arrangement.value!r} is not tabulated for "
            f"{cable.construction.value} cables (Table {table}). "
            f"Tabulated here: {sorted(a.value for a in arrangements_for(cable))}. "
            f"It does not fall back to a neighbouring column (R-ARR-1)."
        )
    return store.value(
        "ccc",
        table=table,
        arrangement=method.arrangement,
        material=cable.material,
        size_mm2=cable.size_mm2,
    )


def capacity(
    store: TableStore,
    cable: Cable,
    route: Route,
    load: Load,
    declared_as: DeclaredAs = DeclaredAs.TABULATED,
) -> CapacityResult:
    """Compute I_z for a cable over a whole route."""
    if declared_as is DeclaredAs.DERATED:
        raise InvalidDeclaration(
            "capacity() derives I_z from tabulated data. To use a supplied "
            "DERATED figure, pass it straight to the compliance check instead."
        )

    harmonic = harmonic_treatment(store, load)

    per_segment: list[SegmentCapacity] = []
    for seg in route.segments:
        if cable.parallel_sets > 1 and seg.method.circuits_in_group < cable.parallel_sets:
            raise InvalidDeclaration(
                f"{cable.parallel_sets} parallel sets were declared but segment "
                f"{seg.label or '?'} reports only {seg.method.circuits_in_group} "
                "circuits in the group. Each parallel set is its own circuit for "
                "grouping; set circuits_in_group accordingly."
            )
        it = tabulated_capacity(store, cable, seg.method)
        fs = build_factor_set(store, cable, seg.method, declared_as)
        per_segment.append(
            SegmentCapacity(segment=seg, tabulated_a=it, factors=fs,
                            capacity_a=it * fs.product)
        )

    governing = min(per_segment, key=lambda s: s.capacity_a)

    # The harmonic factor sits outside the FactorSet product (convention C5):
    # on a phase basis it derates the capacity; on a neutral basis it converts
    # a three-loaded-conductor rating into a four-loaded-conductor rating that
    # is then compared against the neutral current.
    iz = governing.capacity_a * harmonic.cf * cable.parallel_sets

    return CapacityResult(
        cable=cable,
        per_segment=per_segment,
        governing=governing,
        harmonic=harmonic,
        iz_a=iz,
        parallel_sets=cable.parallel_sets,
        detail={
            "governing_segment": governing.segment.label,
            "harmonic_basis": harmonic.basis.value,
        },
    )


def check_capacity(result: CapacityResult, load: Load,
                   protection: Protection) -> list[CheckResult]:
    """The I_b <= I_n <= I_z chain, plus the 1.45 overload rule.

    Note which current is compared: under a neutral-basis harmonic outcome the
    comparison is against the neutral current, not the phase current.
    """
    ib = result.harmonic.governing_current_a
    basis = result.harmonic.basis.value

    checks = [
        CheckResult(
            name=f"I_b <= I_n ({basis} basis)",
            passed=ib <= protection.rating_a,
            governing_value=ib,
            limit=protection.rating_a,
            units="A",
            detail={"basis": basis,
                    "phase_a": load.design_current_a,
                    "neutral_a": result.harmonic.neutral_a},
        ),
        CheckResult(
            name="I_n <= I_z",
            passed=protection.rating_a <= result.iz_a,
            governing_value=protection.rating_a,
            limit=result.iz_a,
            units="A",
            detail={"factors": result.governing.factors.as_dict(),
                    "harmonic_cf": result.harmonic.cf,
                    "governing_segment": result.governing.segment.label},
        ),
    ]

    if protection.fusing_current_a is not None:
        checks.append(CheckResult(
            name="I_2 <= 1.45 I_z (overload)",
            passed=protection.fusing_current_a <= 1.45 * result.iz_a,
            governing_value=protection.fusing_current_a,
            limit=1.45 * result.iz_a,
            units="A",
        ))
    return checks
