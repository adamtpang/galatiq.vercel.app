"""Five evals over the invoice agents.

  python -m evals            offline (default): no API key, no network, about 2 seconds
  python -m evals --live     also runs the pipeline and a Grok-only extraction live (needs XAI_API_KEY)

(a) extraction   per-field accuracy against the hand-checked evals/ground_truth.yaml
(b) agreement    live vs offline decision agreement, disagreements with reasons from the traces
(c) adversarial  catch rate on data/invoices_adversarial/ against evals/adversarial_expected.yaml
(d) cost         tokens for every LLM call, billed cost, latency per invoice and per batch
(e) unseen       legitimate invoices in layouts the parsers were never tuned on (data/invoices_unseen/)

Results go to evals/out/ (git-ignored): offline.{json,md}, with --live also live.{json,md} and the live
traces in runs/live/, and summary.md, which combines the fresh offline numbers with the latest live run
(this directory's, else the committed snapshot). Nothing tracked is modified. --write-snapshot writes the
committed snapshot instead (evals/results/ and web/data/evals.json).
"""
from __future__ import annotations

import argparse
import sys
import json
import re
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from invoice_agents import ROOT
from invoice_agents.agents.ingestion import llm_extract, resolve_skus
from invoice_agents.db import Inventory, connect
from invoice_agents.graph import make_context, run_batch
from invoice_agents.llm import GrokClient, LLMOutputError, LLMUnavailable, OfflineClient
from invoice_agents.models import Invoice, InvoiceState
from invoice_agents.parsers import read_source
from invoice_agents.pipeline import collect

EVALS = Path(__file__).resolve().parent
RESULTS = EVALS / "results"     # committed snapshot, written only with --write-snapshot
OUT = EVALS / "out"             # default output, git-ignored
SAMPLES, EXTRA, ADV = ROOT / "data" / "invoices", ROOT / "data" / "invoices_extra", ROOT / "data" / "invoices_adversarial"
UNSEEN = ROOT / "data" / "invoices_unseen"   # layouts the parsers were never tuned on (decision 14)
FIELDS = ["vendor", "invoice_number", "total", "line_items", "due_date"]
MIN_CONF = 0.85


def load_yaml(name: str) -> dict:
    return yaml.safe_load((EVALS / name).read_text(encoding="utf-8"))


def rel(p: str | Path) -> str:
    p = Path(p)
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:   # outside the repo (a temp dir): never write a machine path into committed results
        return f"(temporary, not kept)/{p.parent.name}/{p.name}"


# --- (a) extraction ------------------------------------------------------------------
def _t(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _num(s: Any) -> str | None:
    n = _t(s).upper()
    n = n[3:] if n.startswith("INV") else n
    return n or None


def item_key(li) -> str:
    return _t(li.sku if (li.sku and li.sku_confidence >= MIN_CONF) else li.sku_raw)


def predicted(inv: Invoice | None) -> dict | None:
    if inv is None:
        return None
    return {"vendor": inv.vendor, "invoice_number": inv.number, "total": inv.total,
            "due_date": inv.due_date.isoformat() if inv.due_date else None, "due_date_raw": inv.due_date_raw,
            "line_items": [[li.sku if (li.sku and li.sku_confidence >= MIN_CONF) else li.sku_raw, li.qty]
                           for li in inv.items]}


def score_invoice(inv: Invoice | None, gt: dict) -> dict:
    amb = gt.get("ambiguous") or {}
    got = predicted(inv)
    out = {}
    for f in FIELDS:
        exp = gt.get(f)
        if isinstance(exp, (datetime,)) or hasattr(exp, "isoformat"):
            exp = exp.isoformat()
        g = None if got is None else got[f]
        if got is None:
            ok = False
        elif f == "vendor":
            ok = _t(g) == _t(exp)
        elif f == "invoice_number":
            ok = _num(g) == _num(exp)
        elif f == "total":
            ok = (g is None and exp is None) or (g is not None and exp is not None and abs(g - float(exp)) < 0.005)
        elif f == "due_date":
            ok = g == exp
        else:
            ok = Counter((_t(n), float(q)) for n, q in g) == Counter((_t(n), float(q)) for n, q in exp)
        status = "ambiguous" if f in amb else ("correct" if ok else ("failed" if got is None else "wrong"))
        out[f] = {"status": status, "expected": exp, "got": g}
        if f in amb:
            out[f]["note"] = amb[f]
    return out


def accuracy(scores: dict[str, dict]) -> dict:
    per = {}
    for f in FIELDS:
        st = [s[f]["status"] for s in scores.values()]
        scored = [x for x in st if x != "ambiguous"]
        ok = sum(x == "correct" for x in scored)
        per[f] = {"correct": ok, "scored": len(scored), "ambiguous": st.count("ambiguous"),
                  "accuracy": round(ok / len(scored), 4) if scored else None}
    tot_ok = sum(v["correct"] for v in per.values())
    tot = sum(v["scored"] for v in per.values())
    misses = [{"file": k, "field": f, **v} for k, s in scores.items() for f, v in s.items() if v["status"] in ("wrong", "failed")]
    return {"per_field": per, "overall": {"correct": tot_ok, "scored": tot, "accuracy": round(tot_ok / tot, 4)},
            "files": len(scores), "misses": misses}


def extraction_eval(states: list[InvoiceState], gt: dict) -> dict:
    by = {rel(s.source): s for s in states}
    scores = {k: score_invoice(by[k].invoice if k in by else None, v) for k, v in gt.items()}
    return accuracy(scores) | {"scores": scores}


def grok_extract_all(gt: dict, workers: int = 4) -> tuple[dict, list[dict]]:
    """Grok-only extraction of every ground-truth file (the live extractor, not the parser)."""
    with connect(Path(tempfile.mkdtemp()) / "inv.db") as conn:
        inventory = Inventory(conn)

    def one(name: str):
        client = GrokClient()
        path = ROOT / name
        raw, fmt = read_source(path)
        t0 = time.monotonic()
        try:
            inv, _ = llm_extract(raw, str(path), fmt, client)
            resolve_skus(inv, inventory)
        except (LLMOutputError, LLMUnavailable) as e:
            inv = None
            print(f"  {name}: Grok extraction failed: {e}")
        return name, inv, {"file": name, "wall_s": round(time.monotonic() - t0, 2), "calls": client.usage_log}

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, gt))
    scores = {n: score_invoice(inv, gt[n]) for n, inv, _ in res}
    return accuracy(scores) | {"scores": scores}, [u for _, _, u in res]


# --- pipeline runs and trace rows ----------------------------------------------------
def run_pipeline(llm, runs_dir: Path, db_dir: Path) -> dict:
    """Samples, then the adversarial set on the same database (so a copy of INV-1001 has an
    original), then the extra invoices on a fresh database."""
    out: dict[str, Any] = {"wall_s": {}}
    ctx = make_context(llm=llm, db=str(db_dir / "main.db"), runs_dir=runs_dir, run_id="main")
    for group, d in (("samples", SAMPLES), ("adversarial", ADV)):
        t0 = time.monotonic()
        out[group] = run_batch(collect(d), ctx)
        out["wall_s"][group] = round(time.monotonic() - t0, 2)
    ctx2 = make_context(llm=llm, db=str(db_dir / "extra.db"), runs_dir=runs_dir, run_id="extra")
    t0 = time.monotonic()
    out["extra"] = run_batch(collect(EXTRA), ctx2)
    out["wall_s"]["extra"] = round(time.monotonic() - t0, 2)
    ctx3 = make_context(llm=llm, db=str(db_dir / "unseen.db"), runs_dir=runs_dir, run_id="unseen")
    t0 = time.monotonic()
    out["unseen"] = run_batch(collect(UNSEEN), ctx3)
    out["wall_s"]["unseen"] = round(time.monotonic() - t0, 2)
    out["traces"] = [rel(runs_dir / n / "trace.jsonl") for n in ("main", "extra", "unseen")]
    return out


# --- (e) unseen layouts ----------------------------------------------------------------
def unseen_eval(states: list[InvoiceState], expected: dict, mode: str) -> dict:
    """Legitimate invoices in layouts nobody tuned the parsers for. Offline the bar is "not rejected" (held or
    paid); live it is "read correctly and paid". Expectations are in evals/unseen_expected.yaml."""
    cases = []
    for s in states:
        name = Path(s.source).name
        exp = expected[name]
        inv = s.invoice
        status = s.decision.status.value if s.decision else "UNKNOWN"
        got = predicted(inv)
        read_ok = bool(got) and _t(got["vendor"]) == _t(exp["vendor"]) and got["total"] is not None \
            and abs(got["total"] - float(exp["total"])) < 0.005 \
            and Counter((_t(n), float(q)) for n, q in got["line_items"]) == Counter((_t(n), float(q)) for n, q in exp["line_items"])
        cases.append({"file": name, "decision": status, "decided_by": s.decision.decided_by if s.decision else None,
                      "extraction_mode": s.extraction_mode, "read_correctly": read_ok,
                      "paid": (s.payment or {}).get("status") == "paid", "meets_expectation": status in exp[mode],
                      "reason": (s.decision.reasons or [""])[0] if s.decision else ""})
    n = len(cases)
    return {"cases": cases, "total": n, "rejected": sum(c["decision"] == "REJECTED" for c in cases),
            "held": sum(c["decision"] == "PENDING_HUMAN" for c in cases), "paid": sum(c["paid"] for c in cases),
            "read_correctly": sum(c["read_correctly"] for c in cases),
            "met": sum(c["meets_expectation"] for c in cases)}


USAGE_KEYS = ("calls", "prompt_tokens", "cached_prompt_tokens", "completion_tokens", "reasoning_tokens")


def trace_rows(*paths: str | Path) -> dict[str, dict]:
    """Per-invoice decision, reasons, risk, latency and LLM usage, read back from trace.jsonl files."""
    rows: dict[str, dict] = {}
    for path in paths:
        for line in Path(ROOT / path if not Path(path).is_absolute() else path).read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            r = rows.setdefault(e["source"], {"file": e["source"], "invoice": e.get("invoice"), "decision": None,
                                              "ms": 0.0, "llm": {k: 0 for k in USAGE_KEYS} | {"cost_in_usd_ticks": 0,
                                                                                            "ticks_complete": True,
                                                                                            "max_prompt_tokens": 0},
                                              "tool_calls": 0, "debate": [], "paid": None})
            d = e["detail"]
            if e["step"] == "decide":
                r.update(decision=d["status"], decided_by=d.get("decided_by"), reasons=d.get("reasons", []),
                         conditions=d.get("conditions", []), risk_score=d.get("risk_score"))
            elif e["step"] == "error" and r["decision"] is None:
                r.update(decision="PENDING_HUMAN", decided_by="error", reasons=[d.get("error")])
            elif e["step"] == "assess":
                r["risk"] = {"score": d.get("score"), "deterministic": d.get("deterministic_score"),
                             "grok_reasons": (d.get("llm") or {}).get("extra_reasons", []),
                             "grok_error": (d.get("llm") or {}).get("error")}
            elif e["step"] == "tool_call":
                r["tool_calls"] += 1
            elif e["step"] in ("vp_propose", "critic_review", "vp_revise"):
                r["debate"].append({"step": e["step"], **{k: d.get(k) for k in ("round", "decision", "verdict", "reasons", "reason")
                                                          if d.get(k) is not None}})
            elif e["step"] == "paid":
                r["paid"] = d.get("amount")
            elif e["step"] == "node_done":
                r["ms"] += d.get("ms", 0)
                u = d.get("llm")
                if u:
                    for k in USAGE_KEYS:
                        r["llm"][k] += u.get(k, 0)
                    r["llm"]["max_prompt_tokens"] = max(r["llm"]["max_prompt_tokens"], u.get("max_prompt_tokens", 0))
                    if u.get("cost_in_usd_ticks") is None:
                        r["llm"]["ticks_complete"] = False
                    else:
                        r["llm"]["cost_in_usd_ticks"] += u["cost_in_usd_ticks"]
    for r in rows.values():
        r["ms"] = round(r["ms"], 1)
    return rows


# --- (b) agreement -------------------------------------------------------------------
def agreement(offline: dict[str, dict], live: dict[str, dict], files: list[str], label: str) -> dict:
    common = [f for f in files if f in offline and f in live]
    dis = []
    for f in common:
        o, l = offline[f], live[f]
        if o["decision"] != l["decision"]:
            dis.append({"file": f, "offline": o["decision"], "offline_by": o.get("decided_by"),
                        "offline_reasons": o.get("reasons", []), "live": l["decision"], "live_by": l.get("decided_by"),
                        "live_reasons": l.get("reasons", []), "live_conditions": l.get("conditions", []),
                        "live_risk": (l.get("risk") or {}).get("score"),
                        "offline_risk": (o.get("risk") or {}).get("score"),
                        "grok_risk_reasons": (l.get("risk") or {}).get("grok_reasons", [])})
    n = len(common)
    # Repeatability metric, not a policy: if a disagreement between live and offline sent the invoice to a
    # person, how many would go, and how much would one side have paid without that check.
    one_side = [{"file": d["file"], "paid_by": "live" if d["live"] == "APPROVED" else "offline",
                 "amount": (live[d["file"]] if d["live"] == "APPROVED" else offline[d["file"]]).get("paid")}
                for d in dis if "APPROVED" in (d["live"], d["offline"])]
    both = [f for f in common if offline[f]["decision"] == live[f]["decision"] == "APPROVED"]
    routing = {"to_human": len(dis), "paid_on_one_side": one_side,
               "paid_on_one_side_usd": round(sum(x["amount"] or 0 for x in one_side), 2),
               "paid_by_both": len(both)}
    return {"label": label, "invoices": n, "agree": n - len(dis), "rate": round((n - len(dis)) / n, 4) if n else None,
            "disagreements": dis, "disagreement_routing": routing}


# --- (c2) the duplicate traps across separate runs -------------------------------------
def separate_run_eval(expected: dict, db_dir: Path, llm=None) -> dict:
    """The adversarial set as its own later run, after the samples were processed in an earlier run on the
    same database (what an AP team does day to day). Offline by default; --separate-run-live runs it with Grok
    (decision cache off, so every answer is a fresh call)."""
    db = str(db_dir / "separate.db")
    llm = llm or OfflineClient()
    run_batch(collect(SAMPLES), make_context(llm=llm, db=db, runs_dir=None, run_id="separate-samples", cache=False))
    states = run_batch(collect(ADV), make_context(llm=llm, db=db, runs_dir=None, run_id="separate-adversarial", cache=False))
    res = adversarial_eval(states, expected)
    dup = next(c for c in res["cases"] if c["file"] == "invoice_3006_duplicate_new_number.txt")
    return res | {"duplicate_3006": {k: dup[k] for k in ("decision", "decided_by", "caught", "flags")}
                  | {"reason": (dup["reasons"] or [""])[0]}}


# --- (c) adversarial -----------------------------------------------------------------
def adversarial_eval(states: list[InvoiceState], expected: dict) -> dict:
    cases = []
    for s in states:
        name = Path(s.source).name
        exp = expected[name]
        status = s.decision.status.value if s.decision else "UNKNOWN"
        paid = (s.payment or {}).get("status") == "paid"
        caught = status != "APPROVED" and not paid
        risk = s.risk or {}
        cases.append({"file": name, "trap": exp["trap"], "expected": exp["expected"], "decision": status,
                      "decided_by": s.decision.decided_by if s.decision else None, "paid": paid, "caught": caught,
                      "risk_score": risk.get("score"),
                      "signals": [x["signal"] for x in risk.get("signals", [])],
                      "flags": [f.code for f in s.flags if f.severity.value != "info"],
                      "grok_reasons": (risk.get("llm") or {}).get("extra_reasons", []),
                      "reasons": s.decision.reasons if s.decision else []})
    caught = sum(c["caught"] for c in cases)
    return {"cases": cases, "caught": caught, "total": len(cases), "catch_rate": round(caught / len(cases), 4),
            "missed": [c["file"] for c in cases if not c["caught"]]}


# --- (d) cost and latency ------------------------------------------------------------
def price(u: dict, pricing: dict) -> float:
    p = pricing["usd_per_million_tokens"]
    if u.get("max_prompt_tokens", 0) >= pricing["long_context"]["threshold_prompt_tokens"]:
        p = pricing["long_context"]
    uncached = u["prompt_tokens"] - u["cached_prompt_tokens"]
    return (uncached * p["input"] + u["cached_prompt_tokens"] * p["cached_input"]
            + (u["completion_tokens"] + u["reasoning_tokens"]) * p["output"]) / 1e6


def cost_eval(rows: dict[str, dict], groups: dict[str, list[str]], wall: dict, pricing: dict | None) -> dict:
    per, batches = [], {}
    for g, files in groups.items():
        tot = {k: 0 for k in USAGE_KEYS} | {"ms": 0.0, "billed_usd": 0.0, "list_price_usd": 0.0}
        for f in files:
            r = rows[f]
            u = r["llm"]
            billed = u["cost_in_usd_ticks"] / 1e10 if u["calls"] and u["ticks_complete"] else (0.0 if not u["calls"] else None)
            lp = price(u, pricing) if pricing else None
            per.append({"file": f, "group": g, "decision": r["decision"], "latency_s": round(r["ms"] / 1000, 3),
                        **{k: u[k] for k in USAGE_KEYS}, "tool_calls": r["tool_calls"],
                        "billed_usd": None if billed is None else round(billed, 6),
                        "list_price_usd": None if lp is None else round(lp, 6)})
            for k in USAGE_KEYS:
                tot[k] += u[k]
            tot["ms"] += r["ms"]
            tot["billed_usd"] += billed or 0.0
            tot["list_price_usd"] += lp or 0.0
        n = len(files)
        batches[g] = {"invoices": n, **{k: tot[k] for k in USAGE_KEYS},
                      "latency_sum_s": round(tot["ms"] / 1000, 2), "wall_s": wall.get(g),
                      "latency_mean_s": round(tot["ms"] / 1000 / n, 2) if n else None,
                      "latency_mean_ms": round(tot["ms"] / n, 1) if n else None,
                      "billed_usd": round(tot["billed_usd"], 4), "billed_usd_per_invoice": round(tot["billed_usd"] / n, 4) if n else None,
                      "list_price_usd": round(tot["list_price_usd"], 4)}
    return {"per_invoice": per, "batches": batches}


def extraction_cost(usage: list[dict], pricing: dict) -> dict:
    calls = [c for u in usage for c in u["calls"]]
    agg = {"calls": len(calls), **{k: sum(c[k] for c in calls) for k in USAGE_KEYS[1:]},
           "max_prompt_tokens": max((c["prompt_tokens"] for c in calls), default=0)}
    ticks = [c["cost_in_usd_ticks"] for c in calls]
    agg["billed_usd"] = round(sum(ticks) / 1e10, 4) if calls and None not in ticks else None
    agg["list_price_usd"] = round(price(agg, pricing), 4)
    agg["files"] = len(usage)
    agg["wall_s_per_file_mean"] = round(sum(u["wall_s"] for u in usage) / len(usage), 2) if usage else None
    return agg


# --- reporting -----------------------------------------------------------------------
def pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def frac(d: dict) -> str:
    return f"{d['correct']}/{d['scored']} ({pct(d['accuracy'])})"


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def agreements(off: dict, live: dict | None) -> list[dict]:
    """Agreement rows for the summary and the site. The committed-demo-runs row is always recomputed from the
    committed runs/demo files (the offline result), so it stays right when the demo runs are regenerated after a
    live eval; the eval-run rows come from the live result."""
    demo = [a for a in off["agreement"] if a["label"].startswith("committed demo runs")]
    rest = [a for a in (live or {}).get("agreement", []) if not a["label"].startswith("committed demo runs")]
    return demo + rest


def summary_md(off: dict, live: dict | None) -> str:
    L = [f"# Eval summary", "",
         f"Offline: generated {off['generated_at']}, base commit {off.get('commit')}. "
         + (f"Live ({live['model']}): run {live['generated_at']}, base commit {live.get('commit')}." if live else "No live run on file."),
         "", "| Eval | Offline | Live |", "|---|---|---|"]
    lx = live["extraction"] if live else None
    for f in FIELDS:
        o = off["extraction"]["pipeline"]["per_field"][f]
        lv = f"{frac(lx['pipeline']['per_field'][f])} pipeline; {frac(lx['grok_only']['per_field'][f])} Grok-only" if lx else "-"
        L.append(f"| (a) Extraction: {f} | {frac(o)} | {lv} |")
    o = off["extraction"]["pipeline"]["overall"]
    lv = (f"{frac(lx['pipeline']['overall'])} pipeline; {frac(lx['grok_only']['overall'])} Grok-only" if lx else "-")
    L.append(f"| (a) Extraction: all fields | {frac(o)} | {lv} |")
    for a in agreements(off, live):
        L.append(f"| (b) Decision agreement, {a['label'].replace('this eval run', 'eval live run')} | - | {a['agree']}/{a['invoices']} ({pct(a['rate'])}) |")
    oa = off["adversarial"]
    la = live["adversarial"] if live else None
    L.append(f"| (c) Adversarial catch rate | {oa['caught']}/{oa['total']} ({pct(oa['catch_rate'])}) | "
             + (f"{la['caught']}/{la['total']} ({pct(la['catch_rate'])})" if la else "-") + " |")
    sr = off.get("adversarial_separate_run")
    if sr:
        d = sr["duplicate_3006"]
        L.append(f"| (c) Adversarial set as a separate later run (after the samples) | {sr['caught']}/{sr['total']} "
                 f"({pct(sr['catch_rate'])}); 3006 {d['decision']} | - (rules only; the duplicate checks run before any Grok call) |")
    ou, lu = off.get("unseen"), (live or {}).get("unseen")
    if ou:
        L.append(f"| (e) Unseen layouts ({ou['total']}, never tuned for): not rejected; read correctly and paid | "
                 f"{ou['total'] - ou['rejected']}/{ou['total']} not rejected ({ou['held']} held, {ou['paid']} paid) | "
                 + (f"{lu['read_correctly']}/{lu['total']} read correctly, {lu['paid']}/{lu['total']} paid, "
                    f"{lu['held']} held, {lu['rejected']} rejected" if lu else "-") + " |")
    for a in agreements(off, live):
        r = a.get("disagreement_routing")
        if r and "samples" in a["label"]:
            L.append(f"| (b) Disagreement routing (a metric; sending disagreements to a person is a plan, not policy), "
                     f"{a['label'].split(',')[0].replace('this eval run', 'eval live run')} | - | "
                     f"{r['to_human']} of {a['invoices']} would go to a person; without that check one side paid "
                     f"{len(r['paid_on_one_side'])} of them (${r['paid_on_one_side_usd']:,.2f}) |")
    if live:
        b = live["cost_latency"]["batches"]
        s = b["samples"]
        L.append(f"| (d) 20 samples: LLM calls, tokens | 0 | {s['calls']} calls; prompt {s['prompt_tokens']:,} "
                 f"(cached {s['cached_prompt_tokens']:,}), completion {s['completion_tokens']:,}, reasoning {s['reasoning_tokens']:,} |")
        L.append(f"| (d) 20 samples: billed cost | $0 | ${s['billed_usd']:.4f} total, ${s['billed_usd_per_invoice']:.4f} per invoice |")
        ob = off["cost_latency"]["batches"]["samples"]
        L.append(f"| (d) 20 samples: latency | {ob.get('latency_mean_ms', round(ob['latency_sum_s'] * 1000 / ob['invoices'], 1))} ms mean per invoice, {ob['wall_s']}s batch | "
                 f"{s['latency_mean_s']}s mean per invoice, {s['wall_s']}s batch |")
    L += ["", "Details: `offline.md` and `live.md` next to this file."]
    return "\n".join(L) + "\n"


def lat(b: dict) -> str:
    ms = b.get("latency_mean_ms", round(b["latency_sum_s"] * 1000 / b["invoices"], 1) if b["invoices"] else None)
    return "-" if ms is None else (f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms} ms")


def detail_md(res: dict) -> str:
    live = res["mode"] == "live"
    L = [f"# Eval results ({res['mode']}{', ' + res['model'] if res.get('model') else ''})", "",
         f"Generated {res['generated_at']}, base commit {res.get('commit')}.", "", "## (a) Extraction accuracy", "",
         "Ground truth: `evals/ground_truth.yaml`, hand-checked from the source files. Ambiguous fields are not scored.", ""]
    ex = res["extraction"]
    heads = ["pipeline"] + (["grok_only"] if live else [])
    L += ["| Field | " + " | ".join(heads) + " |", "|---|" + "---|" * len(heads)]
    for f in FIELDS + ["overall"]:
        L.append(f"| {f} | " + " | ".join(frac(ex[h]["per_field"][f] if f != "overall" else ex[h]["overall"])
                                           + (f", {ex[h]['per_field'][f]['ambiguous']} ambiguous" if f != "overall" and ex[h]['per_field'][f]['ambiguous'] else "")
                                           for h in heads) + " |")
    for h in heads:
        L += ["", f"Misses ({h}):", ""]
        L += [f"- {m['file']} {m['field']}: expected {m['expected']!r}, got {m['got']!r} ({m['status']})" for m in ex[h]["misses"]] or ["- none"]
    if live:
        c = res["cost_latency"]["grok_only_extraction"]
        L += ["", f"Grok-only extraction: {c['calls']} calls over {c['files']} files, billed ${c['billed_usd']}, "
                  f"mean {c['wall_s_per_file_mean']}s per file."]
    L += ["", "## (b) Live vs offline decision agreement", ""]
    if res["mode"] == "live":
        L += ["The committed demo runs (runs/demo/offline vs runs/demo/live) are compared in `offline.md` and "
              "`summary.md`, recomputed from the committed files each time, so they stay right when the demo runs "
              "are regenerated. This file covers the eval's own live run.", ""]
    for a in (x for x in res["agreement"] if res["mode"] != "live" or not x["label"].startswith("committed demo runs")):
        L += [f"**{a['label']}**: {a['agree']}/{a['invoices']} agree ({pct(a['rate'])}).", ""]
        for d in a["disagreements"]:
            L.append(f"- {d['file']}: offline {d['offline']} ({d['offline_by']}, risk {d['offline_risk']}), "
                     f"live {d['live']} ({d['live_by']}, risk {d['live_risk']}). Live reasons: "
                     + "; ".join(d["live_reasons"]) + (". Conditions: " + "; ".join(d["live_conditions"]) if d["live_conditions"] else "")
                     + (". Grok risk notes: " + "; ".join(d["grok_risk_reasons"]) if d["grok_risk_reasons"] else ""))
        L.append("")
    a = res["adversarial"]
    L += ["## (c) Adversarial set", "", f"Caught (not approved, not paid): {a['caught']}/{a['total']} ({pct(a['catch_rate'])}).", "",
          "| File | Trap | Decision | Caught | Risk | Signals and flags |", "|---|---|---|---|---|---|"]
    for c in a["cases"]:
        L.append(f"| {c['file']} | {c['trap']} | {c['decision']} ({c['decided_by']}) | {'yes' if c['caught'] else 'NO'} | "
                 f"{c['risk_score']} | {', '.join(c['signals'] + c['flags']) or '-'} |")
    sr = res.get("adversarial_separate_run")
    if sr:
        L += ["", "### (c2) Separate later run", "",
              "The samples run first; the adversarial set runs later as its own run on the same database, so the "
              "duplicate checks must use stored history. Rules only (offline): these checks run before any Grok call.", "",
              f"Caught: {sr['caught']}/{sr['total']} ({pct(sr['catch_rate'])}). Missed: {', '.join(sr['missed']) or 'none'}.", "",
              f"3006: {sr['duplicate_3006']['decision']} ({sr['duplicate_3006']['decided_by']}). {sr['duplicate_3006']['reason']}"]
    routing = [a for a in res["agreement"] if a.get("disagreement_routing")
               and (res["mode"] != "live" or not a["label"].startswith("committed demo runs"))]
    if routing:
        L += ["", "### Repeatability: disagreement routing (a metric, not a policy)", "",
              "If every invoice where live and offline disagree went to a person:", ""]
        for a in routing:
            r = a["disagreement_routing"]
            paid = "; ".join(f"{x['file']} paid by {x['paid_by']} (${(x['amount'] or 0):,.2f})" for x in r["paid_on_one_side"]) or "none"
            L.append(f"- {a['label']}: {r['to_human']} of {a['invoices']} to a person; paid on one side only: {paid}; "
                     f"approved by both: {r['paid_by_both']}.")
    u = res.get("unseen")
    if u:
        L += ["", "## (e) Unseen layouts", "",
              "Legitimate invoices in layouts the parsers were never tuned on (data/invoices_unseen, expectations in "
              "evals/unseen_expected.yaml, written before the first run). Offline the bar is not rejected; live it is "
              "read correctly and paid.", "",
              f"Rejected {u['rejected']}, held {u['held']}, paid {u['paid']}, read correctly {u['read_correctly']} "
              f"of {u['total']}; met the expectation: {u['met']}/{u['total']}.", "",
              "| File | Decision | Extraction | Read correctly | Paid | Reason |", "|---|---|---|---|---|---|"]
        for c in u["cases"]:
            L.append(f"| {c['file']} | {c['decision']} ({c['decided_by']}) | {c['extraction_mode']} | "
                     f"{'yes' if c['read_correctly'] else 'no'} | {'yes' if c['paid'] else 'no'} | "
                     f"{c['reason'].replace('|', '/')[:160]} |")
    cl = res["cost_latency"]
    L += ["", "## (d) Cost and latency", ""]
    if live:
        L += [f"Every LLM call is counted (cross-check reading, extraction repair, risk tool rounds, risk review, VP, critic, memo). Billed cost is "
              f"the API's `cost_in_usd_ticks`; list price is recomputed from {cl['pricing_source']}.", ""]
    L += ["| Batch | Invoices | LLM calls | Prompt (cached) | Completion | Reasoning | Billed USD | List price USD | Latency mean per invoice | Batch wall s |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for g, b in cl["batches"].items():
        L.append(f"| {g} | {b['invoices']} | {b['calls']} | {b['prompt_tokens']:,} ({b['cached_prompt_tokens']:,}) | "
                 f"{b['completion_tokens']:,} | {b['reasoning_tokens']:,} | {b['billed_usd']:.4f} | {b['list_price_usd']:.4f} | "
                 f"{lat(b)} | {b['wall_s']} |")
    L += ["", "| File | Decision | Calls | Tools | Prompt | Completion | Reasoning | Billed USD | Latency s |", "|---|---|---|---|---|---|---|---|---|"]
    for p in cl["per_invoice"]:
        L.append(f"| {p['file']} | {p['decision']} | {p['calls']} | {p['tool_calls']} | {p['prompt_tokens']:,} | {p['completion_tokens']:,} | "
                 f"{p['reasoning_tokens']:,} | {p['billed_usd']} | {p['latency_s']} |")
    return "\n".join(L) + "\n"


def evaluate(mode: str = "offline", workdir: Path | None = None, keep_traces: Path | None = None,
             live_ref: dict | None = None) -> dict:
    """Run every eval in one mode and return the result dict (no files written)."""
    gt, expected = load_yaml("ground_truth.yaml"), load_yaml("adversarial_expected.yaml")
    pricing = load_yaml("pricing.yaml")
    workdir = Path(workdir or tempfile.mkdtemp(prefix="evals-"))
    llm = GrokClient() if mode == "live" else OfflineClient()
    runs_dir = keep_traces or workdir / "runs"
    run = run_pipeline(llm, runs_dir, workdir)
    res: dict[str, Any] = {"mode": mode, "model": getattr(llm, "model", None),
                           "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
                           "commit": git_commit(), "traces": run["traces"]}
    res["extraction"] = {"pipeline": extraction_eval(run["samples"] + run["extra"], gt)}
    rows = trace_rows(*[runs_dir / n / "trace.jsonl" for n in ("main", "extra", "unseen")])
    groups = {"samples": [Path(s.source).name for s in run["samples"]],
              "adversarial": [Path(s.source).name for s in run["adversarial"]],
              "extra": [Path(s.source).name for s in run["extra"]],
              "unseen": [Path(s.source).name for s in run["unseen"]]}
    res["adversarial"] = adversarial_eval(run["adversarial"], expected)
    res["unseen"] = unseen_eval(run["unseen"], load_yaml("unseen_expected.yaml"), mode)
    if mode == "offline":
        res["adversarial_separate_run"] = separate_run_eval(expected, workdir)
    res["cost_latency"] = cost_eval(rows, groups, run["wall_s"], pricing) | {
        "pricing_source": "docs.x.ai/docs/models (grok-4.7: $2.00 input, $0.50 cached input, $6.00 output per 1M tokens; "
                          "reasoning billed as output), fetched " + pricing["fetched"]}
    res["rows"] = rows
    res["groups"] = groups
    # (b) agreement. Committed demo runs always; eval runs when a live run exists.
    demo = agreement(trace_rows("runs/demo/offline/trace.jsonl"), trace_rows("runs/demo/live/trace.jsonl"),
                     groups["samples"], "committed demo runs (runs/demo/offline vs runs/demo/live), 20 samples")
    res["agreement"] = [demo]
    if mode == "live":
        off = evaluate("offline", live_ref={})
        res["offline_reference"] = {"commit": off["commit"]}
        res["adversarial_separate_run"] = off["adversarial_separate_run"] | {"note": "rules only, run offline"}
        for g in ("samples", "adversarial", "extra", "unseen"):
            res["agreement"].append(agreement(off["rows"], rows, groups[g], f"this eval run, {g} ({len(groups[g])})"))
        print("  Grok-only extraction of all ground-truth files ...")
        grok, usage = grok_extract_all(gt)
        res["extraction"]["grok_only"] = grok
        res["cost_latency"]["grok_only_extraction"] = extraction_cost(usage, pricing)
    else:
        live = live_ref if live_ref is not None else latest_live(RESULTS)
        if live:
            for g in ("samples", "adversarial", "extra", "unseen"):
                if not set(groups[g]) & set(live["rows"]):
                    continue   # a live snapshot from before this group existed
                res["agreement"].append(agreement(rows, live["rows"], groups[g],
                                                  f"eval live run ({live['generated_at']}) vs this offline run, {g} ({len(groups[g])})"))
    return res


def _saved(name: str, pick):
    """A committed one-off result in evals/results (separate_run_live.json, cache_repeatability.json), or None."""
    p = RESULTS / name
    return pick(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def web_summary(off: dict, live: dict | None) -> dict:
    """Compact eval summary for the web replay (web/data/evals.json). Written only with --web."""
    def ext(e):
        return {f: e["per_field"][f] for f in FIELDS} | {"overall": e["overall"]}
    offc = {c["file"]: c for c in off["adversarial"]["cases"]}
    livc = {c["file"]: c for c in live["adversarial"]["cases"]} if live else {}
    return {
        "source": "evals/results (python -m evals)",
        "offline_generated_at": off["generated_at"], "live_generated_at": live and live["generated_at"],
        "model": live and live["model"],
        "extraction": {"offline": ext(off["extraction"]["pipeline"]),
                       "live_pipeline": live and ext(live["extraction"]["pipeline"]),
                       "live_grok_only": live and ext(live["extraction"]["grok_only"]),
                       "ambiguous": {k: list(v["ambiguous"]) for k, v in load_yaml("ground_truth.yaml").items() if v.get("ambiguous")}},
        "agreement": [{k: a[k] for k in ("label", "invoices", "agree", "rate")}
                      | {"disagreement_routing": a.get("disagreement_routing")}
                      | {"disagreements": [{"file": d["file"], "offline": d["offline"], "live": d["live"],
                                            "live_reason": (d["live_reasons"] or [""])[0]} for d in a["disagreements"]]}
                      for a in agreements(off, live)],
        "separate_run": off.get("adversarial_separate_run") and {
            k: off["adversarial_separate_run"][k] for k in ("caught", "total", "catch_rate", "missed", "duplicate_3006")},
        "separate_run_live": _saved("separate_run_live.json", lambda r: {
            k: r[k] for k in ("caught", "total", "missed", "generated_at", "model", "commit", "wall_s", "billed_usd")}
            | {"calls": r["usage"]["calls"], "cases": [{k: c[k] for k in ("file", "decision", "decided_by", "caught")}
                                                       for c in r["cases"]]}),
        "cache_repeatability": _saved("cache_repeatability.json", lambda r: r),
        "unseen": {"offline": off.get("unseen"), "live": live and live.get("unseen")},
        "adversarial": {"offline": {k: off["adversarial"][k] for k in ("caught", "total", "catch_rate")},
                        "live": live and {k: live["adversarial"][k] for k in ("caught", "total", "catch_rate")},
                        "cases": [{"file": f, "trap": c["trap"], "offline": c["decision"], "offline_caught": c["caught"],
                                   "live": livc.get(f, {}).get("decision"), "live_caught": livc.get(f, {}).get("caught")}
                                  for f, c in offc.items()]},
        "cost_latency": live and {"batches": live["cost_latency"]["batches"],
                                  "grok_only_extraction": live["cost_latency"].get("grok_only_extraction"),
                                  "pricing_source": live["cost_latency"]["pricing_source"]},
        "offline_latency": {g: {"latency_mean_ms": b.get("latency_mean_ms"), "wall_s": b["wall_s"]}
                            for g, b in off["cost_latency"]["batches"].items()},
    }


def separate_run_live(out: Path, write: bool = True) -> int:
    """Live version of (c2): writes separate_run_live.json and .md."""
    from invoice_agents.graph import llm_usage
    expected, pricing = load_yaml("adversarial_expected.yaml"), load_yaml("pricing.yaml")
    try:
        client = GrokClient()
    except LLMUnavailable as e:
        print(f"{e}; --separate-run-live needs the xAI API.")
        return 2
    t0 = time.monotonic()
    res = separate_run_eval(expected, Path(tempfile.mkdtemp(prefix="evals-sep-")), llm=client)
    u = llm_usage(client.usage_log)
    ticks = u.get("cost_in_usd_ticks")
    res |= {"mode": "live", "model": client.model, "commit": git_commit(),
            "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"), "wall_s": round(time.monotonic() - t0, 1),
            "usage": {k: u[k] for k in ("calls", "prompt_tokens", "cached_prompt_tokens", "completion_tokens", "reasoning_tokens")},
            "list_price_usd": round(price(u, pricing), 4),
            "billed_usd": round(ticks / 1e10, 4) if ticks is not None else None,
            "returned_models": sorted({r.get("model") for r in client.usage_log if r.get("model")})}
    lines = [f"# Separate later run, live ({res['model']}, {res['generated_at']}, commit {res['commit']})", "",
             f"The 20 samples run first, then the {res['total']} adversarial invoices as a new run on the same database.", "",
             f"Caught {res['caught']}/{res['total']}. Missed: {', '.join(res['missed']) or 'none'}. "
             f"Both runs: {u['calls']} Grok calls, {res['wall_s']} s, billed ${res['billed_usd']} "
             f"(list price ${res['list_price_usd']}). Models the API reported: {', '.join(res['returned_models'])}.", "",
             "| file | trap | decision | decided by | risk | caught |", "|---|---|---|---|---|---|"]
    lines += [f"| {c['file']} | {c['trap']} | {c['decision']} | {c['decided_by']} | {c['risk_score']} | {c['caught']} |"
              for c in res["cases"]]
    lines += ["", "3006: " + res["duplicate_3006"]["reason"], ""]
    md = "\n".join(lines)
    if write:
        out.mkdir(parents=True, exist_ok=True)
        (out / "separate_run_live.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        (out / "separate_run_live.md").write_text(md, encoding="utf-8")
    print(md)
    return 0 if not res["missed"] else 1


def latest_live(out: Path) -> dict | None:
    """The live results to compare against: this output dir's own live run if any, else the committed snapshot."""
    for d in (out, RESULTS):
        if (d / "live.json").exists():
            return json.loads((d / "live.json").read_text(encoding="utf-8"))
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals", description=__doc__.split("\n\n")[0])
    ap.add_argument("--live", action="store_true", help="also run live against the xAI API (needs XAI_API_KEY)")
    ap.add_argument("--out", type=Path, default=OUT, help=f"results directory (default {rel(OUT)}, git-ignored)")
    ap.add_argument("--write-snapshot", action="store_true",
                    help=f"write the committed snapshot instead: {rel(RESULTS)} and web/data/evals.json")
    ap.add_argument("--no-write", action="store_true", help="print the summary only, write no files")
    ap.add_argument("--report-only", action="store_true", help="re-render the .md files from the saved .json results")
    ap.add_argument("--separate-run-live", action="store_true",
                    help="only the separate-later-run eval, live: samples, then the adversarial set as a new run (needs XAI_API_KEY)")
    args = ap.parse_args(argv)
    out = RESULTS if args.write_snapshot else args.out
    if args.separate_run_live:
        return separate_run_live(out, write=not args.no_write)

    def finish(off: dict, live: dict | None) -> int:
        md = summary_md(off, live)
        if not args.no_write:
            (out / "summary.md").write_text(md, encoding="utf-8")
            if args.write_snapshot:
                (ROOT / "web" / "data" / "evals.json").write_text(json.dumps(web_summary(off, live), indent=1), encoding="utf-8")
        print(md)
        return 0

    if args.report_only:
        saved = {m: json.loads((out / f"{m}.json").read_text(encoding="utf-8")) for m in ("offline", "live") if (out / f"{m}.json").exists()}
        if "offline" not in saved:
            print(f"No saved results in {rel(out)}: run `python -m evals` first "
                  "(or add --write-snapshot to re-render the committed snapshot).", file=sys.stderr)
            return 2
        if not args.no_write:
            for m, r in saved.items():
                (out / f"{m}.md").write_text(detail_md(r), encoding="utf-8")
        return finish(saved["offline"], saved.get("live"))
    from dotenv import load_dotenv
    load_dotenv()
    if not args.no_write:
        out.mkdir(parents=True, exist_ok=True)
    if args.live:
        import os
        if not os.environ.get("XAI_API_KEY"):
            print("XAI_API_KEY is not set. Set it (see .env.example) or run `python -m evals` offline.")
            return 2
        print("Live eval: pipeline on samples, adversarial and extra invoices, then Grok-only extraction ...")
        traces = (out if not args.no_write else Path(tempfile.mkdtemp())) / "runs" / "live"
        res = evaluate("live", keep_traces=traces)
        if not args.no_write:
            (out / "live.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
            (out / "live.md").write_text(detail_md(res), encoding="utf-8")
        live = res
    off = evaluate("offline", live_ref=live if args.live else latest_live(out))
    if not args.no_write:
        (out / "offline.json").write_text(json.dumps(off, indent=1, default=str), encoding="utf-8")
        (out / "offline.md").write_text(detail_md(off), encoding="utf-8")
    return finish(off, live if args.live else latest_live(out))
