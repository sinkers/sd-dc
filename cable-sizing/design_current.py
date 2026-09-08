"""
Design current (I_b) determination for LV cable sizing.

Implements Section 3 of the LV Cable Sizing Methodology, Rev B.
Scope: LV AC to 1000 V, three-phase four-wire and single-phase, plus DC.

All public functions return a Result carrying the value, the governing
quantity, and the provenance of every intermediate so the derivation is
auditable downstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

SQRT3 = math.sqrt(3.0)


class SystemType(str, Enum):
    THREE_PHASE = "3ph"          # line-to-line voltage, 3 or 4 wire
    SINGLE_PHASE_LN = "1ph_ln"   # line to neutral
    SINGLE_PHASE_LL = "1ph_ll"   # line to line, two poles of a 3ph system
    DC = "dc"


class LoadKind(str, Enum):
    GENERAL = "general"
    MOTOR = "motor"              # nameplate is shaft output power
    UPS_INPUT = "ups_input"
    TRANSFORMER = "transformer"
    RESISTIVE = "resistive"


class DeclaredAs(str, Enum):
    KW_OUTPUT = "kw_output"      # shaft or useful output; efficiency applies
    KW_INPUT = "kw_input"        # real power drawn; efficiency does NOT apply
    KVA_INPUT = "kva_input"      # apparent power drawn; pf and eta do NOT apply
    AMPS = "amps"                # nameplate full load current; used directly


class DesignCurrentError(ValueError):
    """Raised when a load declaration is internally inconsistent."""


# ---------------------------------------------------------------------------
# Power factor
# ---------------------------------------------------------------------------

def distortion_factor(thd_i: float) -> float:
    """Ratio of fundamental RMS current to total RMS current.

    thd_i is total harmonic distortion of current as a fraction (0.30 = 30 %).
    """
    if thd_i < 0:
        raise DesignCurrentError("thd_i must be >= 0")
    return 1.0 / math.sqrt(1.0 + thd_i ** 2)


def true_power_factor(displacement_pf: float, thd_i: float = 0.0) -> float:
    """True power factor lambda = cos(phi_1) * distortion factor.

    Current magnitude is governed by true power factor, because the conductor
    carries harmonic current as well as fundamental. Voltage drop is governed by
    displacement power factor. The two are not interchangeable.
    """
    if not 0.0 < displacement_pf <= 1.0:
        raise DesignCurrentError("displacement_pf must be in (0, 1]")
    return displacement_pf * distortion_factor(thd_i)


# ---------------------------------------------------------------------------
# Neutral current
# ---------------------------------------------------------------------------

def triplen_neutral_current(fundamental_phase_a: float,
                            spectrum: Mapping[int, float]) -> float:
    """Neutral current from triplen harmonics in a balanced three-phase circuit.

    Triplen harmonics (h = 3, 9, 15, ...) are co-phasal across the three phases
    and add arithmetically in the neutral; the neutral carries three times the
    per-phase triplen current.

    spectrum maps harmonic order to magnitude as a fraction of the fundamental.
    Non-triplen orders are ignored here; they cancel in the neutral when balanced.
    """
    triplens = [v for h, v in spectrum.items() if h % 3 == 0 and h % 2 == 1]
    if not triplens:
        return 0.0
    rss = math.sqrt(sum(v ** 2 for v in triplens))
    return 3.0 * rss * fundamental_phase_a


def unbalance_neutral_current(ia: float, ib: float, ic: float) -> float:
    """Fundamental neutral current from phase unbalance, phases at 120 deg.

    Returns the magnitude of the vector sum of three phase currents assumed to be
    at their nominal phase angles. Load-specific angle data, where available,
    supersedes this.
    """
    re = ia + ib * math.cos(math.radians(-120.0)) + ic * math.cos(math.radians(120.0))
    im = ib * math.sin(math.radians(-120.0)) + ic * math.sin(math.radians(120.0))
    return math.hypot(re, im)


def neutral_current(phase_currents: tuple[float, float, float],
                    spectrum: Mapping[int, float] | None = None) -> float:
    """Total neutral current, combining unbalance and triplen contributions.

    The two contributions are at different frequencies and combine in RSS.
    """
    spectrum = spectrum or {}
    ia, ib, ic = phase_currents
    i_unbal = unbalance_neutral_current(ia, ib, ic)
    i_fund_mean = sum(phase_currents) / 3.0
    # phase current supplied is total RMS; recover fundamental before scaling
    thd = math.sqrt(sum(v ** 2 for v in spectrum.values())) if spectrum else 0.0
    i_fund = i_fund_mean / math.sqrt(1.0 + thd ** 2)
    i_trip = triplen_neutral_current(i_fund, spectrum)
    return math.hypot(i_unbal, i_trip)


def neutral_to_phase_ratio(h3: float) -> float:
    """Neutral to phase current ratio for a balanced load with third harmonic only.

    Crosses unity at h3 = 1/sqrt(8) = 0.354, above which the neutral is the
    governing conductor.
    """
    return (3.0 * h3) / math.sqrt(1.0 + h3 ** 2)


NEUTRAL_GOVERNS_THRESHOLD = 1.0 / math.sqrt(8.0)  # 0.3536


# ---------------------------------------------------------------------------
# Design current
# ---------------------------------------------------------------------------

@dataclass
class Load:
    """A single declared load."""
    tag: str
    system: SystemType
    voltage_v: float                 # line-to-line for 3ph and 1ph_ll; L-N for 1ph_ln
    declared_as: DeclaredAs
    value: float                     # kW, kVA or A per declared_as
    kind: LoadKind = LoadKind.GENERAL
    displacement_pf: float = 1.0
    thd_i: float = 0.0
    efficiency: float = 1.0
    spectrum: Mapping[int, float] = field(default_factory=dict)
    diversity: float = 1.0           # applied at the parent board, not here
    # UPS only
    ups_recharge_fraction: float = 0.0

    def __post_init__(self) -> None:
        if self.voltage_v <= 0:
            raise DesignCurrentError(f"{self.tag}: voltage must be positive")
        if self.value < 0:
            raise DesignCurrentError(f"{self.tag}: value must be non-negative")
        if not 0.0 < self.efficiency <= 1.0:
            raise DesignCurrentError(f"{self.tag}: efficiency must be in (0, 1]")
        if self.declared_as is DeclaredAs.KVA_INPUT and self.displacement_pf != 1.0:
            # kVA already contains the power factor; applying it again halves nothing
            # but silently understates current if the user also set pf.
            raise DesignCurrentError(
                f"{self.tag}: do not set displacement_pf when declaring kVA input")
        if self.declared_as is DeclaredAs.KW_OUTPUT and self.efficiency == 1.0 \
                and self.kind is LoadKind.MOTOR:
            raise DesignCurrentError(
                f"{self.tag}: motor declared as output power requires efficiency")
        if self.spectrum and self.thd_i == 0.0:
            self.thd_i = math.sqrt(sum(v ** 2 for v in self.spectrum.values()))


@dataclass
class DesignCurrentResult:
    tag: str
    i_b: float                      # A, governing conductor
    i_phase: float                  # A
    i_neutral: float                # A
    governing_conductor: str        # "phase" or "neutral"
    apparent_power_kva: float
    true_pf: float
    notes: list[str] = field(default_factory=list)


def _voltage_divisor(system: SystemType, voltage_v: float) -> float:
    if system is SystemType.THREE_PHASE:
        return SQRT3 * voltage_v
    if system in (SystemType.SINGLE_PHASE_LN, SystemType.SINGLE_PHASE_LL,
                  SystemType.DC):
        return voltage_v
    raise DesignCurrentError(f"unhandled system type {system}")


def design_current(load: Load) -> DesignCurrentResult:
    """Compute design current for a single load.

    Returns phase current, neutral current, and the governing value I_b.
    """
    notes: list[str] = []
    lam = true_power_factor(load.displacement_pf, load.thd_i)

    if load.declared_as is DeclaredAs.AMPS:
        i_phase = load.value
        s_kva = i_phase * _voltage_divisor(load.system, load.voltage_v) / 1000.0
        notes.append("nameplate current used directly; pf and efficiency ignored")

    elif load.declared_as is DeclaredAs.KVA_INPUT:
        s_kva = load.value
        i_phase = s_kva * 1000.0 / _voltage_divisor(load.system, load.voltage_v)

    else:
        p_kw = load.value
        if load.declared_as is DeclaredAs.KW_OUTPUT:
            p_kw = p_kw / load.efficiency
            notes.append(f"input power from output / eta = {load.efficiency}")
        if load.kind is LoadKind.UPS_INPUT and load.ups_recharge_fraction:
            p_kw *= (1.0 + load.ups_recharge_fraction)
            notes.append(
                f"battery recharge allowance {load.ups_recharge_fraction:.0%}")
        if load.system is SystemType.DC:
            s_kva = p_kw
            i_phase = p_kw * 1000.0 / load.voltage_v
        else:
            s_kva = p_kw / lam
            i_phase = s_kva * 1000.0 / _voltage_divisor(load.system, load.voltage_v)

    if load.system is SystemType.THREE_PHASE:
        i_neutral = neutral_current((i_phase, i_phase, i_phase), load.spectrum)
    elif load.system is SystemType.SINGLE_PHASE_LN:
        i_neutral = i_phase
    else:
        i_neutral = 0.0

    if i_neutral > i_phase:
        governing = "neutral"
        i_b = i_neutral
        notes.append("neutral current exceeds phase current; neutral governs sizing")
    else:
        governing = "phase"
        i_b = i_phase

    return DesignCurrentResult(
        tag=load.tag,
        i_b=i_b,
        i_phase=i_phase,
        i_neutral=i_neutral,
        governing_conductor=governing,
        apparent_power_kva=s_kva,
        true_pf=lam,
        notes=notes,
    )


def board_design_current(loads: list[Load],
                         board_diversity: float = 1.0) -> DesignCurrentResult:
    """Aggregate design current at a distribution board.

    Per-load diversity is applied to each load, then the board diversity to the
    sum. Currents are summed arithmetically, which is conservative where power
    factors differ. Where phase angle data is available for every load a phasor
    sum is the more accurate treatment and is not implemented here.
    """
    if not loads:
        raise DesignCurrentError("no loads supplied")
    systems = {load.system for load in loads}
    if len(systems) > 1:
        raise DesignCurrentError("mixed system types must be resolved before summing")
    voltages = {load.voltage_v for load in loads}
    if len(voltages) > 1:
        raise DesignCurrentError("mixed voltages must be resolved before summing")

    i_phase = sum(design_current(l).i_phase * l.diversity for l in loads)
    i_neutral = sum(design_current(l).i_neutral * l.diversity for l in loads)
    i_phase *= board_diversity
    i_neutral *= board_diversity
    s_kva = sum(design_current(l).apparent_power_kva * l.diversity
                for l in loads) * board_diversity

    governing = "neutral" if i_neutral > i_phase else "phase"
    return DesignCurrentResult(
        tag="board",
        i_b=max(i_phase, i_neutral),
        i_phase=i_phase,
        i_neutral=i_neutral,
        governing_conductor=governing,
        apparent_power_kva=s_kva,
        true_pf=float("nan"),
        notes=[f"arithmetic sum of {len(loads)} loads",
               f"board diversity {board_diversity}"],
    )
