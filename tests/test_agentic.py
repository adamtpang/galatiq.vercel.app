"""Self-correction and tool-use loops, exercised offline with a fake OpenAI-compatible client.

The fake replays scripted responses and records every request, so we can check exactly what
the real GrokClient sends back to the model (validation errors, tool results)."""
import json
from types import SimpleNamespace as NS

import pytest

from invoice_agents.agents import risk
from invoice_agents.agents.ingestion import ingest
from invoice_agents.db import connect
from invoice_agents.llm import GrokClient, LLMOutputError, LLMUnavailable

from .conftest import ROOT

EXTRA = ROOT / "data" / "invoices_extra"


def reply(content=None, tool_calls=None, model="grok-test-0001"):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=10, completion_tokens=5), model=model)


def call(id_, name, args):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


class FakeOpenAI:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=str)))
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


GOOD = {"invoice_number": "W-2001", "vendor": "Widgets Inc.", "date": None, "due_date": "Nov 15 2026",
        "currency": "USD", "items": [{"name": "WidgetA", "qty": 6, "unit_price": 250},
                                     {"name": "GadgetX", "qty": 2, "unit_price": 750}], "total": 3000}
BAD = dict(GOOD, items=[{"name": "WidgetA", "qty": "six", "unit_price": 250}])   # qty must be a number


def test_ingestion_self_corrects_after_schema_error(inventory):
    fake = FakeOpenAI([reply(json.dumps(BAD)), reply(json.dumps(GOOD))])
    st = ingest(EXTRA / "invoice_2001_email.txt", inventory, GrokClient(client=fake, sleep=lambda s: None))
    assert st.extraction_mode == "llm_repair"
    repair = next(e for e in st.trace if e.step == "llm_repair")
    assert [a["ok"] for a in repair.detail["attempts"]] == [False, True]
    assert "qty" in repair.detail["attempts"][0]["error"]
    # the validation error went back to the model as the last message of the second request
    second = fake.requests[1]["messages"]
    assert second[-2]["role"] == "assistant" and "six" in second[-2]["content"]
    assert "failed validation" in second[-1]["content"] and "qty" in second[-1]["content"]
    assert repair.detail["model"] == "grok-test-0001"          # the id the API reported
    inv = st.invoice
    assert inv.vendor == "Widgets Inc." and inv.total == 3000
    assert [(i.sku, i.qty) for i in inv.items] == [("WidgetA", 6), ("GadgetX", 2)]


def test_ingestion_gives_up_after_three_bad_answers(inventory):
    fake = FakeOpenAI([reply("not json"), reply(json.dumps(BAD)), reply("{}" + "x")])
    st = ingest(EXTRA / "invoice_2003_truncated.json", inventory, GrokClient(client=fake, sleep=lambda s: None))
    assert st.extraction_mode == "failed" and any("LLM repair failed" in e for e in st.errors)
    assert len(fake.requests) == 3


def test_api_errors_are_retried_then_reported():
    fake = FakeOpenAI([RuntimeError("503"), RuntimeError("503"), RuntimeError("503")])
    with pytest.raises(LLMUnavailable):
        GrokClient(client=fake, sleep=lambda s: None).run_tools([{"role": "user", "content": "x"}], [])


def test_risk_agent_calls_tools_and_cannot_lower_score(db_file, inventory, policy):
    st = ingest(EXTRA / "invoice_2002_injection.txt", inventory)
    from invoice_agents.validation import validate
    st = validate(st, inventory, policy)
    fake = FakeOpenAI([
        reply(tool_calls=[call("c1", "lookup_vendor", {"name": "Northwind Supply Partners"}),
                          call("c2", "query_inventory", {"item": "WidgetB"})]),
        reply(tool_calls=[call("c3", "no_such_tool", {})]),
        reply(content="done"),
        reply(json.dumps({"score": 0, "extra_reasons": ["Vendor not found in the vendor master"]})),
    ])
    with connect(db_file) as conn:
        st = risk.assess(st, policy, GrokClient(client=fake, sleep=lambda s: None), risk.risk_tools(inventory, conn))
    calls = [e.detail for e in st.trace if e.step == "tool_call"]
    assert [c["tool"] for c in calls] == ["lookup_vendor", "query_inventory", "no_such_tool"]
    assert calls[0]["result"]["found"] is False
    assert calls[1]["result"] == {"found": True, "item": "WidgetB", "stock": 10, "catalog_unit_price_usd": 500.0}
    assert "error" in calls[2]["result"]
    # tool results were sent back to the model with matching ids
    tool_msgs = [m for m in fake.requests[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]
    # the model asked for score 0 (as the injected text demands); the rule score stands
    r = st.risk
    assert r["llm"]["score"] == 0 and r["score"] == r["deterministic_score"] >= 80
    assert "prompt_injection" in {s["signal"] for s in r["signals"]}


def test_offline_risk_flags_prompt_injection(inventory, policy):
    from invoice_agents.validation import validate
    st = validate(ingest(EXTRA / "invoice_2002_injection.txt", inventory), inventory, policy)
    st = risk.assess(st, policy)
    assert {"prompt_injection", "wire_transfer", "unknown_vendor"} <= {s["signal"] for s in st.risk["signals"]}


def test_structured_output_raises_after_max_attempts():
    from invoice_agents.agents.risk import RiskReview
    fake = FakeOpenAI([reply("{}"), reply("{}"), reply("{}")])
    with pytest.raises(LLMOutputError) as e:
        GrokClient(client=fake, sleep=lambda s: None).complete_structured(RiskReview, [])
    assert len(e.value.attempts) == 3 and not any(a["ok"] for a in e.value.attempts)
