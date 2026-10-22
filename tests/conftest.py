import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from invoice_agents.config import load_policy  # noqa: E402
from invoice_agents.db import Inventory, connect, init_db  # noqa: E402

INVOICES = ROOT / "data" / "invoices"

# Pin the PAST_DUE reference date so flag sets do not depend on the day the tests run.
# 2026-01-01 is before every sample due date; tests/test_validation.py checks PAST_DUE with other dates.
os.environ.setdefault("INVOICE_AS_OF", "2026-01-01")


@pytest.fixture(scope="session")
def db_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("db") / "inventory.db"
    init_db(p)
    return p


@pytest.fixture(scope="session")
def inventory(db_file):
    with connect(db_file) as conn:
        return Inventory(conn)


@pytest.fixture(scope="session")
def policy():
    return load_policy()
