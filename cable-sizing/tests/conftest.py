import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dame_cable.tables.registry import TableStore  # noqa: E402


@pytest.fixture(scope="session")
def store():
    """Synthetic fixture data. See tests/fixtures/make_fixtures.py."""
    return TableStore.load(Path(__file__).parent / "fixtures")


@pytest.fixture(scope="session")
def licensed_store():
    """The real data/ directory. Most tests skip until it is populated."""
    return TableStore.load(ROOT / "data")


@pytest.fixture(scope="session")
def licensed_ccc(licensed_store):
    """The licensed store, skipped unless the base rating tables are present.

    A verification case against an empty table is not a failure, it is a case
    that cannot be run yet. Failing it would train people to ignore red.
    """
    if not licensed_store.tables["ccc"].rows:
        pytest.skip(
            "data/ccc.csv is empty. These are the M4 acceptance cases and they "
            "need the licensed AS/NZS 3008.1.1:2025 Section 3 tables. "
            "See METHODOLOGY-S4-RevB.md section 4.10."
        )
    return licensed_store
