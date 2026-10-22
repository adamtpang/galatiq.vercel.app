"""Acme invoice agents CLI.

  python main.py --invoice_path=data/invoices/invoice_1001.txt
  python main.py --batch data/invoices [--offline] [--chaos 0.3] [--json]
  python main.py review                       # list the human review queue
  python main.py review INV-1012 --approve    # or --reject, optional --note
  python main.py eval [--live]                # the four evals (same as python -m evals)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from invoice_agents import hitl
from invoice_agents.agents.payment import PaymentAgent, log_rejection
from invoice_agents.db import connect, db_path
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import get_client
from invoice_agents.models import DecisionStatus
from invoice_agents.pipeline import collect
from invoice_agents.reporter import print_summary, write_artifacts

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
        console.print(f"[red]No such file or directory:[/] {target}")
        raise typer.Exit(2)
    llm = get_client("offline" if offline else mode)
    rc = make_context(llm=llm, chaos=chaos, seed=seed, run_id=run_id)
    model = getattr(llm, "model", None)
    if not as_json:
        console.print(f"[bold]Acme invoice agents[/]  mode=[cyan]{llm.name}[/]{' ' + model if model else ''}  "
                      f"chaos={chaos}  db={db_path()}  run={rc.run_id}")
    states = run_batch(collect(target), rc)
    write_artifacts(states, rc.run_dir, llm.name, model)
    if as_json:
        print(json.dumps([s.model_dump(mode="json", exclude={"raw_text"}) for s in states], indent=2, default=str))
    else:
        if log if log is not None else invoice_path is not None:
            for st in states:
                for ev in st.trace:
                    if ev.step == "node_done":
                        continue
                    line = json.dumps({"agent": ev.agent, "step": ev.step, "detail": ev.detail}, default=str)
                    print(line if len(line) <= 220 else line[:217] + "...")
        for st in states:
            msg = (st.payment or {}).get("bank_message") if isinstance(st.payment, dict) else None
            if msg:
                print(f"mock_payment: {msg}")
        print_summary(states, console, llm.name, rc.run_dir)


@app.command()
def review(
    invoice: Optional[str] = typer.Argument(None, help="Invoice number, e.g. INV-1012"),
    approve: bool = typer.Option(False, "--approve"),
    reject: bool = typer.Option(False, "--reject"),
    note: Optional[str] = typer.Option(None, "--note"),
    chaos: float = typer.Option(0.0, "--chaos", min=0.0, max=1.0),
):
    """List the human review queue, or approve/reject one invoice in it."""
    conn = connect()
    if invoice is None:
        rows = hitl.pending(conn)
        if not rows:
            console.print("Review queue is empty.")
        for r in rows:
            console.print(f"[yellow]{r['invoice_number']}[/] {r['vendor']} ({Path(r['source_file']).name}): {r['reason']}")
        return
    if approve == reject:
        raise typer.BadParameter("pass exactly one of --approve or --reject")
    row = hitl.find(conn, invoice)
    if row is None:
        console.print(f"[red]No pending review for {invoice}[/]")
        raise typer.Exit(1)
    state = hitl.resolve(conn, row, approve, note)
    if state.decision.status == DecisionStatus.APPROVED:
        state = PaymentAgent(conn, chaos=chaos).pay(state)
    else:
        state = log_rejection(conn, state)
    console.print(f"{state.invoice.number}: {state.decision.status.value} by human. Payment: {state.payment}")


@app.command("eval")
def eval_cmd(live: bool = typer.Option(False, "--live", help="Also run live against the xAI API (needs XAI_API_KEY)")):
    """Run the evals: extraction accuracy, live vs offline agreement, adversarial set, cost and latency."""
    from evals.runner import main as run_evals
    raise typer.Exit(run_evals(["--live"] if live else []))


if __name__ == "__main__":
    app()
