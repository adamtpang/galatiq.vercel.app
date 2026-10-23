"""Offline evals run in CI: ground truth coverage, scorer behaviour, and the offline numbers
pinned so a parser, policy or prompt change that moves them shows up as a test failure."""
import json
from types import SimpleNamespace as NS

import pytest

from evals import runner
from invoice_agents.graph import llm_usage
from invoice_agents.llm import GrokClient, usage_record
from invoice_agents.pipeline import collect

from .conftest import ROOT


@pytest.fixture(scope="module")
def offline(tmp_path_factory):
    return runner.evaluate("offline", workdir=tmp_path_factory.mktemp("evals"))


def test_ground_truth_covers_every_sample_and_extra():
    gt = runner.load_yaml("ground_truth.yaml")
    files = [runner.rel(p) for d in (runner.SAMPLES, runner.EXTRA) for p in collect(d)]
    assert sorted(gt) == sorted(files) and len(files) == 26
    for name, g in gt.items():
        assert set(runner.FIELDS) <= set(g), name


def test_known_sample_math_errors_recorded_as_printed():
    gt = runner.load_yaml("ground_truth.yaml")
    assert gt["data/invoices/invoice_1007.csv"]["total"] == 15525.00 and "$110" in gt["data/invoices/invoice_1007.csv"]["math_note"]
    assert gt["data/invoices/invoice_1013.json"]["total"] == 22562.80 and "$50" in gt["data/invoices/invoice_1013.json"]["math_note"]


def test_scorer_rules():
    from invoice_agents.models import Invoice, LineItem
    gt = {"vendor": "Widgets Inc.", "invoice_number": "INV-1002", "total": 10.0, "due_date": None,
          "line_items": [["WidgetA", 1], ["WidgetA", 2]], "ambiguous": {"due_date": "relative"}}
    inv = Invoice(vendor="widgets inc", number="1002", total=10.0,
                  items=[LineItem(sku_raw="Widget A", sku="WidgetA", sku_confidence=1.0, qty=2),
                         LineItem(sku_raw="WidgetA", sku="WidgetA", sku_confidence=1.0, qty=1)])
    s = runner.score_invoice(inv, gt)
    assert {f: v["status"] for f, v in s.items()} == {"vendor": "correct", "invoice_number": "correct", "total": "correct",
                                                       "line_items": "correct", "due_date": "ambiguous"}
    inv.items[0].qty = 3
    assert runner.score_invoice(inv, gt)["line_items"]["status"] == "wrong"
    assert all(v["status"] in ("failed", "ambiguous") for v in runner.score_invoice(None, gt).values())


def test_offline_extraction_numbers(offline):
    ex = offline["extraction"]["pipeline"]
    assert ex["files"] == 26
    # The parsers read all 20 samples and extras 2002, 2004, 2005 and 2006 exactly; 2001 and 2003 cannot be parsed offline and are held by the unreadable-layout hold.
    sample_misses = [m for m in ex["misses"] if m["file"].startswith("data/invoices/")]
    assert sample_misses == []
    assert ex["overall"] == {"correct": 119, "scored": 127, "accuracy": 0.937}
    assert {m["file"] for m in ex["misses"]} == {"data/invoices_extra/invoice_2001_email.txt",
                                                  "data/invoices_extra/invoice_2003_truncated.json"}


def test_offline_adversarial_numbers(offline):
    adv = offline["adversarial"]
    assert adv["total"] == 15 and adv["caught"] == 15 and adv["missed"] == []
    by = {c["file"]: c for c in adv["cases"]}
    assert by["invoice_3006_duplicate_new_number.txt"]["decision"] == "REJECTED"
    # 3002 (reworded injection) is caught by the generic injection patterns added in the reviewer pass
    assert {by[f]["decided_by"] for f in ("invoice_3001_injection_note.json", "invoice_3002_injection_reworded.txt",
                                          "invoice_3003_lookalike_vendor.txt", "invoice_3004_renamed_vendor.txt")} == {"hard_hold"}


def test_offline_makes_no_llm_calls(offline):
    assert all(b["calls"] == 0 for b in offline["cost_latency"]["batches"].values())


def test_committed_demo_agreement(offline):
    demo = offline["agreement"][0]
    # 1014 (EUR) is held offline since decision 22; the committed live demo (05a4ef5, before it) paid it.
    # 1010 is held offline since decision 23 (20% over catalog), as the live demo VP held it.
    # 1004 is SUPERSEDED offline since decision 24; the live demo (before it) logged it as REJECTED. Neither pays it.
    assert demo["invoices"] == 20 and demo["agree"] == 16
    assert sorted(d["file"] for d in demo["disagreements"]) == ["invoice_1001.txt", "invoice_1004.json",
                                                                "invoice_1004_revised.json", "invoice_1014.xml"]


def test_adversarial_as_a_separate_later_run(offline):
    sr = offline["adversarial_separate_run"]
    assert (sr["caught"], sr["total"], sr["missed"]) == (15, 15, [])
    d = sr["duplicate_3006"]
    assert d["decision"] == "REJECTED" and d["decided_by"] == "hard_rules" and "DUPLICATE_INVOICE" in d["flags"]
    assert "INV-1001" in d["reason"] and "earlier run" in d["reason"]


def test_disagreement_routing_metric(offline):
    r = offline["agreement"][0]["disagreement_routing"]
    demo = offline["agreement"][0]
    assert r["to_human"] == len(demo["disagreements"]) == demo["invoices"] - demo["agree"]
    assert all(x["paid_by"] in ("live", "offline") for x in r["paid_on_one_side"])
    assert r["paid_on_one_side_usd"] == round(sum(x["amount"] or 0 for x in r["paid_on_one_side"]), 2)


def test_usage_record_counts_every_call_and_reasoning_tokens():
    resp = NS(model="grok-4.7", usage=NS(prompt_tokens=1246, completion_tokens=1, cost_in_usd_ticks=22640000,
                                          completion_tokens_details=NS(reasoning_tokens=249),
                                          prompt_tokens_details=NS(cached_tokens=1152)))
    r = usage_record(resp, "VPOpinion", 0.5)
    assert (r["prompt_tokens"], r["cached_prompt_tokens"], r["completion_tokens"], r["reasoning_tokens"]) == (1246, 1152, 1, 249)
    pricing = runner.load_yaml("pricing.yaml")
    agg = llm_usage([r])
    # list price recomputed from docs.x.ai matches the billed ticks of this real response
    assert runner.price(agg, pricing) == pytest.approx(22640000 / 1e10)


def test_grok_client_logs_usage_for_tool_rounds_and_structured_calls():
    from .test_agentic import FakeOpenAI, call, reply
    fake = FakeOpenAI([reply(tool_calls=[call("1", "noop", {})]), reply(), reply(json.dumps({"score": 5}))])
    g = GrokClient(client=fake, sleep=lambda s: None)
    from invoice_agents.agents.risk import RiskReview
    from invoice_agents.llm import Tool
    msgs, calls = g.run_tools([{"role": "user", "content": "x"}], [Tool("noop", "", {"type": "object"}, lambda: {})])
    g.complete_structured(RiskReview, msgs)
    assert [u["purpose"] for u in g.usage_log] == ["tool_round", "tool_round", "RiskReview"]
    assert sum(u["prompt_tokens"] for u in g.usage_log) == 30


def test_report_renders(offline):
    assert "Extraction" in runner.detail_md(offline) and "| (c) Adversarial catch rate | 15/15" in runner.summary_md(offline, None)


def test_default_run_modifies_no_tracked_files(tmp_path):
    import shutil
    import subprocess
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    status = lambda: subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,  # noqa: E731
                                    capture_output=True, text=True).stdout
    before = status()
    assert runner.main([]) == 0
    assert status() == before
    assert (runner.OUT / "summary.md").exists()
    ignored = subprocess.run(["git", "check-ignore", "-q", str(runner.OUT / "summary.md")], cwd=ROOT)
    assert ignored.returncode == 0


def test_report_only_without_saved_results_exits_cleanly(tmp_path, capsys):
    from evals.runner import main
    assert main(["--report-only", "--out", str(tmp_path)]) == 2
    assert "run `python -m evals` first" in capsys.readouterr().err


def test_rel_never_writes_a_machine_path(tmp_path):
    from evals.runner import rel
    out = rel(tmp_path / "runs" / "main" / "trace.jsonl")
    assert str(tmp_path) not in out and not out.startswith("/") and out.endswith("main/trace.jsonl")


def test_unseen_layouts_are_held_not_rejected_offline(offline):
    un = offline["unseen"]
    assert un["total"] == 4 and un["rejected"] == 0 and un["held"] == 4 and un["paid"] == 0
    assert all(c["meets_expectation"] for c in un["cases"])
