"""Risk agent. STUB until Adam's design lands.

TODO(Adam): deterministic risk signals and weights. Returns score 0 for now.
"""
from __future__ import annotations

from typing import Any

from ..llm import LLMClient
from ..models import InvoiceState, TraceEvent


def assess(state: InvoiceState, policy: dict[str, Any], llm: LLMClient | None = None) -> InvoiceState:
    state.risk = {"score": 0, "reasons": ["risk agent not built (stub)"], "signals": [], "stub": True}
    state.trace.append(TraceEvent(agent="risk", step="assess", detail=state.risk))
    return state
