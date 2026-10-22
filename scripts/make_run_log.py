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


def dec(r: dict) -> str:
    s = f"{r['decision']} ({r['decided_by']}"
    if r["critique_rounds"]:
        s += f", {r['critique_rounds']} rounds"
    return s + ")"


DIFFS = """\
## Where live and offline disagree

Both runs use the same policy, including the address watch list (`742 evergreen terrace` was added after the first live run flagged it). Every difference goes the cautious way: Grok sent an invoice to a human where the offline rules paid it. Neither run paid anything the other refused on hard rules.

- **invoice_1006.csv**: the live VP held it because the due date (16 days) does not match Net 15. Offline treats TERMS_MISMATCH as info only and pays.
- **invoice_1010.txt**: the live VP held it until a PO or written rush authorization backs the $300 WidgetA rate ($250 catalog). Offline approves with that check as a payment condition.
- **invoice_1012.pdf**: both runs end PENDING_HUMAN, by different paths. Offline: the VP approves with conditions, the critic objects twice (the rename, then the total just under $10K) and the loop deadlocks after 2 rounds. Live: the VP held it straight away (unverified rename, risk 64 above the threshold of 50, total just under $10K). The critic only reviews approvals, so it never ran.
- **invoice_1004_revised.json**: same decision (PENDING_HUMAN) in both runs now. Offline holds it on the watch-list hit; live holds it because the risk score (72) is above the high-risk threshold of 50.

Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule score (it can never lower it). None of those increases crossed a threshold except the ones above.
"""


def main() -> None:
    off, live = load("offline"), load("live")
    lo = {r["file"]: r for r in live["rows"]}
    out = [
        "# Run log: all 20 sample invoices",
        "",
        "Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026:",
        "",
        "- **Offline** (`--offline`, deterministic VP and critic rules): `runs/demo/offline/`",
        f"- **Live** (`--mode live`, {live.get('model')} via the xAI API for risk review, VP and critic): `runs/demo/live/`",
        "",
        "Each folder has `trace.jsonl` (every agent step), `summary.json` and `report.md`. "
        "Hard rules (any blocking flag) decide 12 of 20 without any LLM call, so both runs agree on those by construction. "
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
            f"| {r['file']} | {money(r['total_usd'])} | {r['risk']} / {l['risk']} | {dec(r)} | {dec(l)}{differs} | {r['payment']} / {l['payment']} |"
        )
    for name, s in (("Offline", off), ("Live", live)):
        n, amt, rej, held = counts(s["rows"])
        out.append("")
        out.append(f"{name}: {n} paid ({money(amt)}), {rej} rejected, {held} held for a human.")
    out += ["", DIFFS, "## Live reasons (first reason per invoice the VP decided)", "",
            "| File | Decision | Reason | Conditions |", "|---|---|---|---|"]
    for l in live["rows"]:
        if l["decided_by"] == "hard_rules":
            continue
        cond = "; ".join(l["conditions"]) or "none"
        out.append(f"| {l['file']} | {l['decision']} | {l['reason']} | {cond} |")
    (ROOT / "docs" / "run_log.md").write_text("\n".join(out) + "\n")
    print("wrote docs/run_log.md")


if __name__ == "__main__":
    main()
