"""Compare two runs folder by folder: per-invoice decision, reason and risk, Grok calls and cost.

  python scripts/compare_runs.py runs/cache-1 runs/cache-2 > evals/results/cache_repeatability.md
  python scripts/compare_runs.py runs/cache-1 runs/cache-2 --json evals/results/cache_repeatability.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SAME_KEYS = ("decision", "decided_by", "risk", "reason", "block_flags", "warn_flags", "conditions")


def stats(run: Path) -> dict:
    calls = ticks = 0
    ts, hits, misses, models = [], 0, 0, set()
    for line in open(run / "trace.jsonl", encoding="utf-8"):
        e = json.loads(line)
        ts.append(e["ts"])
        u = e.get("detail", {}).get("llm")
        if e["step"] == "node_done" and u:
            calls += u["calls"]
            ticks += u["cost_in_usd_ticks"] or 0
        if e["step"] == "model_pin":
            hits += e["detail"]["hits"]
            misses += e["detail"]["misses"]
            models |= set(e["detail"]["returned_models"])
    return {"api_calls": calls, "billed_usd": round(ticks / 1e10, 4), "span_s": round(max(ts) - min(ts), 1),
            "cache_hits": hits, "cache_misses": misses, "models": sorted(models)}


def main(a: str, b: str, json_out: str | None = None) -> int:
    ra, rb = json.loads((Path(a) / "summary.json").read_text(encoding="utf-8")), json.loads((Path(b) / "summary.json").read_text(encoding="utf-8"))
    sa, sb = stats(Path(a)), stats(Path(b))
    rows = []
    same = 0
    for x, y in zip(ra["rows"], rb["rows"]):
        eq = x["file"] == y["file"] and all(x[k] == y[k] for k in SAME_KEYS)
        same += eq
        rows.append(f"| {x['file']} | {x['decision']} | {y['decision']} | {x['risk']} | {y['risk']} | {x['payment']} | {y['payment']} | {'yes' if eq else 'NO'} |")
    paid = sum(r["total_usd"] or 0 for r in ra["rows"] if r["decision"] == "APPROVED")
    count = lambda rs, d: sum(r["decision"] == d for r in rs)
    out = [f"# Live re-run with the decision cache: {Path(a).name} vs {Path(b).name}", "",
           f"Model {ra['model']}. Same database, cache on. Decision, decided by, risk, reason, flags and conditions "
           f"identical for {same} of {len(ra['rows'])} invoices. Code commit {ra.get('commit') or 'not recorded'} "
           f"(second run {rb.get('commit') or 'not recorded'}).", "",
           "| | first run | second run |", "|---|---|---|",
           f"| Approved / rejected / held | {count(ra['rows'], 'APPROVED')} / {count(ra['rows'], 'REJECTED')} / {count(ra['rows'], 'PENDING_HUMAN')} "
           f"| {count(rb['rows'], 'APPROVED')} / {count(rb['rows'], 'REJECTED')} / {count(rb['rows'], 'PENDING_HUMAN')} |",
           f"| Approved total | ${paid:,.2f} | ${sum(r['total_usd'] or 0 for r in rb['rows'] if r['decision'] == 'APPROVED'):,.2f} |",
           f"| API calls | {sa['api_calls']} | {sb['api_calls']} |",
           f"| Grok answers stored / reused | {sa['cache_misses']} / {sa['cache_hits']} | {sb['cache_misses']} / {sb['cache_hits']} |",
           f"| Billed | ${sa['billed_usd']} | ${sb['billed_usd']} |",
           f"| Trace span | {sa['span_s']} s | {sb['span_s']} s |",
           f"| Model ids recorded (a cached answer keeps the id of its original call) | {', '.join(sa['models']) or 'none'} | {', '.join(sb['models']) or 'none'} |", "",
           "| file | decision 1 | decision 2 | risk 1 | risk 2 | payment 1 | payment 2 | identical |",
           "|---|---|---|---|---|---|---|---|", *rows, ""]
    if json_out:
        Path(json_out).write_text(json.dumps({
            "model": ra["model"], "runs": [Path(a).name, Path(b).name], "invoices": len(ra["rows"]), "identical": same,
            "compared": list(SAME_KEYS), "first": sa | {"approved_usd": round(paid, 2)}, "second": sb,
            "decisions": {k: [count(r["rows"], k) for r in (ra, rb)] for k in ("APPROVED", "REJECTED", "PENDING_HUMAN")},
            "commit": [ra.get("commit"), rb.get("commit")], "recorded_at": "2026-10-22"}, indent=1), encoding="utf-8")
    else:
        print("\n".join(out))
    return 0 if same == len(ra["rows"]) else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(main(args[0], args[1], args[args.index("--json") + 1] if "--json" in args else None))
