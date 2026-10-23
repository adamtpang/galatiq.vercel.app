"""LangGraph orchestration: ingest -> validate -> risk -> approval -> memo -> pay | reject | hold -> report.

Each node catches its own exceptions and records them on the state, so one bad file never crashes a batch.
Error handling fails closed (review 2):
- an exception in ingest, validate or risk adds an INTERNAL_ERROR flag; the approval agent then holds the
  invoice for a person before any VP call (or the hard rules reject it, if a blocking flag was already found);
- an exception in the approval agent leaves no decision or an unusable one: the invoice is held;
- the `guard` node, after the memo, turns any APPROVED invoice that has a recorded error into a hold (and one
  with a blocking flag into a rejection) before the route to payment; the route itself only sends a clean
  APPROVED invoice to `pay`; and the payment agent refuses again on any error or blocking flag.
So a crash can never pay an invoice.
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
from .hitl import clear_failed_payment, enqueue, enqueue_failed_payment
from .cache import CachedLLM
from .llm import LLMClient, OfflineClient
from .models import Decision, DecisionStatus, Flag, InvoiceState, Severity, TraceEvent
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


CHECK_STAGES = ("ingestion", "validation", "risk")   # a crash here means the checks did not (all) run


def _safe(name: str, fn: Callable[[InvoiceState], InvoiceState], llm: Any = None):
    def node(g: GraphState) -> GraphState:
        s = g["s"]
        log = getattr(llm, "usage_log", None)
        n0 = len(log) if log is not None else 0
        t0 = time.monotonic()
        try:
            s = fn(s)
        except Exception as e:  # noqa: BLE001 - keep the batch alive, record the error
            msg = f"{name}: {type(e).__name__}: {e}"
            s.errors.append(msg)
            s.trace.append(TraceEvent(agent=name, step="error", detail={"error": msg}))
            if name in CHECK_STAGES:   # fail closed: the approval agent holds on this flag before the VP
                s.flags.append(Flag(code="INTERNAL_ERROR", severity=Severity.WARN, evidence={"stage": name},
                                    message=f"The {name} step failed ({type(e).__name__}: {str(e)[:160]}), so its "
                                            "checks did not run; a person must review this invoice"))
            if name == "approval" and s.decision is None:
                s.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="error",
                                      reasons=[f"INTERNAL_ERROR: approval failed: {e}"])
        detail: dict[str, Any] = {"ms": round((time.monotonic() - t0) * 1000, 1)}
        if log is not None and len(log) > n0:
            detail["llm"] = llm_usage(log[n0:])
        s.trace.append(TraceEvent(agent=name, step="node_done", detail=detail))
        return {"s": s}
    return node


def fail_closed(s: InvoiceState) -> InvoiceState:
    """Last check before the route to payment. APPROVED with a recorded error -> PENDING_HUMAN; APPROVED with a
    blocking flag -> REJECTED (blocking always means rejected). No decision -> PENDING_HUMAN."""
    d = s.decision
    errs = s.pipeline_errors()
    blocks = [f for f in s.flags if f.severity == Severity.BLOCK]
    if d is None:
        s.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="error",
                              reasons=["INTERNAL_ERROR: no decision was recorded" + (f" ({errs[0]})" if errs else "")])
    elif d.status == DecisionStatus.APPROVED and d.decided_by != "human" and (errs or blocks):
        before = d.model_dump(mode="json")
        if blocks:
            s.decision = Decision(status=DecisionStatus.REJECTED, decided_by="hard_rules", risk_score=d.risk_score,
                                  reasons=[f"{f.code}: {f.message}" for f in blocks],
                                  arguments={"decision_before_guard": before})
        else:
            s.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="error", risk_score=d.risk_score,
                                  reasons=[f"INTERNAL_ERROR: {errs[0]}; nothing is paid while a step has failed"],
                                  arguments={"decision_before_guard": before})
    else:
        return s
    s.trace.append(TraceEvent(agent="guard", step="decide", detail=s.decision.model_dump(mode="json")))
    s.memo = None
    return memo.write_memo(s, None)   # the memo written before the guard described the old decision


def build_graph(ctx: RunContext):
    def do_ingest(s: InvoiceState) -> InvoiceState:
        if isinstance(ctx.llm, CachedLLM):
            ctx.llm.start(s.source)   # per-invoice cache key and model record
        return ingest(s.source, ctx.inventory, ctx.llm)

    def route(g: GraphState) -> str:
        s = g["s"]
        d = s.decision
        if d is None:
            return "hold"
        if d.status == DecisionStatus.APPROVED:
            # only a clean approval reaches the bank (guard has normally converted anything else already)
            return "pay" if not s.pipeline_errors() and not s.has_blocking() else "hold"
        # a superseded original (decision 24) is logged as not paid, like a rejection, with its own status
        return "reject" if d.status in (DecisionStatus.REJECTED, DecisionStatus.SUPERSEDED) else "hold"

    def pay(s: InvoiceState) -> InvoiceState:
        try:
            s = ctx.payments.pay(s)
        except Exception as e:  # noqa: BLE001 - review 3: never leave an invoice APPROVED but unpaid
            s.errors.append(f"payment: {type(e).__name__}: {e}")
            s = ctx.payments._hold(s, f"the payment step raised {type(e).__name__} ({str(e)[:120]})")
            return s
        if (s.payment or {}).get("status") == "failed":
            enqueue_failed_payment(ctx.conn, s)   # review 2: a failed payment is visible and queued for a person
        elif (s.payment or {}).get("status") in ("paid", "already_paid"):
            clear_failed_payment(ctx.conn, s)
        return s

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
            with open(path, "a", encoding="utf-8") as fh:
                for ev in s.trace:
                    payload = {"run_id": ctx.run_id, "source": Path(s.source).name,
                               "invoice": inv.number if inv else None, **ev.model_dump(mode="json")}
                    fh.write(json.dumps(trace_relative(payload), default=str) + "\n")
        return s

    g = StateGraph(GraphState)
    g.add_node("ingest", _safe("ingestion", do_ingest, ctx.llm))
    g.add_node("validate", _safe("validation", lambda s: validate(s, ctx.inventory, ctx.policy, ctx.registry)))
    g.add_node("risk", _safe("risk", lambda s: risk.assess(s, ctx.policy, ctx.llm, risk.risk_tools(ctx.inventory, ctx.conn)), ctx.llm))
    g.add_node("approve", _safe("approval", lambda s: approval.approve(s, ctx.llm, ctx.policy), ctx.llm))
    g.add_node("memo", _safe("memo", lambda s: memo.write_memo(s, ctx.llm), ctx.llm))
    g.add_node("guard", _safe("guard", fail_closed))
    g.add_node("pay", _safe("payment", pay))
    g.add_node("reject", _safe("payment", lambda s: log_rejection(ctx.conn, s)))
    g.add_node("hold", _safe("hitl", lambda s: enqueue(ctx.conn, s)))
    g.add_node("report", _safe("reporter", report))
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "validate")
    g.add_edge("validate", "risk")
    g.add_edge("risk", "approve")
    g.add_edge("approve", "memo")   # decision 12: the memo is written after the decision and cannot change it
    g.add_edge("memo", "guard")
    g.add_conditional_edges("guard", route, {"pay": "pay", "reject": "reject", "hold": "hold"})
    for n in ("pay", "reject", "hold"):
        g.add_edge(n, "report")
    g.add_edge("report", END)
    return g.compile()


def trace_relative(value: Any) -> Any:
    """Keep repo paths portable before JSON escapes Windows backslashes."""
    if isinstance(value, dict):
        return {k: trace_relative(v) for k, v in value.items()}
    if isinstance(value, list):
        return [trace_relative(v) for v in value]
    if isinstance(value, str):
        prefixes = (str(ROOT) + "/", str(ROOT) + "\\", ROOT.as_posix() + "/")
        for prefix in prefixes:
            if value.startswith(prefix):
                return value[len(prefix):].replace("\\", "/")
        for prefix in prefixes:
            value = value.replace(prefix, "")
    return value


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
        (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
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
    out = []
    for p in paths:
        try:
            out.append(graph.invoke({"s": InvoiceState(source=str(p))})["s"])
        except Exception as e:  # noqa: BLE001 - the graph itself failed: record it, never pay, keep the batch going
            st = InvoiceState(source=str(p), errors=[f"graph: {type(e).__name__}: {e}"])
            st.decision = Decision(status=DecisionStatus.PENDING_HUMAN, decided_by="error",
                                   reasons=[f"INTERNAL_ERROR: the pipeline failed: {e}"])
            st.payment = {"status": "not_paid", "reason": "pipeline error"}
            out.append(st)
    return out
