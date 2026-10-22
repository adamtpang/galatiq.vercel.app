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
    backfill(conn)


def backfill(conn: sqlite3.Connection) -> int:
    """Fill empty history keys on rows stored before those columns existed, so older databases get the
    same cross-run duplicate checks. number_key and base_fp come from the stored columns; content_key
    needs the line items, so the stored source file is ingested again offline (only if it still exists and still
    has the same fingerprint). Rows with no run_id are marked 'legacy', meaning stored by an earlier run.
    Returns the number of rows updated. Runs on every connect; it is a no-op once nothing is empty."""
    rows = conn.execute("SELECT id, invoice_number, revision, vendor, total, source_file FROM invoices WHERE "
                        "run_id IS NULL OR number_key IS NULL OR base_fp IS NULL OR content_key IS NULL").fetchall()
    if not rows:
        return 0
    from .agents.ingestion import ingest
    from .models import Invoice
    from .validation import content_hash, fingerprint, number_key
    prev, conn.row_factory = conn.row_factory, sqlite3.Row   # Inventory reads columns by name
    try:
        inventory = Inventory(conn)
    finally:
        conn.row_factory = prev
    n = 0
    for rid, number, revision, vendor, total, source in rows:
        inv = Invoice(number=number, revision=revision, vendor=vendor, total=total)
        ckey = None
        src = Path(source) if source else None
        if src is not None and not src.is_absolute() and not src.exists():
            src = ROOT / src
        if src is not None and src.exists():
            try:
                parsed = ingest(src, inventory).invoice   # same offline ingestion as a run, no LLM
                if parsed is not None and fingerprint(parsed) == fingerprint(inv):
                    ckey = content_hash(parsed)
            except Exception:  # noqa: BLE001 - an unreadable old file keeps an empty content key
                ckey = None
        conn.execute("UPDATE invoices SET run_id=COALESCE(run_id, 'legacy'), number_key=COALESCE(number_key, ?), "
                     "base_fp=COALESCE(base_fp, ?), content_key=COALESCE(content_key, ?) WHERE id=?",
                     (number_key(inv), fingerprint(inv), ckey, rid))
        n += 1
    conn.commit()
    return n


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
