"""Regenerate the tables in docs/run_log.md from runs/demo/{offline,live}/summary.json.

The prose sections below are written by hand and kept in this script so the
numbers and the words are updated together.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> dict:
    return json.loads((ROOT / "runs" / "demo" / name / "summary.json").read_text())


def money(x: float) -> str:
    return f"${x:,.2f}"


def counts(rows: list[dict]) -> tuple[int, float, int, int]:
    paid = [r for r in rows if r["payment"].startswith("paid")]
    rej = sum(r["decision"] == "REJECTED" for r in rows)
    held = sum(r["decision"] == "PENDING_HUMAN" for r in rows)
    return len(paid), sum(r["total_usd"] for r in paid), rej, held


def dec(r: dict, live: bool = False) -> str:
    engine = r.get("engine") or ("grok" if live and r["decided_by"] in ("vp", "vp+critic", "deadlock") else None)
    s = f"{r['decision']} ({r['decided_by']}" + (", rules stand-in" if engine == "rules" else ", Grok" if engine == "grok" else "")
    if r["critique_rounds"]:
        s += f", {r['critique_rounds']} rounds"
    return s + ")"


DIFFS = """\
## Where live and offline disagree

Both runs use the same policy, including the address watch list and the hard hold rules for prompt injection, renamed or lookalike vendors, changed bank details, Grok and parser disagreeing, Grok-rebuilt invoices and unreadable layouts (decisions 8 to 14 in `docs/DECISIONS.md`). In live mode Grok also reads every invoice next to the parser (trace step `grok_cross_check`; all 20 agreed in this run) and writes the memo for every decision, and the risk agent calls three read-only tools (`lookup_vendor`, `query_inventory`, `vendor_history`) before it scores; the calls are in the trace as `tool_call` events. Every difference goes the cautious way: Grok sent an invoice to a human where the offline rules paid it. Neither run paid anything the other refused.

- **invoice_1004_revised.json**: offline pays revision R1 ($5,940.00); its address is the one on file for Precision Parts, so the watch list does not fire (decision 13). The live VP held it (risk 38): the earlier INV-1004 was rejected and R1 cites a PO amendment with no PO number.
- **invoice_1006.csv**: the live VP held it (risk 20) as the vendor's first recorded invoice with no address in the vendor master, and asked for the remit-to address and bank details to be confirmed. Offline pays.
- **invoice_1010.txt**: the live VP held it (risk 22) until a buyer confirms the $300 WidgetA rush rate (20% over the $250 catalog price). Offline approves with that check as a payment condition.
- **invoice_1014.xml**: the live VP held it (risk 18) as the vendor's first payment, billed in EUR with line prices that do not match the USD catalog. Offline pays it in USD at the mock rate.

Live results are not perfectly repeatable. A second live run of the same code (the cache measurement, `evals/results/cache_repeatability.md`) paid 1006, which this demo run held; see the README for the eval run.

Same outcome, by a different path:

- **invoice_1012.pdf**: PENDING_HUMAN in both runs, decided by the vendor-rename hard hold (decision 9) before the VP and critic. Live, the risk agent still ran its tools and raised the risk to 70, but no VP or critic call was made.

Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule score (it can never lower it). None of those increases crossed a threshold except where noted above.
"""


def main() -> None:
    off, live = load("offline"), load("live")
    lo = {r["file"]: r for r in live["rows"]}
    out = [
        "# Run log: all 20 sample invoices",
        "",
        "Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026. The offline run "
        f"was regenerated at commit {off.get('commit') or 'see summary.json'} after independent review 2; the live run is "
        "from the earlier checkpoint 982b14f (branch `live-eval-checkpoints`) and could not be re-run because the xAI "
        "account is out of credits, so it predates the review 2 changes (for example the rejection review).",
        "",
        "- **Offline** (`--offline`): no model is called; the risk review, VP, critic and rejection review are rules stand-ins "
        "(fixed rules written from the agents' prompts), and a template writes the memo: `runs/demo/offline/`",
        f"- **Live** (`--mode live`, {live.get('model')} via the xAI API for the cross-check, risk review, VP, critic and memo): `runs/demo/live/`",
        "",
        "Each folder has `trace.jsonl` (every agent step), `summary.json` and `report.md`. "
        "Hard rules (any blocking flag) reject 12 of 20 before any Grok opinion, so both runs agree on those by construction (live, Grok still cross-checks and writes their memo); a hard hold rule holds 1012.pdf (renamed vendor) before the VP. "
        "Regenerate this file with `python scripts/make_run_log.py`.",
        "",
        "## Side by side",
        "",
        "| File | Total USD | Risk off / live | Offline decision | Live decision | Paid off / live |",
        "|---|---|---|---|---|---|",
    ]
    for r in off["rows"]:
        l = lo[r["file"]]
        differs = " **differs**" if r["decision"] != l["decision"] else ""
        out.append(
            f"| {r['file']} | {money(r['total_usd'])} | {r['risk']} / {l['risk']} | {dec(r)} | {dec(l, live=True)}{differs} | {r['payment']} / {l['payment']} |"
        )
    for name, s in (("Offline", off), ("Live", live)):
        n, amt, rej, held = counts(s["rows"])
        out.append("")
        out.append(f"{name}: {n} paid ({money(amt)}), {rej} rejected, {held} held for a human.")
    out += ["", DIFFS, "## Live reasons (first reason per invoice the VP decided)", "",
            "| File | Decision | Reason | Conditions |", "|---|---|---|---|"]
    for l in live["rows"]:
        if l["decided_by"] in ("hard_rules", "hard_hold"):
            continue
        cond = "; ".join(l["conditions"]) or "none"
        out.append(f"| {l['file']} | {l['decision']} | {l['reason']} | {cond} |")
    (ROOT / "docs" / "run_log.md").write_text("\n".join(out) + "\n")
    print("wrote docs/run_log.md")


if __name__ == "__main__":
    main()
