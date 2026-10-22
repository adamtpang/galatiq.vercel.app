"""Acme invoice agents CLI (work in progress: ingest + validate only).

  python main.py --invoice_path=data/invoices/invoice_1001.txt
  python main.py --batch data/invoices
  python main.py --batch data/invoices --json      # machine-readable output
  python main.py --invoice_path=... --mode live    # allow Grok repair when the parser fails
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from invoice_agents.db import db_path, init_db
from invoice_agents.llm import get_client
from invoice_agents.models import Severity
from invoice_agents.pipeline import collect, run_files

app = typer.Typer(add_completion=False)
console = Console()
SEV_STYLE = {Severity.BLOCK: "bold red", Severity.WARN: "yellow", Severity.INFO: "dim"}
PENDING = "pending: approval agent not built"


def _money(v, cur="USD"):
    if v is None:
        return "-"
    return f"{'$' if cur == 'USD' else cur + ' '}{v:,.2f}"


@app.command()
def main(
    invoice_path: Optional[Path] = typer.Option(None, "--invoice_path", "--invoice-path", help="One invoice file"),
    batch: Optional[Path] = typer.Option(None, "--batch", help="Directory of invoices"),
    mode: str = typer.Option("offline", "--mode", help="offline | auto | live"),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of tables"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show every flag message and the trace"),
):
    load_dotenv()
    target = invoice_path or batch
    if target is None:
        raise typer.BadParameter("pass --invoice_path or --batch")
    if not db_path().exists():
        init_db()
    llm = get_client(mode)
    files = collect(target)
    states = run_files(files, llm)

    if as_json:
        print(json.dumps([s.model_dump(mode="json", exclude={"raw_text"}) for s in states], indent=2))
        return

    console.print(f"[bold]Acme invoice agents[/]  mode=[cyan]{llm.name}[/]  files={len(files)}  "
                  f"db={db_path()}  [dim](ingest + validate only)[/]")
    t = Table(show_lines=True, expand=False)
    for c, kw in (("File", {"max_width": 22}), ("Invoice", {"no_wrap": True}), ("Vendor", {"max_width": 22}),
                  ("Total", {"justify": "right", "no_wrap": True}), ("Items", {"no_wrap": True}),
                  ("Due", {"no_wrap": True}), ("Flags", {"no_wrap": True}), ("Approval", {"max_width": 18})):
        t.add_column(c, overflow="fold", **kw)
    for s in states:
        inv = s.invoice
        if inv is None:
            t.add_row(Path(s.source).name, "-", "-", "-", "-", "-", "[bold red]EXTRACTION_FAILED[/]", PENDING)
            continue
        items = "\n".join(f"{li.qty:g} x {li.sku or li.sku_raw + '?'} @ {_money(li.unit_price, inv.currency)}"
                          for li in inv.items)
        flags = "\n".join(f"[{SEV_STYLE[f.severity]}]{f.severity.value}: {f.code}[/]" for f in s.flags) or "[green]none[/]"
        total = _money(inv.total, inv.currency) + (f"\n= {_money(s.total_usd)}" if inv.currency != "USD" else "")
        due = str(inv.due_date) if inv.due_date else (inv.due_date_raw or "-")
        t.add_row(Path(s.source).name, f"{inv.number or '-'}{' ' + inv.revision if inv.revision else ''}",
                  inv.vendor or "[red]missing[/]", total, items, due, flags, f"[dim]{PENDING}[/]")
    console.print(t)
    if verbose:
        for s in states:
            console.rule(Path(s.source).name)
            for f in s.flags:
                console.print(f"[{SEV_STYLE[f.severity]}]{f.severity.value:>5} {f.code}[/]: {f.message}")
            for e in s.trace:
                console.print(f"[dim]trace {e.agent}.{e.step} {e.detail}[/]")
    blocked = sum(s.has_blocking() for s in states)
    console.print(f"{len(states)} processed, {blocked} with blocking flags. Decisions: {PENDING}.")


if __name__ == "__main__":
    app()
