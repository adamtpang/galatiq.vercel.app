"""Typed data passed between agents. Deterministic code and the LLM both produce these."""
from __future__ import annotations

import time
from datetime import date as Date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


class LineItem(BaseModel):
    sku_raw: str = Field(description="Item name exactly as printed on the invoice")
    sku: str | None = Field(default=None, description="Normalized inventory SKU, None if unknown")
    sku_confidence: float = 0.0
    qty: float
    unit_price: float | None = None
    amount: float | None = None
    note: str | None = None


class Invoice(BaseModel):
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
    decided_by: str = "unknown"   # hard_rules | vp | vp+critic | deadlock | human | error
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
    risk: dict[str, Any] | None = None       # filled by the risk agent
    decision: Decision | None = None         # filled by the approval agent
    payment: dict[str, Any] | None = None    # filled by the payment agent
    errors: list[str] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)

    def has_blocking(self) -> bool:
        return any(f.severity == Severity.BLOCK for f in self.flags)
