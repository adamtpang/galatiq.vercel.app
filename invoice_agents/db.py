"""SQLite access for the mock Acme ERP (inventory, vendors, invoices, payments, audit log)."""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import ROOT

SEED_SQL = ROOT / "config" / "seed.sql"


def db_path() -> Path:
    return Path(os.environ.get("INVENTORY_DB", ROOT / "inventory.db"))


# Columns added to `invoices` after the first schema; migrate() adds them to older databases.
INVOICE_COLUMNS = {"run_id": "TEXT", "number_key": "TEXT", "base_fp": "TEXT", "content_key": "TEXT"}
INDEXES = ("CREATE INDEX IF NOT EXISTS ix_invoices_base_fp ON invoices(base_fp)",
           "CREATE INDEX IF NOT EXISTS ix_invoices_number_key ON invoices(number_key)",
           "CREATE INDEX IF NOT EXISTS ix_invoices_content_key ON invoices(content_key)")


def migrate(conn: sqlite3.Connection) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(invoices)")}
    for col, typ in INVOICE_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE invoices ADD COLUMN {col} {typ}")
    for st in INDEXES:
        conn.execute(st)


def init_db(path: Path | str | None = None) -> Path:
    """Create tables and (re)apply the seed. Safe to run any number of times; keeps processed invoices."""
    p = Path(path) if path else db_path()
    with sqlite3.connect(p) as conn:
        conn.executescript(SEED_SQL.read_text())
        migrate(conn)
    return p


def ensure_schema(path: Path | str) -> None:
    stmts = [st for st in SEED_SQL.read_text().split(";") if "CREATE TABLE" in st]
    with sqlite3.connect(path) as conn:
        for st in stmts:
            conn.execute(st)
        migrate(conn)


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    if not p.exists():
        init_db(p)
    else:
        ensure_schema(p)  # adds tables introduced since the DB was created, keeps data
    conn = sqlite3.connect(p, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass(frozen=True)
class InventoryRow:
    item: str
    stock: int
    unit_price: float | None
    category: str | None


@dataclass(frozen=True)
class VendorRow:
    name: str
    aliases: tuple[str, ...]
    address: str | None
    approved: bool
    bank_on_file: bool


class Inventory:
    """Read-only snapshot used by the validation tools."""

    def __init__(self, conn: sqlite3.Connection):
        self.items = {
            r["item"]: InventoryRow(r["item"], r["stock"], r["unit_price"], r["category"])
            for r in conn.execute("SELECT * FROM inventory")
        }
        self.vendors = {
            r["name"]: VendorRow(r["name"], tuple(json.loads(r["aliases"] or "[]")), r["address"],
                                 bool(r["approved"]), bool(r["bank_on_file"]))
            for r in conn.execute("SELECT * FROM vendors")
        }

    def query_inventory(self, sku: str) -> InventoryRow | None:
        return self.items.get(sku)

    def lookup_vendor(self, name: str) -> VendorRow | None:
        key = _norm(name)
        for v in self.vendors.values():
            if _norm(v.name) == key or any(_norm(a) == key for a in v.aliases):
                return v
        return None


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def log_audit(conn: sqlite3.Connection, invoice_number: str | None, agent: str, event: str, detail: dict) -> None:
    conn.execute("INSERT INTO audit_log (invoice_number, agent, event, detail) VALUES (?,?,?,?)",
                 (invoice_number, agent, event, json.dumps(detail, default=str)))
    conn.commit()
