"""End to end over all 20 samples through the LangGraph pipeline (offline, fresh DB)."""
from pathlib import Path

import pytest
import yaml

from invoice_agents.agents import approval
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import OfflineClient
from invoice_agents.pipeline import collect

from .conftest import INVOICES

GOLDEN = yaml.safe_load((Path(__file__).parent / "golden.yaml").read_text())
APPROVAL_BUILT = not getattr(approval, "IS_STUB", False)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    d = tmp_path_factory.mktemp("golden")
    ctx = make_context(llm=OfflineClient(), db=str(d / "inv.db"), runs_dir=d / "runs", run_id="golden")
    states = run_batch(collect(INVOICES), ctx)
    return {Path(s.source).name: s for s in states}, ctx


def test_golden_covers_all_files():
    assert sorted(GOLDEN) == sorted(p.name for p in collect(INVOICES)) and len(GOLDEN) == 20


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_golden_decision(results, name):
    exp = GOLDEN[name]
    if exp.get("needs") == "approval_agent" and not APPROVAL_BUILT:
        pytest.xfail("approval agent pending")
    s = results[0][name]
    assert s.decision.status.value == exp["decision"], s.decision.reasons
    codes = {f.code for f in s.flags}
    assert set(exp.get("must_flag", [])) <= codes
    if "paid" in exp:
        assert s.payment["status"] == "paid" and s.payment["amount"] == pytest.approx(exp["paid"])
    else:
        assert (s.payment or {}).get("status") != "paid"


def test_trace_written(results):
    _, ctx = results
    lines = (ctx.run_dir / "trace.jsonl").read_text().splitlines()
    assert len(lines) > 20 and '"agent": "ingestion"' in lines[0]


def test_never_pays_twice_on_rerun(results, tmp_path):
    _, ctx = results
    again = run_batch(collect(INVOICES), make_context(llm=OfflineClient(), db=str(Path(ctx.conn.execute(
        "PRAGMA database_list").fetchone()[2])), runs_dir=None))
    assert all((s.payment or {}).get("status") != "paid" for s in again)
