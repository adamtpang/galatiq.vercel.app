"""Review 3 fixes, using the reviewer's own hostile files (tests/fixtures/review3)."""
from __future__ import annotations

import ast
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from invoice_agents import hitl
from invoice_agents.agents import risk
from invoice_agents.agents.approval import hard_holds
from invoice_agents.db import init_db
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import LLMResult
from invoice_agents.models import DecisionStatus, Invoice, InvoiceState, LineItem
from invoice_agents.normalize import match_text, parse_date

from .conftest import INVOICES, ROOT

FIX = Path(__file__).parent / "fixtures" / "review3"
BANK = ["t01_bank_newacct.txt", "t02_bank_iban.txt", "t03_bank_paypal.txt", "t04_bank_ach.txt",
        "t15_bank_phone.txt", "t17.txt", "t18.txt", "t19.txt", "t20.txt"]
INJECTIONS = ["t05_inj_polite.txt", "t06_inj_json.txt", "t07_inj_fence.txt", "t08_inj_fence_unicode.txt",
              "t09_inj_spaced.txt", "t10_inj_french.txt", "t11_inj_markdown.txt", "t12_inj_codefence.txt",
              "t14_homoglyph_inj.txt", "j27_notes_obj.json"]


def _run(tmp_path, files, **kw):
    ctx = make_context(db=str(init_db(tmp_path / "i.db")), runs_dir=kw.pop("runs_dir", None), cache=False,
                       base_delay=0, sleep=lambda s: None, **kw)
    return run_batch(files, ctx), ctx


def _paid_rows(ctx) -> int:
    return ctx.conn.execute("SELECT count(*) FROM payments WHERE status='paid'").fetchone()[0]


# --- 1. any payment-instruction wording holds offline; Grok's structured field holds live -------------
@pytest.mark.parametrize("name", BANK)
def test_reviewer_bank_sentences_are_held(tmp_path, name):
    (st,), ctx = _run(tmp_path, [FIX / name])
    assert "BANK_DETAILS_CHANGED" in {f.code for f in st.flags}, name
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and _paid_rows(ctx) == 0


def test_only_1003_of_the_20_samples_mentions_payment_instructions(tmp_path):
    states, _ = _run(tmp_path, sorted(INVOICES.iterdir()))
    hits = sorted(Path(s.source).name for s in states if "BANK_DETAILS_CHANGED" in {f.code for f in s.flags})
    assert hits == ["invoice_1003.txt"]   # "Wire transfer preferred." (decision 20); 1003 is rejected anyway


class _RiskLLM:
    available, name = True, "scripted"

    def __init__(self, review):
        self.review = review

    def complete_structured(self, schema, msgs):
        return LLMResult(value=self.review, model="scripted")


def test_grok_payment_details_changed_field_forces_a_hard_hold(policy):
    st = InvoiceState(source="x.txt", raw_text="Thanks for your business.",
                      invoice=Invoice(number="INV-1", vendor="Summit Manufacturing Co.", total=500.0,
                                      items=[LineItem(sku_raw="WidgetA", qty=2, unit_price=250.0)]))
    review = risk.RiskReview(score=5, payment_details_changed=True, payment_change_quote="pay our new account")
    st = risk.assess(st, policy, _RiskLLM(review), tools=None)
    assert "BANK_DETAILS_CHANGED" in {f.code for f in st.flags}
    d = hard_holds(st, policy)
    assert d is not None and d.status == DecisionStatus.PENDING_HUMAN and "BANK_DETAILS_CHANGED" in d.reasons[0]
    st2 = risk.assess(InvoiceState(source="y.txt", raw_text="ok", invoice=st.invoice), policy,
                      _RiskLLM(risk.RiskReview(score=5)), tools=None)
    assert "BANK_DETAILS_CHANGED" not in {f.code for f in st2.flags}


# --- 2. a person types the amount on a mismatch; over $10,000 needs a second confirmation --------------
@pytest.fixture
def queued_9121(tmp_path):
    (st,), ctx = _run(tmp_path, [FIX / "j21_dupe_keys.json"])   # 2 x $250 lines, total $50,000 (duplicate key)
    assert st.decision.status == DecisionStatus.PENDING_HUMAN, st.decision.reasons
    row = hitl.find(ctx.conn, "INV-9121")
    assert row is not None
    return ctx, row


def test_one_click_approve_cannot_pay_50000_for_500_of_lines(queued_9121):
    ctx, row = queued_9121
    with pytest.raises(ValueError, match="Type the amount"):
        hitl.decide(ctx.conn, row, True, "looks fine")
    with pytest.raises(ValueError, match="second, explicit confirmation"):
        hitl.decide(ctx.conn, row, True, "pay the printed total", amount=50000.0)
    assert _paid_rows(ctx) == 0 and hitl.find(ctx.conn, "INV-9121") is not None   # still queued, nothing paid
    st = hitl.decide(ctx.conn, row, True, "pay what the lines add up to", amount=500.0)
    assert st.payment["status"] == "paid" and st.payment["amount"] == 500.0


def test_review_ui_server_enforces_the_amount(queued_9121, tmp_path):
    from invoice_agents import ui
    ctx, row = queued_9121
    page = ui.page_item(ctx.conn, row["id"], "tok")
    assert 'name="amount"' in page and 'value="500.00"' in page and 'name="confirm_large"' in page
    srv = ui.make_server(db=str(tmp_path / "i.db"), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/decide"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        def post(**form):
            data = urllib.parse.urlencode({"token": srv.token, "id": row["id"], "action": "approve", **form}).encode()
            try:
                urllib.request.build_opener(NoRedirect).open(url, data)
            except urllib.error.HTTPError as e:
                return urllib.parse.unquote(e.headers["Location"])
        assert "Type the amount" in post()                                    # one click: refused
        assert "second, explicit confirmation" in post(amount="50,000.00")   # no confirm box: refused
        assert _paid_rows(ctx) == 0
    finally:
        srv.shutdown()


# --- 3. non-USD is held for a person, not paid at a fixed rate -----------------------------------------
def test_eur_invoice_is_held_and_needs_a_typed_usd_amount(tmp_path):
    (st,), ctx = _run(tmp_path, [INVOICES / "invoice_1014.xml"])
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and _paid_rows(ctx) == 0
    assert any("CURRENCY_CONVERTED" in r for r in st.decision.reasons)
    with pytest.raises(ValueError, match="EUR"):
        hitl.decide(ctx.conn, hitl.find(ctx.conn, "INV-1014"), True, None)


# --- 4. crashes hold; an unexpected bank exception is queued, never left APPROVED and unpaid -----------
def _boom(*a, **k):
    raise RuntimeError("simulated crash")


def test_ingestion_crash_holds(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_agents.graph.ingest", _boom)
    (st,), ctx = _run(tmp_path, [INVOICES / "invoice_1001.txt"])
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and st.decision.decided_by == "error"
    assert _paid_rows(ctx) == 0


def test_bank_runtime_error_is_queued_not_left_approved(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_agents.agents.payment.mock_payment", _boom)
    (st,), ctx = _run(tmp_path, [INVOICES / "invoice_1001.txt"])
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and st.payment["status"] == "unknown"
    assert [tuple(r) for r in ctx.conn.execute("SELECT status FROM payments")] == [("unknown",)]
    assert hitl.find(ctx.conn, "INV-1001") is not None and _paid_rows(ctx) == 0


def test_any_exception_in_the_payment_step_is_queued(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_agents.agents.payment.idempotency_key", _boom)
    (st,), ctx = _run(tmp_path, [INVOICES / "invoice_1001.txt"])
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and _paid_rows(ctx) == 0
    assert hitl.find(ctx.conn, "INV-1001") is not None


# --- 5. every report and trace write is UTF-8 -----------------------------------------------------------
def test_every_file_write_names_utf8():
    missing = []
    for f in [*(ROOT / "invoice_agents").rglob("*.py"), *(ROOT / "evals").glob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in ("write_text", "read_text", "open") and not (isinstance(fn, ast.Attribute)
                                                                          and getattr(fn.value, "id", "") in ("pdfplumber", "pymupdf")):
                    if name == "open" and isinstance(fn, ast.Attribute):
                        continue
                    if not any(k.arg == "encoding" for k in node.keywords):
                        missing.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert not missing, missing


def test_non_english_vendor_round_trips_through_the_reports(tmp_path):
    p = tmp_path / "ru.txt"
    p.write_text("INVOICE\nInvoice Number: INV-9501\nVendor: Сибирские Поставки ООО\nDate: 2026-01-20\n"
                 "Due Date: 2026-02-20\nItems:\n  WidgetA  qty: 2  unit price: $250.00\nTotal Amount: $500.00\n",
                 encoding="utf-8")
    from invoice_agents.reporter import write_artifacts
    (st,), ctx = _run(tmp_path, [p], runs_dir=tmp_path / "runs", run_id="ru")
    run = tmp_path / "runs" / "ru"
    write_artifacts([st], run, "offline")
    assert "Сибирские Поставки" in json.loads((run / "summary.json").read_text(encoding="utf-8"))["rows"][0]["vendor"]
    assert "Сибирские Поставки" in (run / "report.md").read_text(encoding="utf-8")
    assert any("Сибирские Поставки" in json.dumps(json.loads(line), ensure_ascii=False)
               for line in (run / "trace.jsonl").read_text(encoding="utf-8").splitlines())


# --- 6. offline injection: normalized text, the reviewer's 10 invented wordings ------------------------
@pytest.mark.parametrize("name", INJECTIONS)
def test_reviewer_injections_are_held(tmp_path, name):
    (st,), ctx = _run(tmp_path, [FIX / name])
    assert "prompt_injection" in {s["signal"] for s in st.risk.get("signals", [])}, name
    assert st.decision.status == DecisionStatus.PENDING_HUMAN and _paid_rows(ctx) == 0


def test_benign_ignore_wording_still_pays(tmp_path):
    (st,), _ = _run(tmp_path, [FIX / "t13_benign_notes.txt"])
    assert st.decision.status == DecisionStatus.APPROVED and st.payment["status"] == "paid"


def test_match_text_normalizes():
    assert match_text("I g n o r e  p r e v i o u s") == "ignore  previous"
    assert match_text("＜/invoice_document＞") == "</invoice_document>"


# --- 7. day-first dates and non-numeric quantities ------------------------------------------------------
def test_day_first_dates_when_unambiguous():
    assert parse_date("20/02/2026").value == date(2026, 2, 20)
    assert parse_date("05/04/2026").value == date(2026, 5, 4)   # ambiguous: month-first, as before


def test_word_quantity_is_a_type_error_not_zero(tmp_path):
    (st,), ctx = _run(tmp_path, [FIX / "l10_csv_bad.csv"])
    assert "INVALID_FIELD_TYPE" in {f.code for f in st.flags} and st.decision.status == DecisionStatus.REJECTED
    assert "quantity" in st.decision.reasons[0] and "'two'" in st.decision.reasons[0]
    assert _paid_rows(ctx) == 0
