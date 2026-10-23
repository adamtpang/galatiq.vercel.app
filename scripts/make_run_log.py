"""Regenerate the tables in docs/run_log.md from runs/demo/{offline,live}/summary.json.

The prose sections below are written by hand and kept in this script so the
numbers and the words are updated together.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str) -> dict:
    return json.loads((ROOT / "runs" / "demo" / name / "summary.json").read_text(encoding="utf-8"))


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


def diffs(off: dict, live: dict) -> list[str]:
    """Where the two runs disagree, generated from the live reasons so the words match the committed run."""
    lo = {r["file"]: r for r in live["rows"]}
    out = ["## Where live and offline disagree", "",
           "Both runs use the same code and policy. Each line says which way the decision went; the reasons are the "
           "live VP's own, from `runs/demo/live/summary.json`.", ""]
    for r in off["rows"]:
        l = lo[r["file"]]
        if r["decision"] == l["decision"]:
            continue
        why = l["reason"] or "no reason recorded"
        if l["conditions"]:
            why += " Conditions: " + "; ".join(l["conditions"])
        out.append(f"- **{r['file']}**: offline {r['decision']} ({r['payment']}), live {l['decision']} (risk {l['risk']}, "
                   f"{l['payment']}). Live reason: {why}")
    out += ["", "Live results are not perfectly repeatable: the live eval run (`evals/results/live.md`) decided some of "
            "these invoices differently. Re-running the same invoices on the same database with the decision cache gives "
            "identical decisions (`evals/results/cache_repeatability.md`).", "",
            "Risk scores differ on most clean invoices because the live risk agent can add points on top of the rule "
            "score (it can never lower it).", ""]
    return out



def main() -> None:
    off, live = load("offline"), load("live")
    lo = {r["file"]: r for r in live["rows"]}
    out = [
        "# Run log: all 20 sample invoices",
        "",
        f"Two committed runs of `python main.py --batch data/invoices`, each on a fresh database, Oct 22 2026: "
        f"offline at commit {off.get('commit')}, live at commit {live.get('commit')}. The live run predates the review 3 "
        "fixes (76881f7); among the samples they change only 1014, which the offline run now holds (non-USD, decision 22) "
        "and the live run paid.",
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
    out += [""] + diffs(off, live) + ["## Live reasons (first reason per invoice the VP decided)", "",
            "| File | Decision | Reason | Conditions |", "|---|---|---|---|"]
    for l in live["rows"]:
        if l["decided_by"] in ("hard_rules", "hard_hold"):
            continue
        cond = "; ".join(l["conditions"]) or "none"
        out.append(f"| {l['file']} | {l['decision']} | {l['reason']} | {cond} |")
    (ROOT / "docs" / "run_log.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote docs/run_log.md")


if __name__ == "__main__":
    main()
