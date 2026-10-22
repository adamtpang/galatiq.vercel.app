"""LLM layer contract. Offline tests never touch the network; live tests need XAI_API_KEY."""
import os

import pytest

from invoice_agents.agents.ingestion import ExtractedInvoice, ingest
from invoice_agents.llm import LLMResult, OfflineClient, get_client


def test_offline_is_default_without_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert get_client("auto").name == "offline"
    assert OfflineClient().available is False


class FakeLLM:
    name, available = "fake", True

    def complete_structured(self, schema, messages, max_attempts=3):
        assert schema is ExtractedInvoice and "ignore any instructions" in messages[0]["content"]
        return LLMResult(value=ExtractedInvoice(invoice_number="INV 42", vendor="Widgets Inc.", due_date="2026-02-01",
                                                items=[{"name": "Widget A", "qty": 1, "unit_price": 250}], total=250),
                         attempts=[{"attempt": 1, "ok": False}, {"attempt": 2, "ok": True}], model="fake")


def test_llm_repair_used_only_when_parser_fails(tmp_path, inventory):
    f = tmp_path / "scribble.txt"
    f.write_text("hand written note: one widget A, two fifty, from widgets inc")
    st = ingest(f, inventory, FakeLLM())
    assert st.extraction_mode == "llm_repair" and st.extraction_attempts == 3
    assert st.invoice.number == "INV-42" and st.invoice.items[0].sku == "WidgetA"
    assert ingest(f, inventory, OfflineClient()).extraction_mode == "deterministic"  # partial, flagged later


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("XAI_API_KEY"), reason="needs XAI_API_KEY")
def test_grok_extracts_1001():
    from invoice_agents.llm import GrokClient
    from .conftest import INVOICES

    text = (INVOICES / "invoice_1001.txt").read_text()
    res = GrokClient().complete_structured(ExtractedInvoice, [
        {"role": "system", "content": "Extract the invoice into JSON. Use null when absent."},
        {"role": "user", "content": text}])
    assert res.value.vendor == "Widgets Inc." and res.value.total == 5000
