"""LangGraph orchestration: ingest -> validate -> risk -> approval -> memo -> pay | reject | hold -> report.

Each node catches its own exceptions, records them on the state and lets the invoice
continue to a safe outcome (never a payment), so one bad file never crashes a batch.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from . import ROOT
from .agents import approval, memo, risk
from .agents.ingestion import ingest
from .agents.payment import PaymentAgent, log_rejection
from .config import load_policy
from .db import Inventory, connect
from .hitl import enqueue
from .cache import CachedLLM
from .llm import LLMClient, OfflineClient
from .models import Decision, DecisionStatus, InvoiceState, TraceEvent
from .parsers import parse_file
from .validation import DuplicateRegistry, content_hash, document_id, fingerprint, number_key, validate


class GraphState(TypedDict):
    s: InvoiceState


@dataclass
class RunContext:
    conn: sqlite3.Connection
    inventory: Inventory
    policy: dict[str, Any]
    llm: LLMClient
    payments: PaymentAgent
    registry: DuplicateRegistry = field(default_factory=DuplicateRegistry)
    run_id: str = ""
    run_dir: Path | None = None

    def trace_path(self) -> Path | None:
        return self.run_dir / "trace.jsonl" if self.run_dir else None


def llm_usage(records: list[dict]) -> dict:
    """Sum of usage records (see llm.usage_record) for one node."""
    keys = ("prompt_tokens", "cached_prompt_tokens", "completion_tokens", "reasoning_tokens")
    out: dict[str, Any] = {"calls": len(records), **{k: sum(r[k] for r in records) for k in keys},
                           "api_latency_s": round(sum(r["latency_s"] for r in records), 3),
                           "max_prompt_tokens": max((r["prompt_tokens"] for r in records), default=0),
                           "purposes": [r["purpose"] for r in records]}
    ticks = [r["cost_in_usd_ticks"] for r in records if r.get("cost_in_usd_ticks") is not None]
    out["cost_in_usd_ticks"] = sum(ticks) if len(ticks) == len(records) else None
    return out


def _safe(name: str, fn: Callable[[InvoiceState], InvoiceState], llm: Any = None):
    def node(g: GraphState) -> GraphState:
        s = g["s"]
        log = getattr(llm, "usage_log", None)
        n0 = len(log) if log is not None else 0
        t0 = time.monotonic()
        try:
            s = fn(s)
        except Exception as e:  # noqa: BLE001 - keep the batch alive, record the error
            s.errors.append(f"{name}: {type(e).__name__}: {e}")
            s.trace.append(TraceEvent(agent=name, step="error", detail={"error": str(e)}))
            if name in ("risk", "approval") and s.decision is None:
                s.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="error",
                                      reasons=[f"{name} failed: {e}"])
        detail: dict[str, Any] = {"ms": round((time.monotonic() - t0) * 1000, 1)}
        if log is not None and len(log) > n0:
            detail["llm"] = llm_usage(log[n0:])
        s.trace.append(TraceEvent(agent=name, step="node_done", detail=detail))
        return {"s": s}
    return node


def build_graph(ctx: RunContext):
    def do_ingest(s: InvoiceState) -> InvoiceState:
        if isinstance(ctx.llm, CachedLLM):
            ctx.llm.start(s.source)   # per-invoice cache key and model record
        return ingest(s.source, ctx.inventory, ctx.llm)

    def route(g: GraphState) -> str:
        d = g["s"].decision
        if d is None:
            return "hold"
        return {DecisionStatus.APPROVED: "pay", DecisionStatus.REJECTED: "reject"}.get(d.status, "hold")

    def report(s: InvoiceState) -> InvoiceState:
        inv = s.invoice
        status = s.decision.status.value if s.decision else "UNKNOWN"
        if inv is not None:   # stored history for later runs (duplicate checks, vendor_history tool)
            ctx.conn.execute(
                "INSERT INTO invoices (invoice_number, revision, vendor, total, currency, source_file, fingerprint, status, "
                "run_id, number_key, base_fp, content_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(fingerprint) DO UPDATE SET status=excluded.status, source_file=excluded.source_file, "
                "run_id=COALESCE(invoices.run_id, excluded.run_id), number_key=excluded.number_key, "
                "base_fp=excluded.base_fp, content_key=excluded.content_key",
                (inv.number, inv.revision, inv.vendor, inv.total, inv.currency, s.source, document_id(inv, s.source),
                 status, ctx.run_id, number_key(inv), fingerprint(inv), content_hash(inv)))
            ctx.conn.commit()
        path = ctx.trace_path()
        if path:
            with open(path, "a") as fh:
                root = str(ROOT) + "/"  # traces are committed; keep paths repo-relative
                for ev in s.trace:
                    fh.write(json.dumps({"run_id": ctx.run_id, "source": Path(s.source).name,
                                         "invoice": inv.number if inv else None, **ev.model_dump(mode="json")},
                                        default=str).replace(root, "") + "\n")
        return s

    g = StateGraph(GraphState)
    g.add_node("ingest", _safe("ingestion", do_ingest, ctx.llm))
    g.add_node("validate", _safe("validation", lambda s: validate(s, ctx.inventory, ctx.policy, ctx.registry)))
    g.add_node("risk", _safe("risk", lambda s: risk.assess(s, ctx.policy, ctx.llm, risk.risk_tools(ctx.inventory, ctx.conn)), ctx.llm))
    g.add_node("approve", _safe("approval", lambda s: approval.approve(s, ctx.llm, ctx.policy), ctx.llm))
    g.add_node("memo", _safe("memo", lambda s: memo.write_memo(s, ctx.llm), ctx.llm))
    g.add_node("pay", _safe("payment", ctx.payments.pay))
    g.add_node("reject", _safe("payment", lambda s: log_rejection(ctx.conn, s)))
    g.add_node("hold", _safe("hitl", lambda s: enqueue(ctx.conn, s)))
    g.add_node("report", _safe("reporter", report))
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "validate")
    g.add_edge("validate", "risk")
    g.add_edge("risk", "approve")
    g.add_edge("approve", "memo")   # decision 12: the memo is written after the decision and cannot change it
    g.add_conditional_edges("memo", route, {"pay": "pay", "reject": "reject", "hold": "hold"})
    for n in ("pay", "reject", "hold"):
        g.add_edge(n, "report")
    g.add_edge("report", END)
    return g.compile()


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def make_context(llm: LLMClient | None = None, db: str | None = None, chaos: float = 0.0, seed: int | None = None,
                 runs_dir: Path | None = ROOT / "runs", run_id: str | None = None, base_delay: float = 0.2,
                 sleep: Callable[[float], None] = time.sleep, cache: bool = True) -> RunContext:
    """cache: reuse stored Grok answers for a repeated invoice (live only; see invoice_agents/cache.py).
    With cache=False the model pin still applies; nothing is read from or written to the cache."""
    conn = connect(db)
    if llm is not None and llm.available and not isinstance(llm, CachedLLM):
        llm = CachedLLM(llm, conn, enabled=cache)
    run_id = run_id or new_run_id()
    run_dir = None
    if runs_dir is not None:
        run_dir = Path(runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "trace.jsonl").write_text("")
    return RunContext(conn=conn, inventory=Inventory(conn), policy=load_policy(), llm=llm or OfflineClient(),
                      payments=PaymentAgent(conn, chaos=chaos, seed=seed, base_delay=base_delay, sleep=sleep),
                      registry=DuplicateRegistry(conn=conn, run_id=run_id), run_id=run_id, run_dir=run_dir)


def run_batch(paths: list[Path], ctx: RunContext) -> list[InvoiceState]:
    parsed = []
    for p in paths:  # prescan so revisions and duplicates are known before any decision
        try:
            parsed.append(parse_file(p))
        except Exception:  # noqa: BLE001 - the real pass reports it
            pass
    ctx.registry.prescan(parsed)
    graph = build_graph(ctx)
    return [graph.invoke({"s": InvoiceState(source=str(p))})["s"] for p in paths]
