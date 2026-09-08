"""Section 7 of the spec - earth fault protection.

Three separate obligations, often conflated and kept apart here:

  (1) SIZE. The protective earthing conductor must be no smaller than
      AS/NZS 3000 Table 5.1 for the associated active size.
  (2) ENERGY. It must also survive the earth fault adiabatically, on the same
      k basis as Section 6 but with the PE's own initial temperature.
  (3) IMPEDANCE. The earth fault loop impedance must be low enough that the
      protective device disconnects within the required time.

The governing PE size is the largest of (1) and (2). Satisfying one and
assuming the other is the classic omission.

Loop impedance
--------------
    Z_s = Z_external + Z_circuit
    Z_circuit = L/1000 * sqrt( (R_phase + R_pe)^2 + (X_phase + X_pe)^2 )

Conductor temperature during the fault matters: resistance rises with
temperature and a loop computed at 20 C is optimistic. The temperature used
is explicit and defaults to the insulation's maximum continuous rating, which
is the conservative choice. AS/NZS 3000 states the basis to be used for
verification; where that basis differs from this default, pass it in rather
than leaving the module to guess.

Acceptance is by whichever of these is available, in order:
  a) the tabulated maximum Z_s for the device (max_zs.csv), or
  b) Z_s <= U_0 / I_a, where I_a is the current causing disconnection within
     the required time and must be supplied by the caller from the device
     curve. There is no default I_a; a wrong one is worse than a stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from .errors import MissingTableData, OpenItem
from .schema import (
    Cable,
    CheckResult,
    ConductorMaterial,
    Insulation,
    Protection,
    Route,
)
from .short_circuit import fault_energy_a2s, k_factor, limits_for
from .tables.registry import TableStore
from .voltage_drop import reactance, resistance_at


@dataclass
class PeSizing:
    table_minimum_mm2: float
    adiabatic_minimum_mm2: float
    governing_mm2: float
    k: float
    detail: dict


def pe_minimum_size(
    store: TableStore,
    cable: Cable,
    protection: Protection,
    pe_material: ConductorMaterial | None = None,
    pe_insulation: Insulation | None = None,
) -> PeSizing:
    """Governing minimum protective earthing conductor size."""
    material = pe_material or cable.pe_material or cable.material
    insulation = pe_insulation or cable.insulation

    table_min = store.value(
        "pe_min_size", material=material, active_size_mm2=cable.size_mm2
    )

    lim = limits_for(store, insulation, cable.size_mm2)
    k = k_factor(material, lim.initial_c, lim.final_c)
    adiabatic_min = sqrt(fault_energy_a2s(protection)) / k

    return PeSizing(
        table_minimum_mm2=table_min,
        adiabatic_minimum_mm2=adiabatic_min,
        governing_mm2=max(table_min, adiabatic_min),
        k=k,
        detail={
            "table": "AS/NZS 3000 Table 5.1",
            "pe_material": material.value,
            "initial_temperature_c": lim.initial_c,
            "final_temperature_c": lim.final_c,
        },
    )


def loop_impedance_ohm(
    store: TableStore,
    cable: Cable,
    route: Route,
    protection: Protection,
    *,
    loop_temperature_c: float | None = None,
) -> dict:
    """Earth fault loop impedance for the circuit, external impedance included."""
    if cable.pe_size_mm2 is None:
        raise OpenItem(
            "Earth fault loop impedance requires a protective earthing "
            "conductor size. Cable.pe_size_mm2 is unset; size the PE first "
            "with pe_minimum_size()."
        )

    theta = loop_temperature_c
    if theta is None:
        theta = cable.insulation.max_continuous_c

    pe_cable = cable.with_size(cable.pe_size_mm2)
    if cable.pe_material is not None:
        from dataclasses import replace
        pe_cable = replace(pe_cable, material=cable.pe_material)

    r_ph = resistance_at(store, cable, theta) / cable.parallel_sets
    r_pe = resistance_at(store, pe_cable, theta)
    x_ph = reactance(store, cable) / cable.parallel_sets
    try:
        x_pe = reactance(store, pe_cable)
    except MissingTableData:
        x_pe = x_ph          # same construction; acceptable and noted below

    length_km = route.total_length_m / 1000.0
    z_circuit = length_km * sqrt((r_ph + r_pe) ** 2 + (x_ph + x_pe) ** 2)
    return {
        "z_circuit_ohm": z_circuit,
        "z_external_ohm": protection.external_loop_impedance_ohm,
        "z_s_ohm": z_circuit + protection.external_loop_impedance_ohm,
        "r_phase_ohm_per_km": r_ph,
        "r_pe_ohm_per_km": r_pe,
        "x_phase_ohm_per_km": x_ph,
        "x_pe_ohm_per_km": x_pe,
        "conductor_temperature_c": theta,
        "route_length_m": route.total_length_m,
    }


def check(
    store: TableStore,
    cable: Cable,
    route: Route,
    protection: Protection,
    *,
    u0_v: float,
    disconnection_current_a: float | None = None,
    loop_temperature_c: float | None = None,
) -> CheckResult:
    """Verify disconnection within the required time."""
    loop = loop_impedance_ohm(
        store, cable, route, protection, loop_temperature_c=loop_temperature_c
    )
    z_s = loop["z_s_ohm"]

    try:
        limit = store.value(
            "max_zs",
            device=protection.device,
            rating_a=protection.rating_a,
            disconnection_time_s=protection.max_disconnection_time_s,
        )
        basis = "AS/NZS 3000 maximum Z_s table"
    except MissingTableData as exc:
        if disconnection_current_a is None:
            raise OpenItem(
                "Neither a tabulated maximum Z_s nor a disconnection current "
                "I_a is available for "
                f"{protection.device.value} {protection.rating_a} A at "
                f"{protection.max_disconnection_time_s} s. Supply I_a from the "
                "device time/current curve, or transcribe AS/NZS 3000's "
                f"maximum Z_s table. No default. ({exc})"
            ) from exc
        limit = u0_v / disconnection_current_a
        basis = f"U_0/I_a with I_a = {disconnection_current_a:g} A from device curve"

    return CheckResult(
        name="earth fault loop impedance",
        passed=z_s <= limit,
        governing_value=z_s,
        limit=limit,
        units="ohm",
        detail={**loop, "basis": basis, "u0_v": u0_v,
                "disconnection_time_s": protection.max_disconnection_time_s},
    )
