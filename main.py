"""Acme invoice agents CLI.

  python main.py --invoice_path=data/invoices/invoice_1001.txt
  python main.py --batch data/invoices [--offline] [--chaos 0.3] [--json] [--no-cache]
  python main.py review                       # list the human review queue
  python main.py review INV-1012 --approve    # or --reject; optional --note, --amount, --confirm-large
  python main.py ui [--port 8765]             # the review queue in the browser, with Approve and Reject
  python main.py eval [--live]                # the five evals (same as python -m evals)
"""
from __future__ import annotations

import json
import re
from difflib import get_close_matches
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from invoice_agents import hitl
from invoice_agents.db import connect, db_path
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import LLMUnavailable, get_client
from invoice_agents.pipeline import collect, skipped
from invoice_agents.reporter import print_review, print_summary, write_artifacts

app = typer.Typer(add_completion=False, invoke_without_command=True, no_args_is_help=False)
console = Console()


@app.callback()
def run(
    ctx: typer.Context,
    invoice_path: Optional[Path] = typer.Option(None, "--invoice_path", "--invoice-path", help="One invoice file"),
    batch: Optional[Path] = typer.Option(None, "--batch", help="Directory of invoices"),
    offline: bool = typer.Option(False, "--offline", help="Never call an LLM (same as --mode offline)"),
    mode: str = typer.Option("auto", "--mode", help="auto (Grok if XAI_API_KEY is set) | offline | live"),
    chaos: float = typer.Option(0.0, "--chaos", min=0.0, max=1.0, help="Probability each bank call fails"),
    seed: Optional[int] = typer.Option(None, "--seed", help="Seed for --chaos"),
    as_json: bool = typer.Option(False, "--json", help="Print full JSON states"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Name of the runs/<run_id> folder"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Live: do not reuse or store Grok answers (decision cache)"),
    log: Optional[bool] = typer.Option(None, "--log/--no-log",
                                       help="Print each agent step as a JSON line (default: on for one file, off for --batch)"),
):
    load_dotenv()
    if ctx.invoked_subcommand:
        return
    target = invoice_path or batch
    if target is None:
        console.print(ctx.get_help())
        raise typer.Exit(1)
    if not target.exists():
        target = brief_alias(target) or missing_path(target)
    try:
        llm = get_client("offline" if offline else mode)
    except LLMUnavailable as e:
        console.print(f"[red]{e}.[/] Set it (see .env.example) or run offline with --offline.")
        raise typer.Exit(2)
    rc = make_context(llm=llm, chaos=chaos, seed=seed, run_id=run_id, cache=not no_cache)
    model = getattr(llm, "model", None)
    if not as_json:
        console.print(f"[bold]Acme invoice agents[/]  mode=[cyan]{llm.name}[/]{' ' + model if model else ''}  "
                      f"chaos={chaos}  db={db_path()}  run={rc.run_id}")
    skip = skipped(target)
    if skip and not as_json:
        console.print(f"[yellow]Skipped {len(skip)} file(s) with an unsupported extension[/] (supported: .txt .eml .csv "
                      f".json .xml .pdf): {', '.join(f.name for f in skip[:6])}{', ...' if len(skip) > 6 else ''}")
    states = run_batch(collect(target), rc)
    write_artifacts(states, rc.run_dir, llm.name, model)
    if as_json:
        print(json.dumps([s.model_dump(mode="json", exclude={"raw_text"}) for s in states], indent=2, default=str))
    else:
        if log if log is not None else invoice_path is not None:
            print_step_log(states)
        for st in states:
            msg = (st.payment or {}).get("bank_message")
            if msg:
                print(f"mock_payment: {msg}")
        print_summary(states, console, llm.name, rc.run_dir)
        info = getattr(rc.llm, "info", None)
        if info is not None:
            pinned = [st for st in states if any(f.code == "MODEL_MISMATCH" for f in st.flags)]
            hits = sum(e.detail.get("hits", 0) for st in states for e in st.trace if e.step == "model_pin")
            misses = sum(e.detail.get("misses", 0) for st in states for e in st.trace if e.step == "model_pin")
            console.print(f"Decision cache: {'on' if not no_cache else 'off (--no-cache)'}; {hits} Grok answers reused, "
                          f"{misses} new calls stored." if not no_cache else "Decision cache: off (--no-cache).")
            if pinned:
                console.print(f"[yellow]Model pin: {len(pinned)} invoice(s) got answers from a model other than "
                              f"{model}; held for a human (MODEL_MISMATCH).[/]")


def brief_alias(target: Path) -> Path | None:
    """The brief's example, data/invoices/invoice1.txt, names a file the case data does not have; the samples
    are invoice_1001.txt and up. Map invoiceN.txt (N below 1000 means 1000 + N) to that sample and say so."""
    m = re.fullmatch(r"invoice_?(\d+)\.txt", target.name, re.I)
    if not m or not target.parent.is_dir():
        return None
    n = int(m.group(1))
    num = 1000 + n if n < 1000 else n
    exact = target.parent / f"invoice_{num}.txt"
    cands = [exact] if exact.exists() else sorted(target.parent.glob(f"invoice_{num}.*"))
    if not cands:
        return None
    console.print(f"[yellow]Note:[/] {target.name} is not in the case data (the samples are named invoice_1001.txt "
                  f"and up); using {cands[0]}.")
    return cands[0]


def missing_path(target: Path) -> None:
    """Exit 2 with the nearest file names, e.g. for the brief's data/invoices/invoice1.txt."""
    console.print(f"[red]No such file or directory:[/] {target}")
    if target.parent.is_dir():
        near = sorted(get_close_matches(target.name, [f.name for f in target.parent.iterdir()], n=50, cutoff=0.6))[:3]
        if near:
            console.print("Did you mean: " + ", ".join(str(target.parent / n) for n in near) + "?")
    raise typer.Exit(2)


LOG_LINE_MAX = 400   # characters per structured log line on the console (the trace file keeps everything)


def compact(value, max_str: int = 100, max_items: int = 4, depth: int = 0):
    """Shorten a log value INSIDE the structure, so the printed line is still valid JSON: long strings get a
    "..." suffix, long lists keep their first items plus a count, deep objects are summarized."""
    if isinstance(value, str):
        return value if len(value) <= max_str else value[:max_str - 3] + "..."
    if isinstance(value, dict):
        if depth >= 3:
            return {"_keys": list(value)[:max_items]}
        return {str(k): compact(v, max_str, max_items, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        out = [compact(v, max_str, max_items, depth + 1) for v in list(value)[:max_items]]
        if len(value) > max_items:
            out.append(f"... {len(value) - max_items} more")
        return out
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return compact(str(value), max_str, max_items, depth)


def step_log_line(ev) -> str:
    """One agent step as a single line of valid JSON, at most LOG_LINE_MAX characters."""
    detail = ev.detail
    if ev.step == "extracted" and isinstance(detail.get("invoice"), dict):
        inv = detail["invoice"]
        detail = {**detail, "invoice": {"number": inv.get("number"), "vendor": inv.get("vendor"),
                                        "total": inv.get("total"), "currency": inv.get("currency"),
                                        "items": len(inv.get("items") or [])}}
    for max_str, max_items in ((100, 4), (60, 3), (30, 2)):
        line = json.dumps({"agent": ev.agent, "step": ev.step, "detail": compact(detail, max_str, max_items)},
                          default=str)
        if len(line) <= LOG_LINE_MAX:
            return line
    d = compact(detail, 30, 2) if isinstance(detail, dict) else {"value": compact(detail, 30, 2)}
    omitted = []
    while d:   # drop the largest fields, named in "_omitted", until the line fits
        big = max(d, key=lambda k: len(json.dumps(d[k], default=str)))
        omitted.append(big)
        d.pop(big)
        line = json.dumps({"agent": ev.agent, "step": ev.step, "detail": {**d, "_omitted": omitted}}, default=str)
        if len(line) <= LOG_LINE_MAX:
            return line
    return json.dumps({"agent": ev.agent, "step": ev.step, "detail": {"_omitted": omitted[:12]}}, default=str)


def print_step_log(states) -> None:
    """One JSON line per agent step (the structured log). Every line is valid JSON: long values are shortened
    inside the object, never by cutting the printed string. The full detail is in runs/<run_id>/trace.jsonl."""
    for st in states:
        for ev in st.trace:
            if ev.step == "node_done":
                continue
            print(step_log_line(ev))


@app.command()
def review(
    invoice: Optional[str] = typer.Argument(None, help="Invoice number, e.g. INV-1012; alone, shows that invoice"),
    approve: bool = typer.Option(False, "--approve", help="Approve and pay it (idempotent, with retries)"),
    reject: bool = typer.Option(False, "--reject", help="Reject it; the reason goes to the audit log"),
    note: Optional[str] = typer.Option(None, "--note", help="Reviewer note, stored with the decision"),
    amount: Optional[float] = typer.Option(None, "--amount", help="Amount to pay in USD; required when the "
                                           "numbers do not add up or the currency is not USD"),
    confirm_large: bool = typer.Option(False, "--confirm-large", help="Second confirmation to pay over $10,000"),
    chaos: float = typer.Option(0.0, "--chaos", min=0.0, max=1.0, help="Probability each bank call fails"),
):
    """List the human review queue, show one queued invoice (with the original text next to Grok's
    reading when Grok rebuilt it), or approve/reject it."""
    conn = connect()
    if invoice is None:
        rows = hitl.pending(conn)
        if not rows:
            console.print("Review queue is empty.")
        for r in rows:
            console.print(f"[yellow]{r['invoice_number']}[/] {r['vendor']} ({Path(r['source_file']).name}): {r['reason']}")
        if rows:
            console.print("Decide one with: python main.py review <invoice number> --approve | --reject [--note TEXT]")
        return
    if approve and reject:
        raise typer.BadParameter("pass only one of --approve or --reject")
    row = hitl.find(conn, invoice)
    if row is None:
        console.print(f"[red]No pending review for {invoice}[/]")
        raise typer.Exit(1)
    if not (approve or reject):
        print_review(hitl.queued_state(row), row["reason"], console)
        return
    try:
        state = hitl.decide(conn, row, approve, note, chaos=chaos, amount=amount, confirm_large=confirm_large)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    p = state.payment or {}
    num, vendor = state.invoice.number, state.invoice.vendor
    if p.get("status") == "paid":
        console.print(f"mock_payment: {p.get('bank_message')}")
        outcome = f"paid ${p['amount']:,.2f} to {vendor} (attempts: {p['attempts']}, key {p['idempotency_key']})"
    elif p.get("status") == "already_paid":
        outcome = f"already paid ${p['amount']:,.2f} earlier; not paid again"
    elif p.get("status") == "failed":
        outcome = f"[red]payment failed[/] after {p['attempts']} attempts: {'; '.join(p.get('errors', []))}"
    else:
        outcome = "not paid; rejection written to the audit log"
    console.print(f"{num}: {state.decision.status.value.lower()} by a human ({note or 'no note'}). {outcome}")
    if p.get("status") == "failed":
        raise typer.Exit(1)


@app.command()
def ui(port: int = typer.Option(8765, "--port", help="Port on 127.0.0.1"),
       chaos: float = typer.Option(0.0, "--chaos", min=0.0, max=1.0, help="Probability each bank call fails")):
    """Local review UI in the browser: the review queue with Approve and Reject buttons (localhost only)."""
    from invoice_agents.ui import make_server
    srv = make_server(port=port, chaos=chaos)
    console.print(f"Review UI on http://127.0.0.1:{srv.server_address[1]}/  (db={db_path()}). Ctrl+C stops it.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


@app.command("eval")
def eval_cmd(live: bool = typer.Option(False, "--live", help="Also run live against the xAI API (needs XAI_API_KEY)")):
    """Run the evals: extraction accuracy, live vs offline agreement, adversarial set, cost and latency."""
    from evals.runner import main as run_evals
    raise typer.Exit(run_evals(["--live"] if live else []))


if __name__ == "__main__":
    app()
