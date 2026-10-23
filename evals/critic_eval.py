"""Critic eval: VP approval proposals injected at the critic stage.

A component-level eval of the critique loop. Each case in evals/critic_eval_cases.yaml is an invoice plus a VP
approval proposal (written in advance, some with a seeded flaw the hard rules do not catch, some sound controls).
The invoice goes through the offline checks (ingest, validate, rules risk; no model). Then the real
approval.decide() runs with InjectedVP: its first answer is the proposal (no model call), its revise() is the real
VP's. The critic is the real critic. With --live both are Grok (no cache), so this exercises the production critic
and revise code with the real model, entered at the critic stage. It is not an end-to-end run: end to end, the
Grok VP has held these invoices before the critic was reached.

    python -m evals.critic_eval                 # rules stand-ins, no model
    python -m evals.critic_eval --live --write  # Grok; writes runs/demo/critic_eval_live and evals/results/critic_eval_live.md

Metrics: objection rate on flawed proposals, false-objection rate on sound ones, and how the VP revised.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

from invoice_agents import ROOT
from invoice_agents.agents import approval, risk
from invoice_agents.agents.ingestion import ingest
from invoice_agents.config import load_policy
from invoice_agents.db import Inventory, connect
from invoice_agents.graph import llm_usage
from invoice_agents.llm import OfflineClient, get_client
from invoice_agents.models import InvoiceState, TraceEvent
from invoice_agents.parsers import parse_file
from invoice_agents.validation import DuplicateRegistry, validate

CASES = Path(__file__).with_name("critic_eval_cases.yaml")
BUDGET_USD = 0.45   # stop before another case if the billed spend reaches this


class InjectedVP:
    """The VP's first answer is the injected proposal (no model call); revise() is the real VP (Grok or rules)."""

    def __init__(self, proposal: approval.VPOpinion, inner: Any):
        self.proposal, self.inner = proposal, inner
        self.engine = getattr(inner, "engine", None)

    def propose(self, state, f):
        return self.proposal

    def revise(self, state, f, prior, objection):
        return self.inner.revise(state, f, prior, objection)


def prepare(path: Path, db: str) -> InvoiceState:
    """Offline checks only: ingest, validate and the rules risk score, on a fresh database. No model is called."""
    conn = connect(db)
    inv, policy = Inventory(conn), load_policy()
    reg = DuplicateRegistry(conn=conn, run_id="critic_eval")
    reg.prescan([parse_file(path)])
    s = ingest(str(path), inv, OfflineClient())
    s = validate(s, inv, policy, reg)
    return risk.assess(s, policy, OfflineClient(), risk.risk_tools(inv, conn))


def run_case(case: dict, vp_inner: Any, critic: Any, llm: Any, policy: dict, db: str) -> tuple[InvoiceState, dict]:
    state = prepare(ROOT / case["file"], db)
    proposal = approval.VPOpinion(**case["proposal"])
    state.trace.append(TraceEvent(agent="critic_eval", step="injected_proposal", detail={
        "case": case["id"], "flawed": case["flawed"], "seeded_flaw": case["flaw"],
        "note": "proposal injected at the critic stage; not a model answer", **proposal.model_dump()}))
    n0 = len(getattr(llm, "usage_log", []) or [])
    t0 = time.monotonic()
    d = approval.decide(state, InjectedVP(proposal, vp_inner), critic, policy)
    recs = (getattr(llm, "usage_log", []) or [])[n0:]
    state.decision = d
    state.trace.append(TraceEvent(agent="approval", step="decide", detail=d.model_dump(mode="json")))
    state.trace.append(TraceEvent(agent="approval", step="node_done",
                                  detail={"ms": round((time.monotonic() - t0) * 1000, 1), "llm": llm_usage(recs)}))
    crit = [e.detail for e in state.trace if e.step == "critic_review"]
    rev = [e.detail for e in state.trace if e.step == "vp_revise"]
    ticks = [r.get("cost_in_usd_ticks") for r in recs]
    row = {"case": case["id"], "file": Path(case["file"]).name, "flawed": case["flawed"],
           "critic_ran": bool(crit), "objected": any(c["verdict"] == "object" for c in crit),
           "critic_rounds": len(crit), "first_verdict": crit[0]["verdict"] if crit else None,
           "first_reason": crit[0]["reason"] if crit else None,
           "vp_revisions": [r["decision"] for r in rev], "final": d.status.value, "decided_by": d.decided_by,
           "calls": len(recs), "models": sorted({r.get("model") for r in recs if r.get("model")}),
           "billed_usd": round(sum(t for t in ticks if t) / 1e10, 4) if recs and all(t is not None for t in ticks) else (0.0 if not recs else None)}
    return state, row


def metrics(rows: list[dict]) -> dict:
    flawed = [r for r in rows if r["flawed"]]
    sound = [r for r in rows if not r["flawed"]]
    return {"flawed": len(flawed), "objected_on_flawed": sum(r["objected"] for r in flawed),
            "objection_rate": round(sum(r["objected"] for r in flawed) / len(flawed), 3) if flawed else None,
            "sound": len(sound), "objected_on_sound": sum(r["objected"] for r in sound),
            "false_objection_rate": round(sum(r["objected"] for r in sound) / len(sound), 3) if sound else None,
            "vp_revisions": sum(len(r["vp_revisions"]) for r in rows),
            "billed_usd": round(sum(r["billed_usd"] or 0 for r in rows), 4)}


def run(live: bool = False, cases: list[dict] | None = None) -> dict:
    cases = cases or yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    policy = load_policy()
    if live:
        llm = get_client("live")   # a bare GrokClient: no decision cache, every answer is fresh
        vp_inner, critic = approval.LLMVP(llm), approval.LLMCritic(llm)
    else:
        llm = OfflineClient()
        vp_inner, critic = approval.OfflineVP(), approval.OfflineCritic()
    tmp = Path(tempfile.mkdtemp(prefix="critic_eval_"))
    states, rows, spent, stopped = [], [], 0.0, None
    try:
        for i, case in enumerate(cases):
            if spent >= BUDGET_USD:
                stopped = f"budget: ${spent:.4f} spent before case {case['id']}"
                break
            st, row = run_case(case, vp_inner, critic, llm, policy, str(tmp / f"case{i}.db"))
            states.append(st)
            rows.append(row)
            spent += row["billed_usd"] or 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"mode": "live" if live else "offline", "model": getattr(llm, "model", None),
            "label": "critic eval: proposals injected at the critic stage",
            "generated_at": time.strftime("%Y-%m-%d %H:%M %Z"), "rows": rows, "metrics": metrics(rows),
            "stopped": stopped, "states": states}


def write(res: dict, run_id: str = "demo/critic_eval_live") -> None:
    d = ROOT / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    root = str(ROOT) + "/"
    with open(d / "trace.jsonl", "w", encoding="utf-8") as fh:
        for s in res["states"]:
            for ev in s.trace:
                fh.write(json.dumps({"run_id": run_id, "source": Path(s.source).name,
                                     "invoice": s.invoice.number if s.invoice else None, **ev.model_dump(mode="json")},
                                    default=str).replace(root, "") + "\n")
    out = {k: v for k, v in res.items() if k != "states"}
    (d / "summary.json").write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    m = res["metrics"]
    lines = [f"# Critic eval: proposals injected at the critic stage ({res['mode']}, {res['model']}, {res['generated_at']})", "",
             "Component-level eval of the critique loop, not an end-to-end run. Each invoice goes through the offline "
             "checks; then the real `approval.decide()` runs with the VP's first answer replaced by the proposal in "
             "`evals/critic_eval_cases.yaml` (no model call for it), the real critic, and the real VP revise path. "
             f"Trace: `runs/{run_id}/trace.jsonl` (unedited).", "",
             f"- Flawed proposals: critic objected on {m['objected_on_flawed']} of {m['flawed']} (objection rate {m['objection_rate']})",
             f"- Sound proposals: critic objected on {m['objected_on_sound']} of {m['sound']} (false-objection rate {m['false_objection_rate']})",
             f"- VP revisions after an objection: {m['vp_revisions']}",
             f"- Billed: ${m['billed_usd']:.4f}" + (f"; stopped early ({res['stopped']})" if res["stopped"] else ""), "",
             "| Case | Flawed | Critic round 1 | Critic reason (round 1) | VP revisions | Loop result |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        reason = (r["first_reason"] or "").replace("|", "/").replace("\n", " ")
        lines.append(f"| {r['case']} | {'yes' if r['flawed'] else 'no (control)'} | {r['first_verdict'] or 'not run'} | {reason} | "
                     f"{', '.join(r['vp_revisions']) or 'none'} | {r['final']} ({r['decided_by']}) |")
    name = "critic_eval_live.md" if res["mode"] == "live" else "critic_eval_offline.md"
    (ROOT / "evals" / "results" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="Grok critic and VP revise (needs XAI_API_KEY)")
    ap.add_argument("--write", action="store_true", help="write the trace, summary and results file")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    res = run(live=a.live)
    for r in res["rows"]:
        print(f"{r['case']:<20} flawed={r['flawed']!s:<5} critic={r['first_verdict']} revisions={r['vp_revisions']} "
              f"final={r['final']} ({r['decided_by']}) calls={r['calls']} billed={r['billed_usd']}")
    print(json.dumps(res["metrics"]))
    if res["stopped"]:
        print(res["stopped"])
    if a.write:
        write(res, a.run_id or ("demo/critic_eval_live" if a.live else "demo/critic_eval_offline"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
