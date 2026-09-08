"""End-to-end example against the synthetic test fixtures.

    python example.py

Swap `tests/fixtures` for `data` once the licensed tables are transcribed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from dame_cable import (Cable, CableConstruction, ConductorMaterial, DeviceType,
                        InstallationArrangement, InstallationMethod, Insulation,
                        Load, Protection, Route, RouteSegment, SystemType,
                        TableStore, select)

store = TableStore.load(Path(__file__).parent / "tests" / "fixtures")

# A GPU hall feeder: hot riser out of the plant room, a long tray run, then a
# buried crossing to the pod. UPS-backed, so a non-trivial third harmonic.
route = Route([
    RouteSegment(25, InstallationMethod(
        arrangement=InstallationArrangement.UNENCLOSED_TOUCHING,
        ambient_c=45, circuits_in_group=4), "plant room riser"),
    RouteSegment(160, InstallationMethod(
        arrangement=InstallationArrangement.UNENCLOSED_TOUCHING,
        ambient_c=35), "ceiling tray"),
    RouteSegment(45, InstallationMethod(
        arrangement=InstallationArrangement.BURIED_DIRECT, ambient_c=25,
        depth_of_burial_m=0.8, soil_thermal_resistivity_km_w=1.2),
        "site crossing"),
])

cable = Cable(material=ConductorMaterial.COPPER,
              insulation=Insulation.THERMOSETTING_90,
              construction=CableConstruction.MULTICORE,
              size_mm2=95, cores_loaded=3, pe_size_mm2=95,
              pe_material=ConductorMaterial.COPPER)

load = Load(design_current_a=280, system=SystemType.THREE_PHASE_AC,
            nominal_voltage_v=400, power_factor=0.95,
            third_harmonic_fraction=0.20, max_voltage_drop_fraction=0.02)

protection = Protection(device=DeviceType.MCB_C, rating_a=315,
                        prospective_fault_current_a=25000, clearing_time_s=0.1,
                        max_disconnection_time_s=5.0,
                        external_loop_impedance_ohm=0.05)

# I_a taken from the device time/current curve at the required
# disconnection time. There is no default for this and there should not be.
selection = select(store, cable, route, load, protection,
                   u0_v=230, disconnection_current_a=1000,
                   refine_operating_temperature=True)
print(selection.report())
print()
print("compliant:", selection.compliant)
