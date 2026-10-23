"""Console summary table and run artifacts (summary.json, report.md)."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .models import InvoiceState, Severity, decided_by_label

STATUS_STYLE = {"APPROVED": "bold green", "REJECTED": "bold red", "PENDING_HUMAN": "bold yellow"}


def money(v: float | None) -> str:
    return "-" if v is None else f"${v:,.2f}"


def row(s: InvoiceState) -> dict:
    inv, d, p = s.invoice, s.decision, s.payment or {}
    blocks = [f.code for f in s.flags if f.severity == Severity.BLOCK]
    warns = [f.code for f in s.flags if f.severity == Severity.WARN]
    return {
        "file": Path(s.source).name,
        "invoice": (inv.number or "-") + (f" {inv.revision}" if inv and inv.revision else "") if inv else "-",
        "vendor": (inv.vendor if inv else None) or "-",
        "total_usd": s.total_usd,
        "risk": (s.risk or {}).get("score"),
        "block_flags": blocks,
        "warn_flags": warns,
        "decision": d.status.value if d else "-",
        "decided_by": d.decided_by if d else "-",
        "engine": d.engine if d else None,
        "decided_by_label": decided_by_label(d),
        "critique_rounds": d.critique_rounds if d else 0,
        "payment": p.get("status", "-") + (f" {money(p['amount'])}" if p.get("status") in ("paid", "already_paid") else ""),
        "reason": (d.reasons[0] if d and d.reasons else ""),
        "conditions": d.conditions if d else [],
        "errors": s.errors,
        "memo": (s.memo or {}).get("text"),
        "memo_by": (s.memo or {}).get("by"),
        "grok_calls": grok_calls(s),
    }


def grok_calls(s: InvoiceState) -> int:
    """Grok API calls made for this invoice (live; 0 offline or when every answer came from the cache)."""
    return sum((e.detail.get("llm") or {}).get("calls", 0) for e in s.trace if e.step == "node_done")


def grok_ratio(states: list[InvoiceState]) -> str | None:
    """Live: how many invoices Grok worked on, and how many the hard rules decided whatever Grok said."""
    used = [s for s in states if any(e.step in ("grok_cross_check", "llm_repair", "memo") and
                                     (e.detail.get("by") == "grok" or e.step != "memo") for e in s.trace)]
    if not used:
        return None
    hard = sum(1 for s in states if s.decision and s.decision.decided_by == "hard_rules")
    calls = sum(grok_calls(s) for s in states)
    return (f"Grok worked on {len(used)} of {len(states)} invoices ({calls} API calls this run; reused cached answers "
            f"are not counted as calls). Hard rules rejected {hard} of them; Grok cannot turn those into a payment: it "
            f"cross-checked the reading, reviewed each rejection (it can only escalate one to a person) and wrote the memo.")


WIDE = 140   # below this terminal width the table drops the Vendor, Risk, Flags and By columns


def print_summary(states: list[InvoiceState], console: Console, mode: str, run_dir: Path | None) -> None:
    wide = console.width >= WIDE
    cols = ["File", "Invoice", "Vendor", "Total USD", "Risk", "Flags", "Decision", "By", "Payment", "Reason"]
    if not wide:   # 80 columns: total and payment go under the decision so the reason gets the room
        cols = ["File", "Decision", "Reason"]
    t = Table(title=f"Run summary ({mode})", show_lines=False)
    for c in cols:
        if c == "Reason":
            t.add_column(c, overflow="fold", ratio=1)
        elif c == "Decision" and not wide:   # status, then the payment on its own lines: wrapped, never cut
            t.add_column(c, no_wrap=False, overflow="fold", min_width=12, max_width=14)
        else:
            t.add_column(c, no_wrap=True, overflow="ellipsis", max_width=None if wide else 17)
    for s in states:
        r = row(s)
        flags = ", ".join(r["block_flags"][:3]) or (", ".join(r["warn_flags"][:2]) and "warn: " + ", ".join(r["warn_flags"][:2])) or "-"
        decision = f"[{STATUS_STYLE.get(r['decision'], '')}]{r['decision'].replace('PENDING_HUMAN', 'HELD')}[/]"
        if not wide:
            decision += "\n" + payment_cell(r)
        cells = {"File": r["file"].removeprefix("invoice_"), "Invoice": r["invoice"], "Vendor": r["vendor"],
                 "Total USD": money(r["total_usd"]), "Risk": "-" if r["risk"] is None else str(r["risk"]),
                 "Flags": flags, "Decision": decision, "By": short_by(r), "Payment": r["payment"],
                 "Reason": textwrap.shorten(r["reason"], width=160 if wide else 100, placeholder=" ...")}
        t.add_row(*(cells[c] for c in cols))
    console.print(t)
    if not wide:
        console.print(f"[dim]Narrow terminal ({console.width} columns): full table in report.md and summary.json.[/]")
    console.print(summary_line(states))
    if mode == "offline":
        console.print("[dim]Offline: no model was called. The risk review, VP, critic and rejection review are rules "
                      "stand-ins (fixed rules written from the agents' prompts), not agents; the memo is a template.[/]")
    late = [Path(s.source).name.removeprefix("invoice_") for s in states if any(f.code == "PAST_DUE" for f in s.flags)]
    if late:
        console.print(f"[yellow]Past due[/] when processed (warning only, changes no decision): {len(late)} of "
                      f"{len(states)}: {', '.join(late[:8])}{', ...' if len(late) > 8 else ''}")
    ratio = grok_ratio(states)
    if ratio:
        console.print(ratio)
    if run_dir:
        console.print(f"Trace: {run_dir / 'trace.jsonl'}")


def payment_cell(r: dict) -> str:
    """Narrow table: payment status, then the amount on its own line, e.g. 'already paid' / '$5,000.00'."""
    p = r["payment"]
    if p.startswith(("paid", "already_paid")):
        status, _, amt = p.partition(" ")
        return status.replace("_", " ") + ("\n" + amt if amt else "")
    if p.startswith("failed"):
        return "PAYMENT\nFAILED\n" + money(r["total_usd"])
    return money(r["total_usd"])


def short_by(r: dict) -> str:
    return r["decided_by"] + (f" ({r['engine']})" if r.get("engine") else "")


def summary_line(states: list[InvoiceState]) -> str:
    """One line: counts, money paid, and failed payments (queued for a person, PAYMENT_FAILED)."""
    counts = {k: sum(row(s)["decision"] == k for s in states) for k in STATUS_STYLE}
    paid = sum((s.payment or {}).get("amount", 0) for s in states if (s.payment or {}).get("status") == "paid")
    failed = [s for s in states if (s.payment or {}).get("status") == "failed"]
    line = (f"{len(states)} invoice{'' if len(states) == 1 else 's'}: {counts['APPROVED']} approved, "
            f"{counts['REJECTED']} rejected, {counts['PENDING_HUMAN']} pending human review. Paid this run: {money(paid)}.")
    if failed:
        amt = sum((s.payment or {}).get("amount", 0) for s in failed)
        line += (f" {len(failed)} payment{'' if len(failed) == 1 else 's'} FAILED after retries ({money(amt)} not paid); "
                 "queued for review as PAYMENT_FAILED, rerun or approve in the review queue to retry.")
    return line


def git_commit() -> str | None:
    """Short commit of the code that made this run (None outside a git checkout)."""
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent.parent,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def write_artifacts(states: list[InvoiceState], run_dir: Path | None, mode: str, model: str | None = None) -> None:
    if not run_dir:
        return
    rows = [row(s) for s in states]
    (run_dir / "summary.json").write_text(json.dumps({"mode": mode, "model": model, "commit": git_commit(),
                                                      "grok": grok_ratio(states), "rows": rows}, indent=2, default=str))
    lines = [f"# Run {run_dir.name} ({mode}{', ' + model if model else ''})", "",
             "| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        reason = r["reason"].replace("|", "/")
        lines.append(f"| {r['file']} | {r['invoice']} | {r['vendor']} | {money(r['total_usd'])} | {r['risk']} | "
                     f"{', '.join(r['block_flags']) or '-'} | {r['decision']} | {r['decided_by_label']} | "
                     f"{r['critique_rounds']} | {r['payment']} | {reason} |")
    lines += ["", "## Decision memos", ""] + [f"- **{r['file']}** ({r['memo_by']}): {r['memo']}" for r in rows if r["memo"]]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")


# --- review: one queued invoice -------------------------------------------------------------
RAW_SHOWN = 6000   # characters of the original shown in the terminal


def grok_reading(s: InvoiceState) -> str:
    """The invoice as extracted, one field per line, in the order a person checks it against the original."""
    inv = s.invoice
    if inv is None:
        return "(nothing extracted)"
    lines = [f"Invoice number: {inv.number or '-'}", f"Vendor: {inv.vendor or '-'}",
             f"Date: {inv.date or inv.date_raw or '-'}", f"Due date: {inv.due_date or inv.due_date_raw or '-'}",
             f"Currency: {inv.currency}", "Items:"]
    lines += [f"  {li.sku_raw}  qty {li.qty:g}  unit price {money(li.unit_price)}" + (f"  ({li.note})" if li.note else "")
              for li in inv.items] or ["  (none)"]
    lines += [f"Subtotal: {money(inv.subtotal)}", f"Tax: {money(inv.tax)}", f"Total: {money(inv.total)}",
              f"Terms: {inv.terms or '-'}", f"Notes: {inv.notes or '-'}"]
    return "\n".join(lines)


def print_review(s: InvoiceState, reason: str | None, console: Console | None = None) -> None:
    console = console or Console()
    inv = s.invoice
    console.print(f"[yellow]{inv.number if inv else '-'}[/] {inv.vendor if inv else '-'} "
                  f"({Path(s.source).name}), total {money(s.total_usd)} USD")
    console.print(f"Held because: {reason or '-'}")
    shown = [f for f in s.flags if f.severity != Severity.INFO]
    if shown:
        console.print("Flags: " + "; ".join(f"{f.severity.value} {f.code}" for f in shown))
    if s.memo:
        console.print(f"Memo ({s.memo.get('by')}): {s.memo.get('text')}")
    if s.extraction_mode == "llm_repair":
        raw = s.raw_text or "(the original text was not stored)"
        cut = f"\n... ({len(raw) - RAW_SHOWN:,} more characters in {s.source})" if len(raw) > RAW_SHOWN else ""
        t = Table(title="Decision 10: the parser could not read this file; Grok rebuilt it. Compare before deciding.",
                  show_lines=False, expand=True)
        t.add_column("Original text, as received", ratio=1, overflow="fold")
        t.add_column("Grok's reading", ratio=1, overflow="fold")
        t.add_row(raw[:RAW_SHOWN] + cut, grok_reading(s))
        console.print(t)
    console.print("Decide with: python main.py review " + (inv.number if inv and inv.number else "<invoice number>")
                  + " --approve | --reject [--note TEXT]")
