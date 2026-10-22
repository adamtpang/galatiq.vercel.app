"""Export the committed demo runs (runs/demo/{offline,live}) to web/data/demo.json.

The web page only replays this file. Every number on it comes from these traces.
Usage: python scripts/export_web_data.py
"""
from __future__ import annotations

import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from invoice_agents.config import load_policy  # noqa: E402

RUNS = ROOT / "runs" / "demo"
OUT = ROOT / "web" / "data" / "demo.json"


def export_run(name: str) -> dict:
    d = RUNS / name
    summary = json.loads((d / "summary.json").read_text())
    by_file: "OrderedDict[str, list[dict]]" = OrderedDict()
    for line in (d / "trace.jsonl").read_text().splitlines():
        ev = json.loads(line)
        by_file.setdefault(ev["source"], []).append(ev)
    rows = {r["file"]: r for r in summary["rows"]}
    invoices = []
    for file, events in by_file.items():
        r = rows[file]
        inv = next((e["detail"]["invoice"] for e in events if e["step"] == "extracted"), None)
        val = next((e["detail"] for e in events if e["agent"] == "validation" and e["step"] == "validate"), {})
        risk = next((e["detail"] for e in events if e["agent"] == "risk" and e["step"] == "assess"), {})
        decision = next((e["detail"] for e in events if e["agent"] == "approval" and e["step"] == "decide"), {})
        pay = next((e["detail"] for e in events if e["agent"] == "payment" and e["step"] in ("paid", "failed",
                                                                                          "idempotency_skip")), None)
        t0 = events[0]["ts"]
        timeline = []
        for e in events:
            if e["step"] == "node_done":
                continue
            det = dict(e["detail"])
            if e["step"] == "extracted":
                det = {"mode": det.get("mode")}
            if e["agent"] == "validation":
                det = {"flags": [f["code"] for f in det.get("flags", [])], "blocking": det.get("blocking", [])}
            if e["agent"] == "risk":
                det = {"score": det.get("score"), "deterministic_score": det.get("deterministic_score"),
                       "reasons": det.get("reasons", []), "llm": det.get("llm")}
            if e["step"] == "decide":
                det = {k: det.get(k) for k in ("status", "decided_by", "critique_rounds", "reasons", "conditions")}
            timeline.append({"agent": e["agent"], "step": e["step"], "ms": round((e["ts"] - t0) * 1000), "detail": det})
        invoices.append({
            "file": file, "number": r["invoice"], "vendor": r["vendor"], "total_usd": r["total_usd"],
            "currency": inv.get("currency") if inv else None, "total": inv.get("total") if inv else None,
            "items": [{k: li.get(k) for k in ("sku_raw", "sku", "qty", "unit_price", "note")} for li in (inv or {}).get("items", [])],
            "flags": val.get("flags", []), "risk": {"score": risk.get("score"), "reasons": risk.get("reasons", []),
                                                    "signals": risk.get("signals", []), "llm": risk.get("llm")},
            "decision": {k: decision.get(k) for k in ("status", "decided_by", "critique_rounds", "reasons",
                                                       "conditions", "arguments")},
            "payment": pay or {"status": r["payment"].split(" ")[0]},
            "timeline": timeline,
        })
    return {"name": name, "mode": summary["mode"], "model": summary.get("model"), "invoices": invoices}


if __name__ == "__main__":
    pol = load_policy()
    data = {"policy": {"approval_threshold_usd": pol["approval"]["approval_threshold_usd"],
                       "near_limit_usd": pol["approval"]["near_limit_usd"],
                       "high_risk_score": pol["approval"]["high_risk_score"],
                       "critic_max_rounds": pol["approval"]["critic_max_rounds"]},
            "runs": {n: export_run(n) for n in ("offline", "live") if (RUNS / n / "summary.json").exists()}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":"), default=str))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): " + ", ".join(f"{k}={len(v['invoices'])}" for k, v in data["runs"].items()))
