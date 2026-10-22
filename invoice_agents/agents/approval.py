"""Approval agent (VP persona + critic/reflection loop). NOT BUILT YET.

TODO(Adam): design and implement. This is deliberately left to Adam to own and explain.
Inputs available today: state.invoice, state.flags (code, severity, message, evidence),
state.total_usd, and config/policy.yaml (approval_threshold_usd, decisions.*).

Decisions already made (README "Decisions", values in config/policy.yaml `approval:`):
  1. Over-stock -> REJECT. Validation emits a blocking STOCK_EXCEEDED flag with
     evidence {item, requested, stock}.
  2. VP/critic deadlock after critic_max_rounds (2): PENDING_HUMAN, both arguments attached.
  3. Critic loop only when total > approval_threshold_usd (10000), total >= near_limit_usd
     (9500), or risk_score >= high_risk_score (50). Otherwise the VP decides alone after hard rules.

Still open for Adam: how risk_score is computed (risk agent not built), the VP and critic
prompts, and how to treat revisions and FX invoices.
"""
from __future__ import annotations

from typing import Any, Protocol

from ..llm import LLMClient
from ..models import Decision, InvoiceState


class ApprovalAgent(Protocol):
    def decide(self, state: InvoiceState, llm: LLMClient, policy: dict[str, Any]) -> Decision:
        """Return APPROVED, REJECTED or PENDING_HUMAN with reasons, conditions and critique_rounds."""
        ...


def approve(state: InvoiceState, llm: LLMClient, policy: dict[str, Any]) -> Decision:
    raise NotImplementedError("Approval agent not built yet (owned by Adam).")
