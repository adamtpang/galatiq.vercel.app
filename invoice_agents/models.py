"""Typed data passed between agents. Deterministic code and the LLM both produce these."""
from __future__ import annotations

import time
from datetime import date as Date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class LineItem(BaseModel):
    # NaN or infinity is never a valid quantity or price. validate_assignment: a value set after construction
    # (parsers fill fields one by one) is type-checked too, so a list or dict can never reach the checks as "text".
    model_config = ConfigDict(allow_inf_nan=False, validate_assignment=True)
    sku_raw: str = Field(description="Item name exactly as printed on the invoice")
    sku: str | None = Field(default=None, description="Normalized inventory SKU, None if unknown")
    sku_confidence: float = 0.0
    qty: float
    unit_price: float | None = None
    amount: float | None = None
    note: str | None = None


class Invoice(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, validate_assignment=True)
    number: str | None = None
    revision: str | None = None
    vendor: str | None = None
    vendor_address: str | None = None
    vendor_former_name: str | None = None
    date: Date | None = None
    date_raw: str | None = None
    due_date: Date | None = None
    due_date_raw: str | None = None
    currency: str = "USD"
    items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    tax_rate: float | None = None
    shipping: float | None = None
    total: float | None = None
    terms: str | None = None
    notes: str | None = None
    field_confidence: dict[str, float] = Field(default_factory=dict)
    source_file: str | None = None
    source_format: str | None = None
    corrections: list[str] = Field(default_factory=list, description="Normalizations applied while parsing")
    type_errors: list[str] = Field(default_factory=list, description="Fields whose value had the wrong type "
                                   "(a list, object or true/false where a number or name belongs); blocking")


class Flag(BaseModel):
    code: str
    severity: Severity
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING_HUMAN = "PENDING_HUMAN"


class Decision(BaseModel):
    status: DecisionStatus
    reasons: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    risk_score: int | None = Field(default=None, ge=0, le=100)
    critique_rounds: int = 0
    decided_by: str = "unknown"   # hard_rules | hard_hold | rejection_review | vp | vp+critic | deadlock | human | error | payment_guard
    # who stood behind the VP, critic and rejection review: "grok" (live) or "rules" (offline stand-ins written as
    # fixed rules). None when no agent was involved (hard rules, hard holds, a person).
    engine: Literal["grok", "rules"] | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)  # e.g. VP and critic positions on deadlock


class TraceEvent(BaseModel):
    agent: str
    step: str
    detail: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=time.time)


class InvoiceState(BaseModel):
    source: str
    raw_text: str | None = None
    invoice: Invoice | None = None
    extraction_attempts: int = 0
    extraction_mode: Literal["deterministic", "llm_repair", "failed"] | None = None
    flags: list[Flag] = Field(default_factory=list)
    total_usd: float | None = None
    repair_check: dict[str, Any] | None = None   # decision 14: is Grok's reading of an unreadable layout grounded?
    cross_check: dict[str, Any] | None = None    # decision 12: live, Grok's independent reading vs the parser's
    memo: dict[str, Any] | None = None           # decision 12: plain-language decision memo (Grok live, template offline)
    risk: dict[str, Any] | None = None       # filled by the risk agent
    decision: Decision | None = None         # filled by the approval agent
    payment: dict[str, Any] | None = None    # filled by the payment agent
    errors: list[str] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)

    def has_blocking(self) -> bool:
        return any(f.severity == Severity.BLOCK for f in self.flags)

    def pipeline_errors(self) -> list[str]:
        """Errors recorded before payment (a step that failed or crashed). Any of them blocks payment:
        the checks may not have run, so "no flags" does not mean "nothing wrong"."""
        return [e for e in self.errors if not e.startswith(("payment failed", "payment:"))]


_BY = {"hard_rules": "the hard rules", "hard_hold": "a hard hold rule", "error": "the fail-closed error rule",
       "payment_guard": "the payment guard", "human": "a person", "model_pin": "the model pin"}
_BY_ENGINE = {
    "vp": ("the VP agent (Grok)", "the VP rules stand-in"),
    "vp+critic": ("the VP and critic agents (Grok)", "the VP and critic rules stand-ins"),
    "deadlock": ("a VP/critic deadlock (Grok agents)", "a deadlock of the VP and critic rules stand-ins"),
    "rejection_review": ("the Grok rejection review", "the rejection review rules stand-in"),
}


def decided_by_label(d: "Decision | None", live: bool | None = None) -> str:
    """Who decided, in words a person reads. Offline stand-ins are written as fixed rules and are labelled as such,
    never as agents. `live` is only used for old records without an engine field."""
    if d is None:
        return "-"
    if d.decided_by in _BY_ENGINE:
        engine = d.engine or ("grok" if live else "rules" if live is not None else None)
        grok, rules = _BY_ENGINE[d.decided_by]
        return grok if engine == "grok" else rules if engine == "rules" else d.decided_by
    return _BY.get(d.decided_by, d.decided_by)
