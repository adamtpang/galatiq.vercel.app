"""Ingest + validate only (used by validation tests). The full pipeline is invoice_agents/graph.py."""
from __future__ import annotations

from pathlib import Path

from .agents.ingestion import ingest
from .config import load_policy
from .db import Inventory, connect
from .llm import LLMClient, OfflineClient
from .models import InvoiceState
from .parsers import SUPPORTED
from .validation import DuplicateRegistry, validate


def run_files(paths: list[Path], llm: LLMClient | None = None, db: str | None = None) -> list[InvoiceState]:
    policy = load_policy()
    with connect(db) as conn:
        inventory = Inventory(conn)
    registry = DuplicateRegistry()
    llm = llm or OfflineClient()
    return [validate(ingest(p, inventory, llm), inventory, policy, registry) for p in paths]


def collect(path: str | Path) -> list[Path]:
    p = Path(path)
    if p.is_dir():
        return sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
    return [p]
