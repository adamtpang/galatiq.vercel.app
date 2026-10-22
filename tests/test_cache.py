"""Decision cache (repeatability) and model pin, with a scripted Grok that answers differently on every call."""
from pathlib import Path

from invoice_agents.agents.approval import CriticOpinion, VPOpinion
from invoice_agents.agents.risk import RiskReview
from invoice_agents.cache import cache_key, normalized_content
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import LLMResult
from invoice_agents.models import DecisionStatus

from .conftest import INVOICES


class FlipGrok:
    """Approves on odd calls and holds on even ones: without a cache every run can differ."""
    name, available = "grok", True

    def __init__(self, model="grok-4.7", reports=None):
        self.model, self.reports, self.calls = model, reports or model, 0
        self.usage_log = []

    def complete_structured(self, schema, messages, max_attempts=3):
        self.calls += 1
        self.usage_log.append({"purpose": schema.__name__, "model": self.reports, "latency_s": 0, "prompt_tokens": 0,
                               "cached_prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
                               "cost_in_usd_ticks": None})
        if schema is RiskReview:
            v = RiskReview(score=self.calls % 7, extra_reasons=[f"call {self.calls}"])
        elif schema is CriticOpinion:
            v = CriticOpinion(verdict="sign_off", reason="ok")
        else:
            v = VPOpinion(decision="approve" if self.calls % 2 else "hold", reasons=[f"call {self.calls}"])
        return LLMResult(value=v, model=self.reports)


FILES = [INVOICES / "invoice_1001.txt", INVOICES / "invoice_1006.csv", INVOICES / "invoice_1015.csv"]


def decisions(db, llm, cache=True, run_id="r"):
    ctx = make_context(llm=llm, db=str(db), runs_dir=None, run_id=run_id, cache=cache, base_delay=0, sleep=lambda s: None)
    return {Path(s.source).name: (s.decision.status.value, s.decision.reasons, (s.risk or {}).get("score"))
            for s in run_batch(FILES, ctx)}


def test_cache_makes_a_rerun_identical_and_skips_grok(tmp_path):
    g = FlipGrok()
    first = decisions(tmp_path / "a.db", g, run_id="one")
    n = g.calls
    assert n > 0
    again = decisions(tmp_path / "a.db", g, run_id="two")
    assert again == first and g.calls == n          # every Grok answer reused, nothing new called


def test_no_cache_calls_grok_again_and_can_differ(tmp_path):
    g = FlipGrok()
    first = decisions(tmp_path / "b.db", g, cache=False, run_id="one")
    n = g.calls
    again = decisions(tmp_path / "b.db", g, cache=False, run_id="two")
    assert g.calls == 2 * n and again != first      # the scripted model drifts; the cache is what makes reruns equal


def test_cache_key_depends_on_content_and_model_not_line_endings(tmp_path):
    a, b, c = tmp_path / "a.txt", tmp_path / "b.txt", tmp_path / "c.txt"
    text = (INVOICES / "invoice_1001.txt").read_text()
    a.write_text(text)
    b.write_bytes(text.replace("\n", "  \r\n").encode())
    c.write_text(text.replace("$5,000.00", "$5,001.00"))
    assert normalized_content(a) == normalized_content(b)
    assert cache_key(a, "grok-4.7") == cache_key(b, "grok-4.7") != cache_key(c, "grok-4.7")
    assert cache_key(a, "grok-4.7") != cache_key(a, "grok-5")


def test_model_pin_holds_when_the_api_reports_another_model(tmp_path):
    g = FlipGrok(model="grok-4.7", reports="grok-4.7-preview")
    ctx = make_context(llm=g, db=str(tmp_path / "c.db"), runs_dir=None, run_id="pin", base_delay=0, sleep=lambda s: None)
    states = {Path(s.source).name: s for s in run_batch(FILES, ctx)}
    for st in states.values():
        assert "MODEL_MISMATCH" in {f.code for f in st.flags}
        assert st.decision.status != DecisionStatus.APPROVED and not (st.payment or {}).get("status") == "paid"
    held = [s for s in states.values() if s.decision.decided_by == "model_pin"]
    assert held and all("grok-4.7-preview" in s.decision.reasons[0] for s in held)


def test_model_pin_is_quiet_when_the_model_matches(tmp_path):
    g = FlipGrok()
    ctx = make_context(llm=g, db=str(tmp_path / "d.db"), runs_dir=None, run_id="ok", base_delay=0, sleep=lambda s: None)
    for st in run_batch(FILES, ctx):
        assert "MODEL_MISMATCH" not in {f.code for f in st.flags}
        assert any(e.step == "model_pin" and e.detail["returned_models"] == ["grok-4.7"] for e in st.trace)
