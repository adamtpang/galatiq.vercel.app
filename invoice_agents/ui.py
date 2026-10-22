"""Local review UI: `python main.py ui` (stdlib only, bound to 127.0.0.1).

Lists the human review queue with the reason, flags, total and the agents' memo, shows one invoice in
detail (the original text next to Grok's reading when Grok rebuilt it), and has Approve and Reject
buttons. A decision goes through hitl.decide, the same code as `python main.py review`, so it writes
the same review_queue, invoices, payments and audit_log rows.

Safety: it listens on localhost only, checks the Host header, and every POST must carry a token
generated when the server starts (so another web page cannot submit a decision).
"""
from __future__ import annotations

import html
import json
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import hitl
from .db import connect

CSS = """body{font-family:system-ui,sans-serif;margin:2rem;max-width:1100px;color:#111}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:.5rem;text-align:left;
vertical-align:top}th{background:#f5f5f5}.r{color:#555;font-size:.9rem}code{background:#f3f3f3;padding:0 .2rem}
pre{white-space:pre-wrap;background:#fafafa;border:1px solid #eee;padding:.75rem;font-size:.85rem}
button{padding:.35rem .8rem;margin-right:.3rem;cursor:pointer}.ok{background:#e7f6ea}.no{background:#fde8e8}
.msg{background:#eef4ff;padding:.6rem;border-radius:6px}.cols{display:grid;grid-template-columns:1fr 1fr;gap:1rem}"""

e = html.escape


def _state(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["state_json"])
    except (TypeError, ValueError):
        return {}


def payable(st: dict) -> bool:
    inv = st.get("invoice") or {}
    amt = st.get("total_usd") if st.get("total_usd") is not None else inv.get("total")
    return bool(inv.get("items")) and isinstance(amt, (int, float)) and amt > 0


def _money(st: dict) -> str:
    amt = st.get("total_usd") if st.get("total_usd") is not None else (st.get("invoice") or {}).get("total")
    return f"${amt:,.2f}" if isinstance(amt, (int, float)) else "not read"


def _buttons(row: sqlite3.Row, st: dict, token: str) -> str:
    ok = payable(st)
    approve = ('<button class="ok" name="action" value="approve">Approve and pay</button>' if ok else
               '<span class="r">No payable amount was read, so it cannot be approved here; reject it or enter it by hand.</span><br>')
    return (f'<form method="post" action="/decide"><input type="hidden" name="token" value="{e(token)}">'
            f'<input type="hidden" name="id" value="{row["id"]}"><input name="note" placeholder="Note (optional)" size="28"> '
            f'{approve}<button class="no" name="action" value="reject">Reject</button></form>')


def page_queue(conn: sqlite3.Connection, token: str, msg: str | None) -> str:
    rows = hitl.pending(conn)
    out = [f"<h1>Review queue</h1><p class='r'>{len(rows)} invoice(s) waiting. Decisions here write the same tables "
           "as <code>python main.py review</code>.</p>"]
    if msg:
        out.append(f"<p class='msg'>{e(msg)}</p>")
    if not rows:
        out.append("<p>Review queue is empty.</p>")
    else:
        out.append("<table><tr><th>Invoice</th><th>Total</th><th>Why it is held</th><th>Decision</th></tr>")
        for r in rows:
            st = _state(r)
            flags = ", ".join(f["code"] for f in st.get("flags", []) if f.get("severity") in ("warn", "block"))
            memo = (st.get("memo") or {}).get("text")
            out.append(
                f"<tr><td><a href='/item/{r['id']}'>{e(r['invoice_number'] or '(no number)')}</a><br>"
                f"<span class='r'>{e(r['vendor'] or 'vendor not read')}<br>{e(Path(r['source_file'] or '').name)}</span></td>"
                f"<td>{e(_money(st))}</td><td>{e(r['reason'] or '')}<br><span class='r'>Flags: {e(flags or 'none')}</span>"
                + (f"<br><span class='r'>Memo: {e(memo)}</span>" if memo else "")
                + f"</td><td>{_buttons(r, st, token)}</td></tr>")
        out.append("</table>")
    return _wrap("Review queue", "".join(out))


def page_item(conn: sqlite3.Connection, row_id: int, token: str) -> str | None:
    r = hitl.find_id(conn, row_id)
    if r is None:
        return None
    st = _state(r)
    inv = st.get("invoice") or {}
    items = "".join(f"<tr><td>{e(str(li.get('sku') or li.get('sku_raw')))}</td><td>{li.get('qty')}</td>"
                    f"<td>{li.get('unit_price')}</td></tr>" for li in inv.get("items", []))
    flags = "".join(f"<tr><td>{e(f['severity'])}</td><td>{e(f['code'])}</td><td>{e(f['message'])}</td></tr>"
                    for f in st.get("flags", []))
    reading = (f"<h3>Agents' reading</h3><p>Vendor: {e(str(inv.get('vendor')))}; number: {e(str(inv.get('number')))}; "
               f"total: {e(_money(st))}; due: {e(str(inv.get('due_date_raw')))}</p>"
               f"<table><tr><th>Item</th><th>Qty</th><th>Unit price</th></tr>{items}</table>")
    raw = st.get("raw_text")
    body = (f"<p><a href='/'>Back to the queue</a></p><h1>{e(r['invoice_number'] or '(no number)')}</h1>"
            f"<p>{e(r['reason'] or '')}</p>"
            + (f"<p class='msg'>Memo: {e(st['memo']['text'])}</p>" if st.get("memo") else "")
            + (f"<div class='cols'><div><h3>Original file</h3><pre>{e(raw)}</pre></div><div>{reading}</div></div>"
               if raw else reading)
            + f"<h3>Flags</h3><table><tr><th>Severity</th><th>Code</th><th>Message</th></tr>{flags}</table>"
            + f"<h3>Decide</h3>{_buttons(r, st, token)}")
    return _wrap(r["invoice_number"] or "Invoice", body)


def _wrap(title: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{e(title)}: Acme invoice review</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def make_server(db: str | Path | None = None, host: str = "127.0.0.1", port: int = 8765,
                chaos: float = 0.0) -> ThreadingHTTPServer:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):   # quiet; decisions go to the audit log
            pass

        def _host_ok(self) -> bool:
            h = (self.headers.get("Host") or "").split(":")[0]
            return h in ("127.0.0.1", "localhost")

        def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, "Forbidden host", "text/plain")
            u = urlparse(self.path)
            conn = connect(db)
            try:
                if u.path == "/":
                    msg = parse_qs(u.query).get("msg", [None])[0]
                    return self._send(200, page_queue(conn, token, msg))
                if u.path.startswith("/item/") and u.path[6:].isdigit():
                    page = page_item(conn, int(u.path[6:]), token)
                    return self._send(200, page) if page else self._send(404, "Not in the queue", "text/plain")
                return self._send(404, "Not found", "text/plain")
            finally:
                conn.close()

        def do_POST(self):
            if not self._host_ok() or urlparse(self.path).path != "/decide":
                return self._send(403, "Forbidden", "text/plain")
            n = min(int(self.headers.get("Content-Length") or 0), 100_000)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace")).items()}
            if not secrets.compare_digest(form.get("token", ""), token):
                return self._send(403, "Bad or missing token; reload the page", "text/plain")
            action, note = form.get("action"), (form.get("note") or "").strip() or None
            if action not in ("approve", "reject") or not form.get("id", "").isdigit():
                return self._send(400, "Bad request", "text/plain")
            conn = connect(db)
            try:
                row = hitl.find_id(conn, int(form["id"]))
                if row is None:
                    msg = "That invoice is no longer in the queue."
                else:
                    try:
                        s = hitl.decide(conn, row, action == "approve", note, chaos=chaos)
                        p = s.payment or {}
                        num = s.invoice.number if s.invoice else "invoice"
                        msg = (f"{num}: approved by a person and paid ${p['amount']:,.2f}." if p.get("status") == "paid"
                               else f"{num}: approved; already paid earlier, not paid again." if p.get("status") == "already_paid"
                               else f"{num}: approved but the payment failed: {'; '.join(p.get('errors', []))}"
                               if p.get("status") == "failed"
                               else f"{num}: {s.decision.status.value.lower()}; not paid, written to the audit log.")
                    except ValueError as ex:
                        msg = str(ex)
            finally:
                conn.close()
            return self._send(303, "", headers={"Location": "/?msg=" + quote(msg)})

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.token = token  # type: ignore[attr-defined]
    return srv
