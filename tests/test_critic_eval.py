"""Critic eval (proposals injected at the critic stage): the harness, offline, and the committed live result."""
import json
from pathlib import Path

from evals import critic_eval
from invoice_agents.agents import approval

ROOT = Path(__file__).resolve().parents[1]


def test_injected_vp_proposes_without_a_model_and_revises_through_the_real_vp():
    prop = approval.VPOpinion(decision="approve", reasons=["x"])
    calls = []

    class Inner:
        engine = "rules"

        def revise(self, state, f, prior, objection):
            calls.append((prior, objection))
            return approval.VPOpinion(decision="hold", reasons=["revised"])

    vp = critic_eval.InjectedVP(prop, Inner())
    assert vp.propose(None, {}) is prop and vp.engine == "rules"
    obj = approval.CriticOpinion(verdict="object", reason="r")
    assert vp.revise(None, {}, prop, obj).decision == "hold" and calls == [(prop, obj)]


def test_offline_critic_eval_runs_the_real_loop_with_rules_stand_ins():
    res = critic_eval.run(live=False)
    rows = {r["case"]: r for r in res["rows"]}
    assert len(rows) == 6 and all(r["critic_ran"] and r["calls"] == 0 for r in rows.values())
    # the rules critic only checks rename, near-limit, >25% price and pushy wording: it catches F3 only
    assert rows["F3_phone_surcharge"]["objected"] and rows["F3_phone_surcharge"]["vp_revisions"] == ["reject"]
    m = res["metrics"]
    assert (m["objected_on_flawed"], m["flawed"], m["objected_on_sound"], m["sound"]) == (1, 4, 0, 2)
    assert res["label"] == "critic eval: proposals injected at the critic stage"


def test_committed_live_critic_eval_matches_its_trace():
    d = ROOT / "runs" / "demo" / "critic_eval_live"
    summ = json.loads((d / "summary.json").read_text())
    tr = [json.loads(line) for line in (d / "trace.jsonl").read_text().splitlines()]
    assert summ["mode"] == "live" and summ["model"].startswith("grok")
    for r in summ["rows"]:
        crit = [e["detail"] for e in tr if e["source"] == r["file"] and e["step"] == "critic_review"]
        assert len(crit) == r["critic_rounds"] and r["objected"] == any(c["verdict"] == "object" for c in crit)
    assert sum(e["step"] == "vp_revise" for e in tr) == summ["metrics"]["vp_revisions"]
    injected = [e for e in tr if e["step"] == "injected_proposal"]
    assert len(injected) == len(summ["rows"]) and all("not a model answer" in e["detail"]["note"] for e in injected)
