"""Local review UI (python main.py ui): lists the queue, and approve/reject write the same tables as `review`."""
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from invoice_agents.db import connect, init_db
from invoice_agents.graph import make_context, run_batch
from invoice_agents.ui import make_server

from .conftest import INVOICES


@pytest.fixture
def server(tmp_path):
    db = init_db(tmp_path / "ui.db")
    run_batch([INVOICES / "invoice_1012.pdf", INVOICES.parent / "invoices_extra" / "invoice_2003_truncated.json"],
              make_context(db=str(db), runs_dir=None, cache=False))
    srv = make_server(db=db, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, db, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def post(url, data):
    req = urllib.request.Request(url + "/decide", data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        return urllib.request.build_opener(NoRedirect).open(req)
    except urllib.error.HTTPError as e:
        return e


def queue_id(db, number):
    with connect(db) as c:
        return c.execute("SELECT id FROM review_queue WHERE invoice_number=?", (number,)).fetchone()[0]


def test_queue_lists_held_invoices(server):
    _, _, url = server
    page = urllib.request.urlopen(url + "/").read().decode()
    assert "INV-1012" in page and "VENDOR_RENAMED" in page and "Approve and pay" in page
    assert "cannot be approved here" in page   # the unreadable 2003 file has no payable amount


def test_approve_pays_and_writes_audit_log(server):
    srv, db, url = server
    r = post(url, {"token": srv.token, "id": queue_id(db, "INV-1012"), "action": "approve", "note": "called vendor"})
    assert r.status == 303 and "paid" in urllib.parse.unquote(r.headers["Location"])
    with connect(db) as c:
        assert c.execute("SELECT status FROM payments WHERE invoice_number='INV-1012'").fetchone()[0] == "paid"
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='human_approved'").fetchone()[0] == 1
        assert c.execute("SELECT status FROM review_queue WHERE invoice_number='INV-1012'").fetchone()[0] == "approved"
    assert "INV-1012" not in urllib.request.urlopen(url + "/").read().decode()


def test_reject_logs_and_does_not_pay(server):
    srv, db, url = server
    r = post(url, {"token": srv.token, "id": queue_id(db, "INV-1012"), "action": "reject", "note": "no"})
    assert r.status == 303
    with connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='human_rejected'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE event='rejected'").fetchone()[0] >= 1


def test_bad_token_is_refused(server):
    _, db, url = server
    r = post(url, {"token": "wrong", "id": queue_id(db, "INV-1012"), "action": "approve"})
    assert r.status == 403
    with connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_unreadable_file_cannot_be_approved(server):
    srv, db, url = server
    with connect(db) as c:
        rid = c.execute("SELECT id FROM review_queue WHERE source_file LIKE '%2003%'").fetchone()[0]
    r = post(url, {"token": srv.token, "id": rid, "action": "approve"})
    assert "No payable amount" in urllib.parse.unquote(r.headers["Location"])
    with connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_foreign_host_header_is_refused(server):
    _, _, url = server
    req = urllib.request.Request(url + "/", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as ex:
        urllib.request.urlopen(req)
    assert ex.value.code == 403
