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


def init_db(path: Path | str | None = None) -> Path:
    """Create tables and (re)apply the seed. Safe to run any number of times."""
    p = Path(path) if path else db_path()
    with sqlite3.connect(p) as conn:
        conn.executescript(SEED_SQL.read_text())
    return p


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    if not p.exists():
        init_db(p)
    conn = sqlite3.connect(p)
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
