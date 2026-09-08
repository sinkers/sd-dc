"""Lazy, injectable data store for the licensed and vendor tables.

Why this exists
---------------
AS/NZS 3008.1.1 and AS/NZS 3000 are licensed documents, and the manufacturer
catalogues are third-party data. The code is publishable; the numbers are not.
Everything in `MANIFEST` therefore lives outside version control and is fetched
from private storage, while this module and everything above it stays open.

The rule that makes that work is that **nothing loads at import time**. Before
this module existed, `as3008.py` did `TABLES = _load_tables()` at module scope
and `as3008_2025.py` did the same for four more files, so a clean checkout
without the private data failed at `import as3008` rather than at first use.
CI could not run at all. Now the data is loaded on first access and a checkout
without it imports, runs its unit tests against synthetic fixtures, and fails
only where a real table is genuinely needed -- with an error that names the
file, the standard and the clause.

Design rules, inherited from the dame-cable table store:

1. No silent defaults. A miss raises MissingTableData naming the table, the key
   and the source, so a gap is a shopping list rather than a wrong answer.
2. Every file declares its provenance and whether it is publishable.
3. The data directory is injectable: `set_data_dir()`, or the environment
   variable CABLE_SIZING_DATA_DIR, or the package directory as the default.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_VAR = "CABLE_SIZING_DATA_DIR"


class MissingTableData(FileNotFoundError):
    """Raised when a licensed data file is needed but not present.

    Carries the provenance so the reader knows what to go and get, rather than
    seeing a bare path that means nothing without the manifest.
    """

    def __init__(self, spec: "DataFile", path: str):
        self.spec = spec
        self.path = path
        super().__init__(
            f"{spec.filename} is not available at {path}.\n"
            f"  Contains : {spec.description}\n"
            f"  Source   : {spec.standard}\n"
            f"  Licensed : {'yes -- never commit this file' if spec.licensed else 'no'}\n"
            f"  Fetch    : {spec.fetch}\n"
            f"Set {ENV_VAR} to point at a directory holding it, or call "
            f"tables.set_data_dir()."
        )


@dataclass(frozen=True)
class DataFile:
    file_id: str
    filename: str
    standard: str
    description: str
    licensed: bool
    fetch: str = ""
    #: Where the file sits in a normal checkout, relative to this package.
    #: Vendor catalogues live in sibling components rather than here. A
    #: fixture directory holds flat basenames, so the store looks for
    #: `data_dir/filename` first and falls back to this.
    default_relpath: str = ""


#: Every file the package reads that is not source code.
#:
#: `licensed=True` means the content is reproduced from a copyrighted document
#: and must stay out of the public repository. `licensed=False` files are safe
#: to publish but are listed here so the store is the single place that knows
#: where data comes from.
_BUCKET = "s3://sd-dc-artifacts-730335486558-apse2"
S3 = f"{_BUCKET}/standards/as-nzs-3008/"

#: Manufacturer catalogues. Published by their makers for use with their
#: products, which is not a licence for us to redistribute them, so they sit
#: alongside the standards tables rather than in the repository.
#: Fetch with tools/data_pull_vendor.sh.
VENDOR = f"{_BUCKET}/vendor/"

MANIFEST = (
    DataFile("impedance", "as3008_impedance_tables.json",
             "AS/NZS 3008.1.1:2025 Tables 4.1-4.13",
             "reactance, a.c. and d.c. resistance", True, S3),
    DataFile("vc", "as3008_vc_tables.json",
             "AS/NZS 3008.1.1:2025 Tables 4.14-4.31",
             "tabulated voltage drop, mV/A.m", True, S3),
    DataFile("short_circuit", "as3008_short_circuit.json",
             "AS/NZS 3008.1.1:2025 Table 5.2",
             "short-circuit limit temperatures", True, S3),
    DataFile("ratings", "as3008_ratings.json",
             "AS/NZS 3008.1.1:2025 Table 3.14 column 5",
             "current-carrying capacity, one column", True, S3),
    DataFile("reference", "reference_tables.json",
             "AS/NZS 3000:2018, nine tables and clauses",
             "limiting temperatures, minimum sizes, voltage drop limits, "
             "conductor colours, conduit fill C10-C12, Table C8, earth sizing",
             True, "still tracked in git pending the B5 split"),
    DataFile("reference_public", "reference_tables_public.json",
             "AS/NZS 3000:2018 provenance, not content",
             "structure, clause numbers, units and verification status for the "
             "nine AS/NZS 3000 tables, plus the clause 3.6.2 limits (5/7/11 %), "
             "which are published figures rather than a reproduced table",
             False, "tracked in git -- this is the publishable half"),
    DataFile("tricab", "tricab_families.json",
             "Tricab (tricab.com), captured 2026-09-02",
             "cable family metadata only, no per-size electrical data",
             True, VENDOR + "tricab/",
             "tricab_families.json"),
    DataFile("nexans", "cable_catalog.json",
             "Nexans Australia, published product data",
             "current ratings, resistances, reactances, diameters and masses; "
             "drives cable sizing",
             True, VENDOR + "nexans/",
             "../cables/cable_catalog.json"),
    DataFile("ezystrut", "tray_catalogue.json",
             "Ezystrut, transcribed from their published datasheets",
             "cable tray dimensions and part numbers",
             True, VENDOR + "ezystrut/",
             "../cable-tray-ezystrut/tray_catalogue.json"),
)

MANIFEST_BY_ID = {f.file_id: f for f in MANIFEST}

_data_dir: str | None = None
_cache: dict[str, dict] = {}


def set_data_dir(path: str | None) -> None:
    """Point the store at a directory of data files and drop the cache."""
    global _data_dir
    _data_dir = path
    _cache.clear()


def data_dir() -> str:
    """Injected directory, else CABLE_SIZING_DATA_DIR, else this package."""
    if _data_dir is not None:
        return _data_dir
    return os.environ.get(ENV_VAR) or HERE


def path_for(file_id: str) -> str:
    """Where to read this file from.

    A flat `data_dir/<filename>` wins if it exists -- that is how the synthetic
    fixture directory and an S3 pull into one place both work. Otherwise fall
    back to where the file naturally lives in a checkout, which for the vendor
    catalogues is a sibling component directory.
    """
    spec = MANIFEST_BY_ID[file_id]
    flat = os.path.join(data_dir(), spec.filename)
    if os.path.exists(flat) or not spec.default_relpath:
        return flat
    return os.path.normpath(os.path.join(HERE, spec.default_relpath))


def available(file_id: str) -> bool:
    """Whether the file is present, without loading or raising."""
    return os.path.exists(path_for(file_id))


def load(file_id: str) -> dict:
    """Parsed contents of a data file. Loaded once, then cached.

    Raises MissingTableData naming the provenance if the file is absent.
    """
    if file_id in _cache:
        return _cache[file_id]
    spec = MANIFEST_BY_ID[file_id]
    p = path_for(file_id)
    if not os.path.exists(p):
        raise MissingTableData(spec, p)
    with open(p) as fh:
        _cache[file_id] = json.load(fh)
    return _cache[file_id]


SYNTHETIC_MARKER = ".SYNTHETIC"


def is_synthetic() -> bool:
    """Whether the active data directory holds synthetic fixtures.

    True means every number in play is invented. Callers that assert real
    AS/NZS values must skip; nothing may be issued from a synthetic run.
    """
    return os.path.exists(os.path.join(data_dir(), SYNTHETIC_MARKER))


def require_real_data(what: str = "this operation") -> None:
    """Raise if the loaded data is synthetic. Guard for anything issuable."""
    if is_synthetic():
        raise MissingTableData(
            DataFile("synthetic", SYNTHETIC_MARKER, "SYNTHETIC FIXTURES",
                     f"{what} needs real licensed data, but the active data "
                     f"directory holds invented numbers", True,
                     "point CABLE_SIZING_DATA_DIR at the real data"),
            data_dir())


def coverage() -> list[dict]:
    """What is present and what is missing. Never raises."""
    return [{
        "file_id": f.file_id,
        "filename": f.filename,
        "standard": f.standard,
        "licensed": f.licensed,
        "present": available(f.file_id),
    } for f in MANIFEST]


# ---------------------------------------------------------------------------
# Lazy proxies
# ---------------------------------------------------------------------------
# Module-level constants derived from the data used to be computed at import.
# These proxies keep the original `NAME[key]` call sites working unchanged
# while deferring the first read to the first actual use.

class LazyMapping:
    """A dict computed on first access."""

    def __init__(self, builder):
        self._builder = builder
        self._value = None

    def _resolve(self):
        if self._value is None:
            self._value = self._builder()
        return self._value

    def __getitem__(self, k):
        return self._resolve()[k]

    def __contains__(self, k):
        return k in self._resolve()

    def __iter__(self):
        return iter(self._resolve())

    def __len__(self):
        return len(self._resolve())

    def __eq__(self, other):
        return self._resolve() == other

    def get(self, k, default=None):
        return self._resolve().get(k, default)

    def keys(self):
        return self._resolve().keys()

    def values(self):
        return self._resolve().values()

    def items(self):
        return self._resolve().items()

    def __repr__(self):
        state = "loaded" if self._value is not None else "not loaded"
        return f"<LazyMapping {state}>"


class LazySequence:
    """A list computed on first access."""

    def __init__(self, builder):
        self._builder = builder
        self._value = None

    def _resolve(self):
        if self._value is None:
            self._value = self._builder()
        return self._value

    def __getitem__(self, i):
        return self._resolve()[i]

    def __iter__(self):
        return iter(self._resolve())

    def __len__(self):
        return len(self._resolve())

    def __eq__(self, other):
        return self._resolve() == other

    def __repr__(self):
        state = "loaded" if self._value is not None else "not loaded"
        return f"<LazySequence {state}>"
