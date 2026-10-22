"""Console summary table and run artifacts (summary.json, report.md)."""
from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .models import InvoiceState, Severity

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
        "critique_rounds": d.critique_rounds if d else 0,
        "payment": p.get("status", "-") + (f" {money(p['amount'])}" if p.get("status") in ("paid", "already_paid") else ""),
        "reason": (d.reasons[0] if d and d.reasons else ""),
        "conditions": d.conditions if d else [],
        "errors": s.errors,
    }


WIDE = 140   # below this terminal width the table drops the Vendor, Risk, Flags and By columns


def print_summary(states: list[InvoiceState], console: Console, mode: str, run_dir: Path | None) -> None:
    wide = console.width >= WIDE
    cols = ["File", "Invoice", "Vendor", "Total USD", "Risk", "Flags", "Decision", "By", "Payment", "Reason"]
    if not wide:
        cols = ["File", "Total USD", "Decision", "Payment", "Reason"]
    t = Table(title=f"Run summary ({mode})", show_lines=False)
    for c in cols:
        if c == "Reason":
            t.add_column(c, overflow="fold", ratio=1)
        else:
            t.add_column(c, no_wrap=True, overflow="ellipsis", max_width=None if wide else 18)
    for s in states:
        r = row(s)
        flags = ", ".join(r["block_flags"][:3]) or (", ".join(r["warn_flags"][:2]) and "warn: " + ", ".join(r["warn_flags"][:2])) or "-"
        decision = f"[{STATUS_STYLE.get(r['decision'], '')}]{r['decision'].replace('PENDING_HUMAN', 'HELD')}[/]"
        cells = {"File": r["file"].removeprefix("invoice_"), "Invoice": r["invoice"], "Vendor": r["vendor"],
                 "Total USD": money(r["total_usd"]), "Risk": "-" if r["risk"] is None else str(r["risk"]),
                 "Flags": flags, "Decision": decision, "By": r["decided_by"], "Payment": r["payment"],
                 "Reason": r["reason"][:90 if wide else 70]}
        t.add_row(*(cells[c] for c in cols))
    console.print(t)
    if not wide:
        console.print(f"[dim]Narrow terminal ({console.width} columns): full table in report.md and summary.json.[/]")
    counts = {k: sum(row(s)["decision"] == k for s in states) for k in STATUS_STYLE}
    paid = sum((s.payment or {}).get("amount", 0) for s in states if (s.payment or {}).get("status") == "paid")
    console.print(f"{len(states)} invoice{'' if len(states) == 1 else 's'}: {counts['APPROVED']} approved, {counts['REJECTED']} rejected, "
                  f"{counts['PENDING_HUMAN']} pending human review. Paid this run: {money(paid)}.")
    if run_dir:
        console.print(f"Trace: {run_dir / 'trace.jsonl'}")


def write_artifacts(states: list[InvoiceState], run_dir: Path | None, mode: str, model: str | None = None) -> None:
    if not run_dir:
        return
    rows = [row(s) for s in states]
    (run_dir / "summary.json").write_text(json.dumps({"mode": mode, "model": model, "rows": rows}, indent=2, default=str))
    lines = [f"# Run {run_dir.name} ({mode}{', ' + model if model else ''})", "",
             "| File | Invoice | Vendor | Total USD | Risk | Blocking flags | Decision | By | Rounds | Payment | Reason |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        reason = r["reason"].replace("|", "/")
        lines.append(f"| {r['file']} | {r['invoice']} | {r['vendor']} | {money(r['total_usd'])} | {r['risk']} | "
                     f"{', '.join(r['block_flags']) or '-'} | {r['decision']} | {r['decided_by']} | "
                     f"{r['critique_rounds']} | {r['payment']} | {reason} |")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")
