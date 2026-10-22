"""Approval agent. STUB: applies only the hard rule until Adam's VP + critic logic lands.

Hard rule (Adam, DECISIONS.md #1 and the spec): any blocking flag => REJECTED, no LLM.
Everything else => PENDING_HUMAN with reason "approval agent not built".

TODO(Adam): VP agent, critic loop (critic_max_rounds), deadlock => PENDING_HUMAN.
"""
from __future__ import annotations

from typing import Any

from ..llm import LLMClient
from ..models import Decision, DecisionStatus, InvoiceState, Severity, TraceEvent

NOT_BUILT = "approval agent not built"
IS_STUB = True  # tests xfail golden cases that need the real approval agent


def hard_rules(state: InvoiceState) -> Decision | None:
    blocks = [f for f in state.flags if f.severity == Severity.BLOCK]
    if not blocks:
        return None
    return Decision(status=DecisionStatus.REJECTED, reasons=[f"{f.code}: {f.message}" for f in blocks],
                    risk_score=(state.risk or {}).get("score"), decided_by="hard_rules")


def approve(state: InvoiceState, llm: LLMClient, policy: dict[str, Any]) -> InvoiceState:
    d = hard_rules(state) or Decision(status=DecisionStatus.PENDING_HUMAN, reasons=[NOT_BUILT],
                                      risk_score=(state.risk or {}).get("score"), decided_by="stub")
    state.decision = d
    state.trace.append(TraceEvent(agent="approval", step="decide", detail=d.model_dump(mode="json")))
    return state
