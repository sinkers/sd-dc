"""DAME LV cable sizing - AS/NZS 3008.1.1:2025 and AS/NZS 3000.

The tables of both standards are licensed content and are NOT distributed with
this package. Populate the CSV files under data/ from your own licensed copy;
`python -m dame_cable.tables.validate data/` reports what is still missing.
"""

from .errors import (
    CableCalcError,
    InvalidDeclaration,
    MissingTableData,
    NoCompliantSize,
    OpenItem,
)
from .schema import (
    Armour,
    Cable,
    CableConstruction,
    CheckResult,
    ConductorForm,
    ConductorMaterial,
    DeclaredAs,
    DeviceType,
    InstallationArrangement,
    InstallationMethod,
    Insulation,
    Load,
    Protection,
    Route,
    RouteSegment,
    Sheath,
    SystemType,
)
from .tables.registry import TableStore
from .select_conductor import Selection, select

__all__ = [
    "Armour", "Cable", "CableCalcError", "CableConstruction", "CheckResult",
    "ConductorForm", "ConductorMaterial", "DeclaredAs", "DeviceType",
    "InstallationArrangement", "InstallationMethod", "Insulation",
    "InvalidDeclaration", "Load", "MissingTableData", "NoCompliantSize",
    "OpenItem", "Protection", "Route", "RouteSegment", "Selection", "Sheath",
    "SystemType", "TableStore", "select",
]
