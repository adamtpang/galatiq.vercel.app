"""Duplicates against stored history (decision 7 across runs), idempotent re-runs, and the review flow."""
import sqlite3
from pathlib import Path

import pytest

from invoice_agents import hitl
from invoice_agents.agents.payment import PaymentAgent
from invoice_agents.db import connect
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import OfflineClient
from invoice_agents.models import DecisionStatus
from invoice_agents.pipeline import collect

from .conftest import INVOICES, ROOT

ADV = ROOT / "data" / "invoices_adversarial"


def run(db, paths, run_id):
    ctx = make_context(llm=OfflineClient(), db=str(db), runs_dir=None, run_id=run_id, base_delay=0, sleep=lambda s: None)
    return {Path(s.source).name: s for s in run_batch(paths, ctx)}


def codes(st):
    return {f.code for f in st.flags}


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "inv.db"
    run(p, collect(INVOICES), "samples")
    return p


def test_content_duplicate_is_caught_in_a_later_separate_run(db):
    st = run(db, collect(ADV), "adversarial")["invoice_3006_duplicate_new_number.txt"]
    dup = [f for f in st.flags if f.code == "DUPLICATE_INVOICE"]
    assert st.decision.status == DecisionStatus.REJECTED and dup[0].evidence["match"] == "content"
    assert dup[0].evidence["original_invoice"] == "INV-1001" and "invoice_1001.txt, seen in an earlier run" in dup[0].message
    assert "paid $5,000.00" in dup[0].message


def test_rerunning_the_same_files_is_idempotent_not_fraud(db):
    first = run(db.parent / "fresh.db", collect(INVOICES), "fresh")
    again = run(db, collect(INVOICES), "again")
    for name, st in again.items():
        assert st.decision.status == first[name].decision.status, name
        assert codes(st) == codes(first[name]), name           # no new duplicate flags on a re-run
    paid = [n for n, s in again.items() if s.decision.status == DecisionStatus.APPROVED]
    assert paid and all(again[n].payment["status"] == "already_paid" for n in paid)


def test_single_file_reruns(db):
    st = run(db, [INVOICES / "invoice_1001.txt"], "r1")["invoice_1001.txt"]
    assert st.decision.status == DecisionStatus.APPROVED and st.payment["status"] == "already_paid"
    st = run(db, [INVOICES / "invoice_1011.pdf"], "r2")["invoice_1011.pdf"]
    assert st.payment["status"] == "already_paid" and "DUPLICATE_INVOICE" not in codes(st)
    st = run(db, [INVOICES / "invoice_1011.txt"], "r3")["invoice_1011.txt"]   # the copy stays a copy
    f = next(f for f in st.flags if f.code == "DUPLICATE_INVOICE")
    assert st.decision.status == DecisionStatus.REJECTED and f.evidence["match"] == "history"
    st = run(db, [INVOICES / "invoice_1004.json"], "r4")["invoice_1004.json"]   # its revision is on file
    assert "SUPERSEDED_BY_REVISION" in codes(st) and st.decision.status == DecisionStatus.SUPERSEDED
    assert st.payment["status"] == "not_paid"


def test_adversarial_then_samples_keeps_the_original(tmp_path):
    p = tmp_path / "x.db"
    run(p, [INVOICES / "invoice_1001.txt"], "a")
    run(p, [ADV / "invoice_3006_duplicate_new_number.txt"], "b")
    st = run(p, [INVOICES / "invoice_1001.txt"], "c")["invoice_1001.txt"]
    assert "DUPLICATE_INVOICE" not in codes(st) and st.payment["status"] == "already_paid"


def _write(path, number, total, qty=2):
    path.write_text(f"INVOICE\n\nVendor: Widgets Inc.\nInvoice Number: {number}\nDate: 2026-10-01\nDue Date: 2026-10-31\n\n"
                    f"Items:\n  WidgetA    qty: {qty}    unit price: $250.00\n\nSubtotal: ${total:,.2f}\nTax (0%): $0.00\n"
                    f"Total Amount: ${total:,.2f}\n\nPayment Terms: Net 30\n")
    return path


def test_same_number_different_content_in_a_later_run(tmp_path):
    p = tmp_path / "y.db"
    a = run(p, [_write(tmp_path / "a.txt", "INV-7001", 500.0)], "a")["a.txt"]
    assert a.decision.status == DecisionStatus.APPROVED
    b = run(p, [_write(tmp_path / "b.txt", "INV-7001", 750.0, qty=3)], "b")["b.txt"]
    assert "DUPLICATE_NUMBER_CONFLICT" in codes(b) and b.decision.status == DecisionStatus.REJECTED


def test_old_database_is_migrated(tmp_path):
    p = tmp_path / "old.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_number TEXT, revision TEXT, "
                  "vendor TEXT, total REAL, currency TEXT, source_file TEXT, fingerprint TEXT UNIQUE, status TEXT, "
                  "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    cols = {r[1] for r in connect(p).execute("PRAGMA table_info(invoices)")}
    assert {"run_id", "number_key", "base_fp", "content_key"} <= cols


def test_old_database_rows_are_backfilled_and_catch_a_later_duplicate(tmp_path):
    """An INV-1001 row stored before the history columns existed: on connect its keys are filled in,
    so 3006 (same content, new number) is rejected in a later run, and the original re-run is not."""
    p = tmp_path / "old.db"
    run(p, [INVOICES / "invoice_1001.txt"], "old")
    with sqlite3.connect(p) as c:   # make it look like a database from before the reviewer pass
        c.execute("UPDATE invoices SET run_id=NULL, number_key=NULL, base_fp=NULL, content_key=NULL")
    conn = connect(p)
    row = conn.execute("SELECT run_id, number_key, base_fp, content_key FROM invoices").fetchone()
    assert row["run_id"] == "legacy" and all(row[k] for k in ("number_key", "base_fp", "content_key"))
    st = run(p, [ADV / "invoice_3006_duplicate_new_number.txt"], "new")["invoice_3006_duplicate_new_number.txt"]
    dup = next(f for f in st.flags if f.code == "DUPLICATE_INVOICE")
    assert st.decision.status == DecisionStatus.REJECTED and dup.evidence["match"] == "content"
    again = run(p, [INVOICES / "invoice_1001.txt"], "again")["invoice_1001.txt"]
    assert "DUPLICATE_INVOICE" not in codes(again) and again.payment["status"] == "already_paid"


def test_review_approve_end_to_end_then_rerun(db):
    conn = connect(db)
    row = hitl.find(conn, "INV-1012")
    st = hitl.resolve(conn, row, approve=True, note="called vendor")
    st = PaymentAgent(conn, base_delay=0, sleep=lambda s: None).pay(st)
    assert st.payment["status"] == "paid" and st.payment["amount"] == 9975.0
    assert conn.execute("SELECT status FROM invoices WHERE source_file LIKE '%invoice_1012.pdf'").fetchone()[0] == "APPROVED"
    assert conn.execute("SELECT count(*) FROM audit_log WHERE event='human_approved'").fetchone()[0] == 1
    assert hitl.find(conn, "INV-1012") is None
    again = run(db, [INVOICES / "invoice_1012.pdf"], "rerun")["invoice_1012.pdf"]
    assert again.decision.status == DecisionStatus.APPROVED and again.decision.decided_by == "human"
    assert again.payment["status"] == "already_paid" and hitl.find(conn, "INV-1012") is None


def test_review_reject_end_to_end(db):
    conn = connect(db)
    st = hitl.resolve(conn, hitl.find(conn, "INV-1012"), approve=False, note="rename not confirmed")
    assert st.decision.status == DecisionStatus.REJECTED
    assert conn.execute("SELECT status FROM invoices WHERE source_file LIKE '%1012.pdf'").fetchone()[0] == "REJECTED"
    again = run(db, [INVOICES / "invoice_1012.pdf"], "rerun")["invoice_1012.pdf"]
    assert again.decision.status == DecisionStatus.REJECTED and again.payment["status"] == "not_paid"


def test_trace_paths_are_repo_relative(tmp_path):
    """Traces get committed, so absolute machine paths must not leak into them."""
    ctx = make_context(llm=OfflineClient(), db=str(tmp_path / "inv.db"), runs_dir=tmp_path / "runs", run_id="t",
                       base_delay=0, sleep=lambda s: None)
    run_batch([INVOICES / "invoice_1004.json", INVOICES / "invoice_1004_revised.json"], ctx)
    text = (tmp_path / "runs" / "t" / "trace.jsonl").read_text()
    assert '"data/invoices/invoice_1004.json"' in text
    assert str(ROOT) not in text


class RepairGrok:
    """Scripted Grok: rebuilds the truncated 2003 file, scores it low risk, and would approve it as VP."""
    name, available, model = "fake", True, "fake"

    def __init__(self):
        self.schemas = []

    def complete_structured(self, schema, messages, max_attempts=3):
        from invoice_agents.agents.approval import VPOpinion
        from invoice_agents.agents.ingestion import ExtractedInvoice, ExtractedItem
        from invoice_agents.agents.risk import RiskReview
        from invoice_agents.llm import LLMResult
        self.schemas.append(schema.__name__)
        if schema is ExtractedInvoice:
            v = ExtractedInvoice(invoice_number="INV-2003", vendor="Reliable Components Inc.", date="2026-10-18",
                                 due_date="2026-11-17", items=[ExtractedItem(name="WidgetA", qty=4, unit_price=250.0),
                                                               ExtractedItem(name="WidgetB", qty=2, unit_price=500.0)],
                                 total=2000.0)
        elif schema is RiskReview:
            v = RiskReview(score=5, extra_reasons=["looks routine"])
        else:
            v = VPOpinion(decision="approve", reasons=["fine"])
        return LLMResult(value=v, model="fake")


def test_decision_10_llm_repaired_invoice_is_held_with_original_shown(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    import main
    db = tmp_path / "inv.db"
    llm = RepairGrok()
    ctx = make_context(llm=llm, db=str(db), runs_dir=None, run_id="r", base_delay=0, sleep=lambda s: None)
    st = run_batch([ROOT / "data" / "invoices_extra" / "invoice_2003_truncated.json"], ctx)[0]
    assert st.extraction_mode == "llm_repair"
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and st.decision.decided_by == "hard_hold"
    assert st.decision.reasons[0].startswith("LLM_REPAIRED") and "VPOpinion" not in llm.schemas
    assert st.payment["status"] == "not_paid"
    monkeypatch.setenv("INVENTORY_DB", str(db))
    monkeypatch.setenv("COLUMNS", "160")
    out = CliRunner().invoke(main.app, ["review", "INV-2003"]).output
    raw = (ROOT / "data" / "invoices_extra" / "invoice_2003_truncated.json").read_text()
    assert "Original text, as received" in out and "Grok's reading" in out
    assert "Reliable Components" in out and raw.splitlines()[1].strip()[:20] in out
    assert "Total: $2,000.00" in out
    r = CliRunner().invoke(main.app, ["review", "INV-2003", "--approve", "--note", "checked the original"])
    assert r.exit_code == 0 and "paid $2,000.00" in r.output


def test_decision_10_off_switch(tmp_path):
    from invoice_agents.config import load_policy
    db = tmp_path / "inv.db"
    ctx = make_context(llm=RepairGrok(), db=str(db), runs_dir=None, run_id="r", base_delay=0, sleep=lambda s: None)
    ctx.policy = load_policy()
    ctx.policy["approval"]["hard_holds"]["llm_repaired"] = False
    st = run_batch([ROOT / "data" / "invoices_extra" / "invoice_2003_truncated.json"], ctx)[0]
    assert st.decision.decided_by == "vp"
