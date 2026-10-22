(function () {
  "use strict";
  var DATA = null, MODE = "offline", SET = "case", FILTER = "all", SELECTED = null;
  var PILL = { APPROVED: ["approve", "Approved"], REJECTED: ["reject", "Rejected"], PENDING_HUMAN: ["review", "Held for a human"] };
  var BY = { hard_rules: "hard rules", vp: "the VP agent", "vp+critic": "the VP after critic review", deadlock: "deadlock (VP and critic still disagree)", error: "error fallback" };
  var TRIG = { over_threshold: "over the approval limit", near_limit: "near the approval limit", high_risk: "high risk score" };
  var SEV = { block: "Blocking: this finding rules out payment", warn: "Warning: worth a look, does not block payment on its own", info: "Info: noted for the record" };
  var STG_TIP = { ingestion: "Read the file and extract the invoice", validation: "Check inventory, math, dates, prices, vendor, duplicates", risk: "Score fraud signals; Grok checks claims with read-only tools", vp: "VP agent proposes approve, hold or reject", critic: "Second agent that challenges VP approvals", outcome: "Pay, reject, or hold for a person" };
  var AGENT = { ingestion: "Ingest", validation: "Validate", risk: "Risk", approval: "Approval", payment: "Payment", hitl: "Human review" };
  var README = "https://github.com/adamtpang/galatiq.vercel.app#quickstart-offline-about-a-minute";
  var $ = function (id) { return document.getElementById(id); };
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function money(v) {
    if (v == null) return "-";
    var neg = v < 0; v = Math.abs(v);
    return (neg ? "-$" : "$") + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function pill(status) {
    var p = PILL[status] || ["", status || "-"];
    return '<span class="pill ' + p[0] + '">' + p[1] + "</span>";
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function key(mode, set) { return (set === "extra" ? "extra_" : "") + mode; }
  function run() { return DATA.runs[key(MODE, SET)]; }
  function other() { return DATA.runs[key(MODE === "offline" ? "live" : "offline", SET)]; }
  function invNumber(n) { return n ? String(n).replace(/\s+R(\d+)$/, ", Revision $1") : "No invoice number"; }
  function vendorHtml(v) { return v ? esc(v) : '<span class="missing">Missing vendor</span>'; }
  function flag(inv, code) { return inv.flags.find(function (f) { return f.code === code; }); }
  function base(p) { return String(p || "").split("/").pop(); }
  function hr() { return DATA.policy.high_risk_score; }
  function dupNote(inv) {
    var f = flag(inv, "DUPLICATE_INVOICE");
    if (f) return "Duplicate of " + base(f.evidence.first_seen) + ", not paid twice";
    f = flag(inv, "SUPERSEDED_BY_REVISION");
    if (f) return "Replaced by a later revision (" + base(f.evidence.superseded_by) + "), not paid";
    f = flag(inv, "REVISION_SUPERSEDES");
    if (f) return "Revision 1 of " + base(f.evidence.supersedes) + "; only this version can be paid";
    return "";
  }
  function dupTag(i) {
    return flag(i, "DUPLICATE_INVOICE") ? '<span class="tag dup">Duplicate</span>' : flag(i, "SUPERSEDED_BY_REVISION") ? '<span class="tag dup">Superseded</span>' : "";
  }
  function riskText(r) {
    var det = r.deterministic_score;
    if (det != null && r.score !== det) return "risk: rules " + det + ", Grok raised to " + r.score;
    return "risk " + r.score;
  }
  function isFraudBlocked(inv) { return inv.decision.status === "REJECTED" && (inv.risk.score || 0) >= hr(); }
  function list(a) { return a && a.length ? "<ul class='reasons'>" + a.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>" : ""; }
  function cond(a, label) { return a && a.length ? "<div class='conds'><b>" + (label || "Conditions") + "</b>" + list(a) + "</div>" : ""; }
  function fmtClock(ms) {
    var s = Math.max(0, Math.round(ms / 1000)), m = Math.floor(s / 60);
    return m + ":" + String(s % 60).padStart(2, "0");
  }
  function fmtDur(ms) {
    var s = Math.round(ms / 1000);
    if (s < 1) return ms + " ms";
    if (s < 60) return s + " s";
    return Math.floor(s / 60) + " min " + (s % 60) + " s";
  }
  function fmtWhen(iso) {
    var d = new Date(iso);
    var date = d.toLocaleDateString("en-US", { timeZone: "America/Chicago", month: "long", day: "numeric", year: "numeric" });
    var time = d.toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    return { date: date, time: time, full: date + " at " + time };
  }
  function isLive(r) { return r.mode !== "offline"; }
  function runLabel(r) { return isLive(r) ? "live " + (r.model || "Grok") + " run" : "offline rules run"; }
  function grokReasons(inv) { return (inv.risk.llm && inv.risk.llm.extra_reasons) || []; }
  function ruleReasons(inv) {
    var g = grokReasons(inv);
    return (inv.risk.reasons || []).filter(function (r) { return !/^\(Grok\) /.test(r) || g.indexOf(r.replace(/^\(Grok\) /, "")) < 0; });
  }

  /* ---------- tool result summaries (faithful re-wording of the JSON) ---------- */
  function toolArgs(d) {
    return typeof d.args === "object" && d.args ? Object.keys(d.args).map(function (k) { return k + "=" + JSON.stringify(d.args[k]); }).join(", ") : esc(d.args);
  }
  function toolSummary(d) {
    var r = d.result || {};
    if (d.tool === "lookup_vendor") {
      if (!r.found) return "Not in the vendor master.";
      return "On file. Approved: " + (r.approved ? "yes" : "no") + ". Bank on file: " + (r.bank_on_file ? "yes" : "no") + ". Address: " + (r.address ? r.address : "none on file") + "." + (r.aliases && r.aliases.length ? " Aliases: " + r.aliases.join(", ") + "." : " No recorded aliases.");
    }
    if (d.tool === "query_inventory") {
      if (!r.found) return "Item not in inventory.";
      return "In inventory. Stock " + r.stock + ", catalog price " + money(r.catalog_unit_price_usd) + ".";
    }
    if (d.tool === "vendor_history") {
      var n = (r.invoices || []).length;
      return n ? plural(n, "earlier invoice") + " on record." : "No earlier invoices on record.";
    }
    return "";
  }

  /* ---------- narration of one trace event: what the agent is doing and why ---------- */
  function narrate(ev, inv, r) {
    var d = ev.detail || {}, o = { agent: ev.agent, title: "", what: "", body: "", cls: "" };
    switch (ev.agent + "." + ev.step) {
      case "ingestion.read":
        o.title = "Opened " + esc(inv.file);
        o.what = "Reading the " + esc(String(d.format || "").toUpperCase()) + " file, " + esc(d.chars) + " characters.";
        break;
      case "ingestion.deterministic_parse":
        o.title = d.ok ? "Parsed with the " + esc(inv.format || "") + " parser" : "The format parser could not read this file";
        o.what = d.ok ? "The structure was readable, so no model call was needed to extract it." : "Handing the raw text to Grok to extract, with schema checks." + (d.error ? '<br><span class="mono small">' + esc(d.error) + "</span>" : "");
        o.cls = d.ok ? "" : "warn";
        break;
      case "ingestion.llm_repair":
        if (d.attempts) {
          o.title = "Grok extracted the invoice (" + esc(d.model) + ", " + plural(d.attempts.length, "attempt") + ")";
          o.what = "The answer is validated against the invoice schema before it is used.";
          o.body = d.attempts.map(function (a) { return "Attempt " + esc(a.attempt) + (a.latency_s != null ? " (" + esc(a.latency_s) + " s)" : "") + ": " + (a.ok ? "valid against the schema" : "failed validation, error sent back: " + esc(String(a.error).slice(0, 220))); }).join("<br>") +
            (d.prompt_tokens ? '<br><span class="muted small">' + esc(d.prompt_tokens) + " prompt tokens, " + esc(d.completion_tokens) + " completion tokens</span>" : "");
          o.cls = "good";
        } else { o.title = "Grok extraction failed"; o.body = esc(d.error); o.cls = "bad"; }
        break;
      case "ingestion.extracted":
        o.title = "Extracted " + esc(invNumber(inv.number)) + " from " + vendorHtml(inv.vendor);
        o.what = plural(inv.items.length, "line item") + ", total " + money(inv.total_usd) + (inv.currency && inv.currency !== "USD" ? " (" + esc(inv.currency) + " " + esc(inv.total) + ")" : "") + ". Names are shown as written on the invoice, typos included.";
        o.body = inv.items.map(function (li) {
          return esc(li.qty) + " x " + esc(li.sku || li.sku_raw + " (unknown item)") + " @ " + money(li.unit_price) + (li.note ? " (" + esc(li.note) + ")" : "");
        }).join("<br>");
        break;
      case "validation.validate":
        var nb = d.blocking.length;
        o.title = d.flags.length ? "Validation: " + plural(d.flags.length, "flag") + ", " + nb + " blocking" : "Validation: clean, no flags";
        o.what = "Checked every line against inventory, recomputed the math, and checked dates, currency, prices, vendor and duplicates." + (nb ? " A blocking flag means this invoice cannot be paid, whatever any model says." : "");
        o.body = inv.flags.length ? '<ul class="fl">' + inv.flags.map(function (f) { return '<li><span class="sev ' + esc(f.severity) + '" title="' + esc(SEV[f.severity] || "") + '">' + esc(f.severity) + "</span><span>" + esc(f.message) + "</span></li>"; }).join("") + "</ul>" : "";
        o.cls = nb ? "bad" : "good";
        break;
      case "risk.tool_call":
        o.title = "Risk agent called <span class='mono'>" + esc(d.tool) + "(" + esc(toolArgs(d)) + ")</span>";
        o.what = toolSummary(d);
        o.body = '<details><summary>raw result</summary><pre>' + esc(JSON.stringify(d.result, null, 1)) + "</pre></details>";
        o.cls = "tool";
        break;
      case "risk.assess":
        var llm = d.llm;
        o.title = "Risk score " + esc(d.score) + " / 100" + (llm && llm.score != null && d.score !== d.deterministic_score ? " (rules gave " + esc(d.deterministic_score) + ", Grok raised it)" : "");
        var sig = inv.risk.signals || [];
        o.what = (sig.length ? "Rule signals: " + sig.map(function (s) { return esc(s.signal.replace(/_/g, " ")) + " +" + esc(s.weight); }).join(", ") + "." : "No rule signals fired.") +
          (llm && !llm.error ? " Grok reviewed it with " + plural(llm.tool_calls || 0, "tool call") + (llm.attempts && llm.attempts.length ? ", final answer in " + esc(llm.attempts[llm.attempts.length - 1].latency_s) + " s" : "") + "." :
            llm && llm.error ? " Grok risk review errored: " + esc(llm.error) + "." :
            isLive(r) ? " No Grok risk review: it only runs on invoices with no blocking flag." : " Offline run: no model call.");
        var g = grokReasons(inv), rr = ruleReasons(inv);
        o.body = (rr.length ? "<div class='sub-h'>Rule findings</div>" + list(rr) : "") + (g.length ? "<div class='sub-h grok'>Grok's reasoning</div>" + list(g) : "");
        o.cls = d.score >= hr() ? "warn" : "";
        break;
      case "approval.vp_propose":
        o.title = "VP agent proposes: " + esc(d.decision);
        o.what = isLive(r) ? "Grok, acting as the VP, weighs the flags and risk review and argues for a decision." : "The rules version of the VP weighs the flags and risk score.";
        o.body = list(d.reasons) + cond(d.conditions);
        o.cls = "vp";
        break;
      case "approval.critic_review":
        o.title = "Critic, round " + esc(d.round) + ": " + (d.verdict === "object" ? "objects" : "signs off");
        o.what = "The critic looks for a reason the VP approval is wrong.";
        o.body = esc(d.reason);
        o.cls = "crit " + (d.verdict === "object" ? "bad" : "good");
        break;
      case "approval.vp_revise":
        o.title = "VP revises, round " + esc(d.round) + ": " + esc(d.decision);
        o.body = list(d.reasons) + cond(d.conditions);
        o.cls = "vp";
        break;
      case "approval.decide":
        o.title = "Decision: " + (PILL[d.status] || [0, d.status])[1] + " by " + esc(BY[d.decided_by] || d.decided_by) + (d.critique_rounds ? ", after " + plural(d.critique_rounds, "critic round") : "");
        var trig = (inv.decision.arguments && inv.decision.arguments.critic_triggers) || [];
        if (d.decided_by === "hard_rules") o.what = "Blocking flags decide this on their own. No VP or critic needed.";
        else if (trig.length && !d.critique_rounds) o.what = "Critic triggers: " + trig.map(function (t) { return TRIG[t] || t; }).join(", ") + ". The critic only reviews approvals, so with the VP holding or rejecting it did not run.";
        else if (!trig.length && d.decided_by === "vp") o.what = "No critic trigger (not large, not near the limit, not high risk), so the VP decision stands.";
        o.body = list(d.reasons) + cond(d.conditions);
        o.cls = d.status === "APPROVED" ? "good" : d.status === "REJECTED" ? "bad" : "warn";
        break;
      case "payment.paid":
        o.title = "Paid " + money(d.amount) + " on attempt " + esc(d.attempts);
        o.what = "Called the mock bank once, guarded by an idempotency key so it can never pay twice.";
        o.body = "Bank reply: " + esc(d.bank_message) + '<br><span class="small muted">Idempotency key <span class="mono">' + esc(d.idempotency_key) + "</span></span>";
        o.cls = "good"; break;
      case "payment.bank_error": o.title = "Bank error, attempt " + esc(d.attempt); o.body = esc(d.error); o.cls = "bad"; break;
      case "payment.failed": o.title = "Payment failed"; o.body = esc((d.errors || []).join("; ")); o.cls = "bad"; break;
      case "payment.idempotency_skip": o.title = "Already paid, skipped"; break;
      case "payment.rejection_logged": o.title = "Not paid. Rejection logged to the audit trail"; o.cls = "bad"; break;
      case "hitl.queued":
        o.title = "Queued for human review";
        o.what = "No money moves until a person approves or rejects it in the review queue.";
        o.body = '<span class="mono small">python main.py review ' + esc(inv.number) + ' --approve --note "..."</span>';
        o.cls = "warn"; break;
      default: o.title = esc(ev.agent + " " + ev.step);
    }
    return o;
  }
  function stepHtml(ev, inv, r, extra) {
    var o = narrate(ev, inv, r);
    return '<li class="step ' + o.cls + (extra || "") + '"><div class="step-head"><span class="agent">' + esc(AGENT[o.agent] || o.agent) + '</span><span class="ms small muted" title="' + esc(Number(ev.ms).toLocaleString("en-US")) + ' ms after this invoice started (recorded)">' + fmtClock(ev.ms) + '</span><span class="step-title">' + o.title + "</span></div>" +
      (o.what ? '<div class="step-what">' + o.what + "</div>" : "") + (o.body ? '<div class="step-body">' + o.body + "</div>" : "") + "</li>";
  }

  /* ---------- per-invoice detail (explorer and inspector) ---------- */
  function riskMeter(score) {
    var s = Math.max(0, Math.min(100, score || 0));
    return '<div class="meter"><div class="meter-row"><span>Risk</span><span class="mono">' + s + " / 100</span></div>" +
      '<div class="meter-bar"><span style="left:' + s + '%"></span></div></div>';
  }
  function detailHtml(inv, r) {
    var d = inv.decision;
    var flags = inv.flags.length ? '<table class="flags-t"><thead><tr><th>Severity</th><th>Code</th><th>Finding</th></tr></thead><tbody>' +
      inv.flags.map(function (f) {
        return '<tr><td><span class="sev ' + esc(f.severity) + '">' + esc(f.severity) + "</span></td><td class='mono small'>" + esc(f.code) +
          "</td><td>" + esc(f.message) + "<details><summary>evidence</summary><pre>" + esc(JSON.stringify(f.evidence, null, 1)) + "</pre></details></td></tr>";
      }).join("") + "</tbody></table>" : '<p class="muted small">No flags.</p>';
    return '<div class="inv-head"><div><div class="small muted">' + esc(inv.file) + '</div><div class="inv-id">' + esc(invNumber(inv.number)) + " · " + vendorHtml(inv.vendor) + "</div>" +
      (inv.vendor ? '<div class="as-written">Names and labels are shown as written on the invoice, typos included.</div>' : "") + "</div>" + pill(d.status) + "</div>" +
      (dupNote(inv) ? '<div class="note">' + esc(dupNote(inv)) + ".</div>" : "") +
      '<div class="amount">' + money(inv.total_usd) + (inv.currency && inv.currency !== "USD" ? ' <span class="small muted">(' + esc(inv.currency) + " " + esc(inv.total) + ")</span>" : "") + "</div>" +
      riskMeter(inv.risk.score) +
      '<div class="decision"><b>Why</b>' + list(d.reasons) + cond(d.conditions) + "</div>" +
      "<h3 class='dh'>Agent timeline</h3><ol class='timeline'>" + inv.timeline.map(function (ev) { return stepHtml(ev, inv, r); }).join("") + "</ol>" +
      "<h3 class='dh'>Flags</h3>" + flags;
  }

  /* ---------- explorer ---------- */
  function renderSummary() {
    var invs = run().invoices, paid = 0, nPaid = 0, rej = 0, held = 0, fraud = 0, fraudN = 0;
    invs.forEach(function (i) {
      if (i.payment && i.payment.status === "paid") { paid += i.payment.amount; nPaid++; }
      if (i.decision.status === "REJECTED") rej++;
      if (i.decision.status === "PENDING_HUMAN") held++;
      if (isFraudBlocked(i)) { fraud += i.total_usd || 0; fraudN++; }
    });
    $("summary").innerHTML =
      card(money(paid), plural(nPaid, "invoice") + " paid") +
      card(String(rej), "rejected, with reasons logged") +
      card(String(held), "sent to a human") +
      card(money(fraud), plural(fraudN, "high-risk invoice") + " blocked", "Rejected invoices with risk score " + hr() + " or more");
    var r = run();
    $("showing").innerHTML = "Showing the <b>" + esc(runName(MODE)) + "</b> run" + (SET === "extra" ? " on the 3 extra test invoices" : " on the 20 case invoices") + ", recorded " + esc(fmtWhen(r.recorded_at).full) + ". The handoff report uses the same run.";
    $("run-meta").textContent = r.mode === "offline" ? "Deterministic VP and critic rules, no API calls" : "Risk review (with tool calls), VP and critic by " + (r.model || "Grok");
    var o = other(), diff = [];
    if (o) r.invoices.forEach(function (i) {
      var j = o.invoices.find(function (x) { return x.file === i.file; });
      if (j && j.decision.status !== i.decision.status) diff.push(invNumber(i.number));
    });
    var why = MODE === "offline"
      ? "Offline, the VP and critic are fixed rules written from the same prompts. No API calls, so every run gives the same result."
      : "Live, Grok does the risk review, the VP and the critic. It tends to be more cautious than the rules. The critic only reviews approvals, so when the VP holds an invoice the critic never runs.";
    $("run-note").textContent = why + (diff.length ? " Different outcome from the " + (MODE === "offline" ? "live" : "offline") + " run: " + diff.join(", ") + "." : (o ? " Same outcomes as the " + (MODE === "offline" ? "live" : "offline") + " run." : ""));
  }
  function card(big, cap, title) {
    return '<div class="sum"' + (title ? ' title="' + esc(title) + '"' : "") + '><div class="sum-big">' + esc(big) + '</div><div class="cap">' + esc(cap) + "</div></div>";
  }
  function renderInbox() {
    var html = run().invoices.filter(function (i) { return FILTER === "all" || i.decision.status === FILTER; }).map(function (i) {
      var blocks = i.flags.filter(function (f) { return f.severity === "block"; }).length, dn = dupNote(i);
      return '<li><button type="button" class="inv' + (i.file === SELECTED ? " on" : "") + '" data-file="' + esc(i.file) + '">' +
        '<span class="inv-main"><b>' + esc(invNumber(i.number)) + dupTag(i) + '</b><span class="small' + (i.vendor ? " muted" : "") + '">' + vendorHtml(i.vendor) + '</span></span>' +
        '<span class="inv-side"><span class="money">' + money(i.total_usd) + "</span>" + pill(i.decision.status) + "</span>" +
        '<span class="inv-meta small muted">' + esc(i.file) + " · " + esc(riskText(i.risk)) + (blocks ? " · " + blocks + " blocking" : "") +
        (dn ? '<span class="why">' + esc(dn) + "</span>" : "") + "</span>" +
        "</button></li>";
    }).join("");
    $("inbox").innerHTML = html || '<li class="muted small pad">No invoices with this status in this run.</li>';
  }
  function renderDetail() {
    var inv = run().invoices.find(function (i) { return i.file === SELECTED; }) || run().invoices[0];
    SELECTED = inv.file;
    $("detail").innerHTML = detailHtml(inv, run());
  }
  function setRun(mode, set) {
    set = set || SET;
    if (!DATA.runs[key(mode, set)]) return;
    MODE = mode; SET = set;
    document.querySelectorAll("[data-run]").forEach(function (x) { x.classList.toggle("on", x.dataset.run === MODE); x.setAttribute("aria-pressed", x.dataset.run === MODE); x.disabled = !DATA.runs[key(x.dataset.run, SET)]; });
    document.querySelectorAll("[data-set]").forEach(function (x) { x.classList.toggle("on", x.dataset.set === SET); x.setAttribute("aria-pressed", x.dataset.set === SET); x.disabled = !DATA.runs[key(MODE, x.dataset.set)]; });
    if (!run().invoices.some(function (i) { return i.file === SELECTED; })) SELECTED = run().invoices[0].file;
  }
  function renderAll() { labelButtons(); renderSummary(); renderInbox(); renderDetail(); }

  /* ---------- stage 1: overview ---------- */
  function renderOverview() {
    var live = DATA.runs.live, w = fmtWhen(live.recorded_at), p = DATA.policy;
    $("honesty").innerHTML = "<b>This is a replay, not a live call.</b> It plays back a real run recorded on " + esc(w.full) + " with " + esc(live.model) +
      ". Every step, tool result, score and argument comes from the committed trace (<span class='mono'>runs/demo/live</span>); nothing is generated in your browser. The system itself runs locally as a Python CLI: <a href='" + README + "'>quickstart in the README</a>.";
    $("sit-limit").textContent = money(p.approval_threshold_usd).replace(".00", "") + " approval limit";
    $("sit-limit-p").textContent = "Invoices over " + money(p.approval_threshold_usd).replace(".00", "") + ", at or above " + money(p.near_limit_usd).replace(".00", "") + ", or with a risk score of " + p.high_risk_score + " or more get a second opinion before anyone pays them.";
    $("pipe-critic").textContent = "If the VP approves an invoice that is over " + money(p.approval_threshold_usd).replace(".00", "") + ", at or above " + money(p.near_limit_usd).replace(".00", "") + " or risk " + p.high_risk_score + "+, a critic objects or signs off, for up to " + p.critic_max_rounds + " rounds. Still split after that? A human decides.";
    var invs = live.invoices, fm = {};
    invs.forEach(function (i) { var f = (i.format || "?").toUpperCase(); fm[f] = (fm[f] || 0) + 1; });
    var keys = Object.keys(fm).sort(function (a, b) { return fm[b] - fm[a]; });
    $("inbox-sum").textContent = invs.length + " invoice files waiting, none processed yet. Some are the same invoice sent twice in different formats; one is a revision.";
    $("fmt-row").innerHTML = keys.map(function (k) { return '<span class="fmt-chip"><b>' + fm[k] + "</b> " + esc(k) + "</span>"; }).join("");
    $("tiles").innerHTML = invs.map(function (i) {
      return '<li><span class="t-fmt">' + esc((i.format || "").toUpperCase()) + '</span><span class="mono t-name">' + esc(i.file) + "</span></li>";
    }).join("");
    var plan = schedule(live);
    $("go-note").textContent = "1x = about " + fmtDur(Math.round(plan.total / 1000) * 1000) + " (real run took " + fmtDur(live.duration_ms) + "). You can switch to 4x, pause or skip to the end.";
    $("go").disabled = false;
  }

  /* ---------- stage 2: playback ---------- */
  var SCALE = 25, MIN_STEP = 130, INTRO = 280, OUTRO = 170;
  var P = null;
  function schedule(r) {
    var evs = [], at = 0, prevReal = 0;
    r.invoices.forEach(function (inv, k) {
      at += INTRO; evs.push({ type: "start", inv: inv, k: k, at: at, real: inv.start_ms });
      inv.timeline.forEach(function (ev, j) {
        var real = inv.start_ms + ev.ms, gap = Math.max(0, real - prevReal);
        var dwell = Math.max(MIN_STEP, gap / SCALE);
        at += dwell; prevReal = real;
        evs.push({ type: "ev", inv: inv, k: k, ev: ev, at: at, real: real, gap: gap, dwell: dwell });
      });
      at += OUTRO; evs.push({ type: "end", inv: inv, k: k, at: at, real: inv.start_ms + inv.duration_ms });
    });
    return { evs: evs, total: at };
  }
  var STAGES = [["ingestion", "Ingest"], ["validation", "Validate"], ["risk", "Risk"], ["vp", "VP"], ["critic", "Critic"], ["outcome", "Outcome"]];
  function stageOf(ev) {
    if (ev.agent === "approval") return ev.step === "critic_review" ? "critic" : ev.step === "decide" ? "outcome" : "vp";
    if (ev.agent === "payment" || ev.agent === "hitl") return "outcome";
    return ev.agent;
  }

  function startRun(name) {
    if (!DATA || !DATA.runs[name]) return;
    var r = DATA.runs[name];
    stopLoop();
    var plan = schedule(r);
    P = { r: r, evs: plan.evs, total: plan.total, T: 0, cur: 0, speed: P ? P.speed : 1, playing: true, done: 0, curInv: null, stage: {},
      tot: { paid: 0, nPaid: 0, rej: 0, held: 0, fraud: 0, nFraud: 0 }, status: {}, real: 0, finished: false, last: 0, raf: 0 };
    $("run").hidden = false; $("report").hidden = true; closeInspector();
    $("run-eyebrow").textContent = "Working · " + runLabel(r) + ", replayed";
    $("run-h").textContent = isLive(r) ? "Grok is working through the inbox" : "The offline rules are working through the inbox";
    $("prog").setAttribute("aria-valuemax", r.invoices.length);
    $("speed-note").textContent = "1x = about " + fmtDur(Math.round(plan.total / 1000) * 1000) + ", 4x = about " + fmtDur(Math.round(plan.total / 4000) * 1000) + " (real run took " + fmtDur(r.duration_ms) + ")";
    $("queue").innerHTML = r.invoices.map(function (inv, k) {
      return '<li><button type="button" class="q-item" data-q="' + k + '"><span class="q-num">' + (k + 1) + '</span><span class="q-main"><span class="small q-file">' + esc(inv.file) + '</span><span class="small muted">' + esc(invNumber(inv.number)) + '</span></span><span class="q-st" id="qs-' + k + '"><span class="q-wait">Waiting</span></span></button></li>';
    }).join("");
    $("feed").innerHTML = ""; $("cur-head").innerHTML = ""; renderStepper();
    $("skip").disabled = false; $("pause").disabled = false; setPauseLabel();
    updateBar();
    jump("run");
    P.last = performance.now();
    P.raf = requestAnimationFrame(tick);
  }
  function stopLoop() { if (P && P.raf) cancelAnimationFrame(P.raf); }
  function tick(now) {
    if (!P) return;
    var dt = Math.min(250, now - P.last); P.last = now;
    if (P.playing && !P.finished) {
      P.T += dt * P.speed;
      while (P.cur < P.evs.length && P.evs[P.cur].at <= P.T) fire(P.evs[P.cur++], true);
      updateBar();
      if (P.cur >= P.evs.length) finish(true);
    }
    if (!P.finished) P.raf = requestAnimationFrame(tick);
  }
  function fire(e, show) {
    var inv = e.inv, k = e.k;
    P.real = Math.max(P.real, e.real);
    if (e.type === "start") {
      P.curInv = k; P.stage = {};
      setQ(k, '<span class="q-now">Working</span>', "now");
      if (show) {
        $("cur-head").innerHTML = '<div class="small muted">Invoice ' + (k + 1) + " of " + P.r.invoices.length + " · " + esc(inv.file) + '</div><div class="cur-title">' + esc(invNumber(inv.number)) + dupTag(inv) + " · " + vendorHtml(inv.vendor) + "</div>" +
          '<div class="small muted">' + money(inv.total_usd) + (inv.currency && inv.currency !== "USD" ? " (" + esc(inv.currency) + " " + esc(inv.total) + ")" : "") + " · recorded in " + fmtDur(inv.duration_ms) + "</div>";
        $("feed").innerHTML = ""; renderStepper();
      }
      return;
    }
    if (e.type === "end") {
      P.done++; P.stage.complete = true;
      setQ(k, pill(inv.decision.status), "done");
      if (show) { renderStepper(); $("live-status").textContent = "Invoice " + (k + 1) + " of " + P.r.invoices.length + ", " + inv.file + ": " + (PILL[inv.decision.status] || [0, inv.decision.status])[1] + "."; }
      return;
    }
    var ev = e.ev, st = stageOf(ev);
    Object.keys(P.stage).forEach(function (s) { if (P.stage[s] === "on") P.stage[s] = "done"; });
    P.stage[st] = "on";
    if (ev.step === "decide") {
      if (!inv.timeline.some(function (x) { return x.step === "critic_review"; })) P.stage.critic = "skipped";
      if (ev.detail.decided_by === "hard_rules") { P.stage.vp = "skipped"; P.stage.critic = "skipped"; }
      var s = ev.detail.status;
      if (s === "REJECTED") { P.tot.rej++; if (isFraudBlocked(inv)) { P.tot.fraud += inv.total_usd || 0; P.tot.nFraud++; } }
      if (s === "PENDING_HUMAN") P.tot.held++;
    }
    if (ev.step === "paid") { P.tot.paid += ev.detail.amount || 0; P.tot.nPaid++; }
    if (show) {
      var feed = $("feed");
      feed.insertAdjacentHTML("beforeend", stepHtml(ev, inv, P.r));
      feed.scrollTop = feed.scrollHeight;
      renderStepper();
    }
  }
  function setQ(k, html, cls) {
    var el = $("qs-" + k); if (!el) return;
    el.innerHTML = html;
    var b = el.closest(".q-item");
    b.classList.remove("now", "done"); b.classList.add(cls);
    if (cls === "now" && !REDUCED) { var list = $("queue"); if (list.scrollHeight > list.clientHeight) list.scrollTop = b.parentNode.offsetTop - list.offsetTop - 60; }
  }
  function renderStepper() {
    var s = P ? P.stage : {};
    $("stepper").innerHTML = STAGES.map(function (x) {
      var v = s[x[0]] || (s.complete ? "skipped" : "");
      if (v === "on" && s.complete) v = "done";
      return '<li class="stg ' + v + '" title="' + esc(STG_TIP[x[0]]) + '"' + (v === "on" ? ' aria-current="step"' : "") + ">" + x[1] + (v === "skipped" ? '<span class="sr-only"> (skipped)</span>' : v === "done" ? '<span class="sr-only"> (done)</span>' : "") + "</li>";
    }).join("");
  }
  function updateBar() {
    var n = P.r.invoices.length, pct = P.total ? Math.min(100, P.T / P.total * 100) : 0;
    $("prog-fill").style.width = pct + "%";
    $("prog").setAttribute("aria-valuenow", P.done);
    $("prog-label").textContent = P.done + " of " + n + " invoices done";
    $("prog-eta").textContent = P.finished ? "Finished" : (P.playing ? "ETA " + fmtClock((P.total - P.T) / P.speed) + " at " + P.speed + "x" : "Paused · " + fmtClock((P.total - P.T) / P.speed) + " left at " + P.speed + "x");
    $("prog-real").textContent = "About " + fmtClock(P.real) + " into the real run, which took " + fmtDur(P.r.duration_ms) + ".";
    var t = P.tot;
    $("totals").innerHTML =
      tcard(money(t.paid), "paid · " + plural(t.nPaid, "invoice"), "good") +
      tcard(String(t.rej), "rejected", "bad") +
      tcard(String(t.held), "held for a human", "warn") +
      tcard(money(t.fraud), "high-risk blocked · " + t.nFraud, "", "Rejected invoices with risk score " + hr() + " or more");
    updateWaiting();
  }
  function tcard(big, cap, cls, title) {
    return '<div class="tot ' + cls + '"' + (title ? ' title="' + esc(title) + '"' : "") + '><div class="tot-big">' + esc(big) + '</div><div class="small muted">' + esc(cap) + "</div></div>";
  }
  function updateWaiting() {
    var w = $("waiting"), nx = P.evs[P.cur];
    if (!P.finished && nx && nx.type === "ev" && isLive(P.r) && nx.gap > 1000 && (nx.ev.agent === "risk" || nx.ev.agent === "approval" || nx.ev.step === "llm_repair")) {
      var who = nx.ev.agent === "approval" ? "VP agent" : nx.ev.agent === "risk" ? "Risk agent" : "Ingest agent";
      var frac = Math.max(0, Math.min(1, 1 - (nx.at - P.T) / nx.dwell));
      var txt = who + " waiting on " + esc(P.r.model) + " · recorded wait " + (nx.gap / 1000).toFixed(1) + " s";
      if (w.dataset.t !== txt) { w.innerHTML = '<span class="spin" aria-hidden="true"></span><span>' + txt + '</span><span class="w-bar"><span id="w-fill"></span></span>'; w.dataset.t = txt; }
      $("w-fill").style.width = (frac * 100) + "%";
      w.hidden = false;
    } else { w.hidden = true; w.dataset.t = ""; }
  }
  function setPauseLabel() {
    var b = $("pause");
    b.textContent = P && !P.playing ? "Resume" : "Pause";
    b.setAttribute("aria-pressed", P && !P.playing ? "true" : "false");
  }
  function skipToEnd() {
    if (!P || P.finished) return;
    var lastStart = -1;
    for (var i = P.evs.length - 1; i >= 0; i--) if (P.evs[i].type === "start") { lastStart = i; break; }
    while (P.cur < P.evs.length) { var e = P.evs[P.cur]; fire(e, P.cur >= lastStart); P.cur++; }
    P.T = P.total;
    finish(true);
  }
  function finish(scroll) {
    if (P.finished) return;
    P.finished = true; P.playing = false;
    updateBar();
    $("pause").disabled = true; $("skip").disabled = true; setPauseLabel();
    $("run-eyebrow").textContent = "Finished · " + runLabel(P.r) + ", replayed";
    $("run-h").textContent = "All " + P.r.invoices.length + " invoices handled";
    $("live-status").textContent = "Run complete. The handoff report is below.";
    REPORT = P.r.name.replace(/^extra_/, "");
    renderReport(); setRun(REPORT, "case"); renderAll();
    $("report").hidden = false;
    if (scroll) setTimeout(function () { jump("report"); }, REDUCED ? 0 : 500);
  }
  function jump(id) {
    var el = $(id); if (!el) return;
    el.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
  }
  function inspect(k) {
    if (!P) return;
    if (P.playing && !P.finished) { P.playing = false; setPauseLabel(); updateBar(); }
    var inv = P.r.invoices[k], reached = k < P.curInv || (k === P.curInv && P.stage.complete) || P.finished;
    $("insp-note").textContent = (reached ? "Paused. Full recorded trace for this invoice." : "Paused. The replay has not reached this invoice yet; this is its full recorded trace.") ;
    $("insp-body").innerHTML = detailHtml(inv, P.r);
    document.querySelectorAll(".q-item.picked").forEach(function (x) { x.classList.remove("picked"); });
    var qb = document.querySelector('[data-q="' + k + '"]'); if (qb) qb.classList.add("picked");
    var box = $("inspector"), cardEl = box.closest(".feed-card");
    box.hidden = false; cardEl.classList.add("inspecting"); document.body.classList.add("sheet-open");
    box.scrollTop = 0; $("insp-body").scrollTop = 0;
    box.focus({ preventScroll: true });
    // Desktop: keep queue and detail side by side; only scroll the page if the panel top is out of view.
    if (window.innerWidth > 900) {
      var top = cardEl.getBoundingClientRect().top, navH = document.querySelector(".nav").offsetHeight;
      if (top < navH + 8 || top > window.innerHeight * 0.4) window.scrollTo({ top: window.scrollY + top - navH - 12, behavior: REDUCED ? "auto" : "smooth" });
    } else if (qb) {
      // Phone: the detail opens as a bottom sheet; keep the tapped queue row visible in the strip above it.
      var nh = document.querySelector(".nav").offsetHeight, sheetTop = box.getBoundingClientRect().top, qr = qb.getBoundingClientRect();
      var want = nh + Math.max(4, (sheetTop - nh - qr.height) / 2);
      if (qr.top < nh || qr.bottom > sheetTop) window.scrollTo({ top: window.scrollY + qr.top - want, behavior: "auto" });
    }
  }
  function closeInspector() {
    var box = $("inspector"); box.hidden = true;
    var c = box.closest(".feed-card"); if (c) c.classList.remove("inspecting");
    document.body.classList.remove("sheet-open");
    document.querySelectorAll(".q-item.picked").forEach(function (x) { x.classList.remove("picked"); });
  }

  /* ---------- stage 3: report ---------- */
  var REPORT = "live";
  var CAT = [
    ["dup", "duplicate copies of invoices already received", function (i) { return !!flag(i, "DUPLICATE_INVOICE"); }],
    ["sup", "replaced by a later revision", function (i) { return !!flag(i, "SUPERSEDED_BY_REVISION"); }],
    ["risk", "high risk (score {HR}+) that also failed hard rules", function (i) { return (i.risk.score || 0) >= hr() && hasBlock(i); }],
    ["stock", "not enough stock", function (i) { return blocks(i).some(function (c) { return c === "STOCK_EXCEEDED" || c === "ZERO_STOCK"; }); }],
    ["item", "items not in inventory", function (i) { return blocks(i).indexOf("UNKNOWN_ITEM") >= 0; }],
    ["data", "missing or invalid invoice data", function (i) { return blocks(i).some(function (c) { return /^MISSING_|^NEGATIVE_|^INVALID_|UNREADABLE|PARSE/.test(c); }); }],
    ["math", "math that does not add up", function (i) { return blocks(i).some(function (c) { return /MISMATCH/.test(c); }); }],
    ["vp", "rejected by the VP agent", function (i) { return !hasBlock(i); }],
    ["other", "other blocking flags", function () { return true; }]
  ];
  function blocks(i) { return i.flags.filter(function (f) { return f.severity === "block"; }).map(function (f) { return f.code; }); }
  function hasBlock(i) { return blocks(i).length > 0; }
  function catOf(i) { for (var c = 0; c < CAT.length; c++) if (CAT[c][2](i)) return CAT[c]; }
  function catLabel(c) { return c[1].replace("{HR}", hr()); }
  function owners(inv) {
    var t = (inv.decision.conditions || []).concat(inv.decision.reasons || []).join(" "), o = [];
    if (/procurement/i.test(t)) o.push("Procurement");
    if (/\bAP\b/.test(t)) o.push("AP");
    return o;
  }
  function invLine(i, extra) {
    return '<li><span class="r-inv"><b>' + esc(invNumber(i.number)) + "</b>" + dupTag(i) + ' <span class="muted">· ' + vendorHtml(i.vendor) + " · " + money(i.total_usd) + ' · <button type="button" class="linkish mono small" data-open-file="' + esc(i.file) + '">' + esc(i.file) + "</button></span></span>" + (extra || "") + "</li>";
  }
  function statusRank(s) { return { APPROVED: 0, PENDING_HUMAN: 1, REJECTED: 2 }[s]; }

  function syncRepButtons() {
    document.querySelectorAll("[data-rep]").forEach(function (b) { b.classList.toggle("on", b.dataset.rep === REPORT); b.setAttribute("aria-pressed", b.dataset.rep === REPORT); });
  }
  function runName(mode) { var r = DATA.runs[mode]; return mode === "live" ? "Live " + (r.model || "Grok") : "Offline rules"; }
  function labelButtons() {
    document.querySelectorAll("[data-rep]").forEach(function (b) { var r = DATA.runs[b.dataset.rep]; if (r) b.innerHTML = esc(runName(b.dataset.rep)) + '<span class="seg-sub">' + esc(fmtWhen(r.recorded_at).time) + "</span>"; });
    document.querySelectorAll("[data-run]").forEach(function (b) { var r = DATA.runs[key(b.dataset.run, SET)]; if (r) b.innerHTML = esc(runName(b.dataset.run)) + '<span class="seg-sub">' + esc(fmtWhen(r.recorded_at).time) + "</span>"; });
  }
  function renderReport() {
    var r = DATA.runs[REPORT], o = DATA.runs[REPORT === "live" ? "offline" : "live"], invs = r.invoices, n = invs.length, w = fmtWhen(r.recorded_at);
    syncRepButtons();
    var by = function (s) { return invs.filter(function (i) { return i.decision.status === s; }); };
    var paid = invs.filter(function (i) { return i.payment && i.payment.status === "paid"; }), rej = by("REJECTED"), held = by("PENDING_HUMAN"), appr = by("APPROVED");
    var paidSum = paid.reduce(function (a, i) { return a + i.payment.amount; }, 0);
    var hard = invs.filter(function (i) { return i.decision.decided_by === "hard_rules"; }).length;
    var reviewed = invs.filter(function (i) { return i.risk.llm && !i.risk.llm.error; });
    var tools = 0; invs.forEach(function (i) { i.timeline.forEach(function (e) { if (e.step === "tool_call") tools++; }); });
    var fm = {}; invs.forEach(function (i) { var f = (i.format || "?").toUpperCase(); fm[f] = (fm[f] || 0) + 1; });
    var fmTxt = Object.keys(fm).sort(function (a, b) { return fm[b] - fm[a]; }).map(function (k) { return fm[k] + " " + k; }).join(", ");
    var h = [];

    h.push('<header class="memo-h"><div><div class="small muted">From</div><b>' + (isLive(r) ? "Grok (" + esc(r.model) + "), AP agent pipeline" : "Offline rules pipeline") + '</b></div><div><div class="small muted">To</div><b>Acme accounts payable</b></div><div><div class="small muted">Run recorded</div><b>' + esc(w.full) + "</b></div></header>");
    h.push('<p class="memo-note small">Assembled by this page from the trace of the ' + runLabel(r) + ". The numbers, quotes and reasons are from the run; only the connecting sentences are a template. A replay, not a live call.</p>");

    // 1. what it processed
    h.push('<section class="m-sec"><h3>1. What I processed</h3><p>I worked through all ' + n + " invoice files in the inbox (" + esc(fmTxt) + ") in " + fmtDur(r.duration_ms) + ". " +
      plural(hard, "invoice was", "invoices were") + " decided by hard rules alone, because a blocking flag means it cannot be paid. " +
      (isLive(r) ? "The other " + (n - hard) + " went through a Grok risk review (" + plural(reviewed.length, "review") + ", " + plural(tools, "read-only tool call") + " to the vendor master, inventory and vendor history) and then the VP agent." :
        "The other " + (n - hard) + " went through the rules versions of the risk review and the VP, plus the critic where it was triggered, with no model calls.") + "</p></section>");

    // 2. final state
    var groups = {}, order = [];
    rej.forEach(function (i) { var c = catOf(i); if (!groups[c[0]]) { groups[c[0]] = { c: c, items: [] }; order.push(c[0]); } groups[c[0]].items.push(i); });
    order.sort(function (a, b) { return CAT.findIndex(function (c) { return c[0] === a; }) - CAT.findIndex(function (c) { return c[0] === b; }); });
    var headline = "Rejected " + rej.length + ": " + order.map(function (k) { return groups[k].items.length + " " + catLabel(groups[k].c); }).join(", ") + ".";
    h.push('<section class="m-sec"><h3>2. Final state</h3><div class="st-cards">' +
      '<div class="st approve"><b>' + appr.length + "</b> approved and paid</div>" +
      '<div class="st reject"><b>' + rej.length + "</b> rejected</div>" +
      '<div class="st review"><b>' + held.length + "</b> held for a human</div></div>" +
      '<p class="headline">' + esc(headline) + "</p>" +
      order.map(function (k) {
        var g = groups[k];
        return '<div class="grp"><div class="grp-h">' + g.items.length + " " + esc(catLabel(g.c)) + '</div><ul class="r-list">' + g.items.map(function (i) {
          return invLine(i, '<div class="r-why">' + esc((i.decision.reasons || []).join(" · ")) + "</div>");
        }).join("") + "</ul></div>";
      }).join("") + "</section>");

    // 3. paid
    h.push('<section class="m-sec"><h3>3. What I paid</h3>' + (paid.length ? "<p>" + plural(paid.length, "invoice") + ", " + money(paidSum) + " in total, each paid once through the mock bank with an idempotency key.</p>" +
      '<div class="tbl-wrap"><table class="r-t stack"><thead><tr><th>Invoice</th><th>Vendor</th><th class="r-num">Amount</th><th>Bank reply</th><th>VP conditions</th></tr></thead><tbody>' +
      paid.map(function (i) {
        return "<tr><td><b>" + esc(invNumber(i.number)) + '</b><div class="mono small muted">' + esc(i.file) + '</div></td><td data-l="Vendor">' + vendorHtml(i.vendor) + '</td><td class="r-num mono" data-l="Amount">' + money(i.payment.amount) + '</td><td class="small" data-l="Bank reply">' + esc(i.payment.bank_message || i.payment.status) + (i.payment.attempts ? ", attempt " + esc(i.payment.attempts) : "") + '</td><td class="small" data-l="VP conditions">' + ((i.decision.conditions || []).length ? esc(i.decision.conditions.join(" · ")) : '<span class="muted">none</span>') + "</td></tr>";
      }).join("") + '</tbody><tfoot><tr><td colspan="2"><b>Total</b></td><td class="r-num mono" data-l="Total"><b>' + money(paidSum) + "</b></td><td colspan='2' class='empty'></td></tr></tfoot></table></div>" : "<p>Nothing was paid in this run.</p>") + "</section>");

    // 4. blocked
    var hi = rej.filter(isFraudBlocked), hiSum = hi.reduce(function (a, i) { return a + (i.total_usd || 0); }, 0);
    var copies = rej.filter(function (i) { return flag(i, "DUPLICATE_INVOICE") || flag(i, "SUPERSEDED_BY_REVISION"); });
    var rejOrig = rej.filter(function (i) { return copies.indexOf(i) < 0; }), rejSum = rejOrig.reduce(function (a, i) { return a + Math.max(0, i.total_usd || 0); }, 0);
    h.push('<section class="m-sec"><h3>4. What I blocked</h3><p>' + plural(hi.length, "high-risk invoice") + " (risk score " + hr() + " or more) stopped before payment, " + money(hiSum) + " in total:</p><ul class='r-list'>" +
      hi.map(function (i) {
        return invLine(i, '<div class="r-why">Risk ' + esc(i.risk.score) + ". Signals: " + esc((i.risk.signals || []).map(function (s) { return s.reason; }).join("; ") || "none") + ". Stopped by: " + esc(blocks(i).join(", ")) + ".</div>");
      }).join("") + "</ul><p class='small muted'>Across all rejections, " + plural(rejOrig.length, "original invoice") + " worth " + money(rejSum) + " as billed did not reach payment" + (copies.length ? ", plus " + plural(copies.length, "duplicate or superseded copy", "duplicate or superseded copies") + " that would have paid the same bill twice" : "") + ". Negative totals are counted as zero.</p></section>");

    // 5. data errors
    var codes = {};
    invs.forEach(function (i) { i.flags.forEach(function (f) { if (f.severity === "info") return; var c = codes[f.code] || (codes[f.code] = { sev: f.severity, files: [], msg: [] }); if (c.files.indexOf(i.file) < 0) c.files.push(i.file); if (c.msg.length < 2 && c.msg.indexOf(f.message) < 0) c.msg.push(f.message); if (f.severity === "block") c.sev = "block"; }); });
    var fixes = {};
    invs.forEach(function (i) { i.flags.forEach(function (f) { if (f.severity !== "info" || !/OCR_CORRECTED|SKU_NORMALIZED|LINES_AGGREGATED/.test(f.code)) return; (fixes[f.code] = fixes[f.code] || []).indexOf(i.file) < 0 && fixes[f.code].push(i.file); }); });
    var ck = Object.keys(codes).sort(function (a, b) { return (codes[a].sev === "block" ? 0 : 1) - (codes[b].sev === "block" ? 0 : 1) || codes[b].files.length - codes[a].files.length; });
    h.push('<section class="m-sec"><h3>5. Data errors I found in the sample</h3><div class="tbl-wrap"><table class="r-t stack errs"><thead><tr><th>Severity</th><th>Finding</th><th class="r-num">Files</th><th>Example from the trace</th></tr></thead><tbody>' +
      ck.map(function (c) { var x = codes[c]; return '<tr><td><span class="sev ' + x.sev + '">' + x.sev + '</span></td><td class="mono small">' + esc(c) + '</td><td class="r-num" data-l="Files">' + x.files.length + '</td><td class="small">' + esc(x.msg[0]) + '<div class="muted mono small">' + esc(x.files.join(", ")) + "</div></td></tr>"; }).join("") +
      "</tbody></table></div>" + (Object.keys(fixes).length ? "<p class='small muted'>Fixed automatically and noted in the trace: " + Object.keys(fixes).map(function (c) { return esc(c) + " (" + esc(fixes[c].join(", ")) + ")"; }).join("; ") + ".</p>" : "") + "</section>");

    // 6. needs a human
    h.push('<section class="m-sec"><h3>6. What needs a human</h3>' + (held.length ? "<p>" + plural(held.length, "invoice is", "invoices are") + " waiting in the review queue. Nothing is paid until someone approves it. For each one, here is why I held it and the next steps the VP set.</p>" +
      held.map(function (i) {
        var ow = owners(i), crit = i.timeline.filter(function (e) { return e.step === "critic_review"; });
        return '<div class="hold card"><div class="hold-h"><div><b>' + esc(invNumber(i.number)) + "</b>" + dupTag(i) + ' <span class="muted">· ' + vendorHtml(i.vendor) + '</span><div class="mono small muted">' + esc(i.file) + " · " + esc(riskText(i.risk)) + "</div></div><div class='amount sm'>" + money(i.total_usd) + "</div></div>" +
          '<div class="hold-b"><div><div class="sub-h">Why I held it</div>' + list(i.decision.reasons) + "</div>" +
          '<div><div class="sub-h">Next steps</div>' + ((i.decision.conditions || []).length ? list(i.decision.conditions) : '<p class="small muted">No conditions were recorded for this invoice.</p>') +
          (crit.length ? '<div class="sub-h">Critic objections</div>' + list(crit.map(function (c) { return "Round " + c.detail.round + ": " + c.detail.reason; })) : "") +
          '<p class="small"><b>Who:</b> ' + (ow.length ? esc(ow.join(" and ")) + ", as named in the VP's own words, then an AP approver in the review queue." : "an AP approver in the review queue. The trace does not name a team.") + '</p><p class="mono small cli">python main.py review ' + esc(i.number) + ' --approve --note "..."</p></div></div></div>';
      }).join("") : "<p>Nothing is waiting for a human.</p>") + "</section>");

    // 7. recommendations, each triggered by something in the data
    var rec = [];
    var ren = invs.filter(function (i) { return flag(i, "VENDOR_RENAMED") && i.decision.status !== "REJECTED"; });
    ren.forEach(function (i) { var f = flag(i, "VENDOR_RENAMED"); rec.push("Confirm whether " + f.evidence.vendor + " really is the renamed " + f.evidence.former + " by calling the contact on file, then record the alias in the vendor master or reject " + invNumber(i.number) + "."); });
    var noAddr = [];
    invs.forEach(function (i) { i.timeline.forEach(function (e) { var d = e.detail; if (e.step === "tool_call" && d.tool === "lookup_vendor" && d.result && d.result.found && !d.result.address && noAddr.indexOf(d.result.name) < 0) noAddr.push(d.result.name); }); });
    if (noAddr.length) rec.push("The vendor master has no address on file for " + plural(noAddr.length, "approved vendor") + " that the risk agent looked up (" + noAddr.join("; ") + "). Fill these in so a remit address can be checked before payment.");
    var dupN = invs.filter(function (i) { return flag(i, "DUPLICATE_INVOICE"); });
    if (dupN.length) rec.push(plural(dupN.length, "invoice") + " arrived twice in different formats (" + dupN.map(function (i) { return i.file + " copies " + base(flag(i, "DUPLICATE_INVOICE").evidence.first_seen); }).join("; ") + "). Ask vendors to send one format, and keep the duplicate check as the first gate.");
    var unk = []; invs.forEach(function (i) { i.flags.forEach(function (f) { if (f.code === "UNKNOWN_ITEM") { var m = /'([^']+)'/.exec(f.message); if (m && unk.indexOf(m[1]) < 0) unk.push(m[1]); } }); });
    if (unk.length) rec.push("Check whether " + unk.join(", ") + " are new catalog items or vendor errors. They are not in inventory, so those invoices were rejected.");
    var stockN = rej.filter(function (i) { return blocks(i).indexOf("STOCK_EXCEEDED") >= 0 && !flag(i, "DUPLICATE_INVOICE"); });
    if (stockN.length) rec.push(plural(stockN.length, "invoice was", "invoices were") + " rejected for asking for more than the stock on hand. If the inventory table is out of date, refresh it and re-run those files.");
    var fx = invs.filter(function (i) { return flag(i, "CURRENCY_CONVERTED"); });
    if (fx.length) rec.push("Agree a price list in " + fx.map(function (i) { return i.currency; }).filter(function (v, k, a) { return a.indexOf(v) === k; }).join(", ") + " with " + fx.map(function (i) { return i.vendor; }).join(", ") + "; the run converted at a mock rate.");
    if (o) {
      var diffs = invs.map(function (i) { var j = o.invoices.find(function (x) { return x.file === i.file; }); return j && j.decision.status !== i.decision.status ? [i, j] : null; }).filter(Boolean);
      if (diffs.length) {
        var cautious = diffs.every(function (p) { return statusRank(isLive(r) ? p[0].decision.status : p[1].decision.status) > statusRank(isLive(r) ? p[1].decision.status : p[0].decision.status); });
        rec.push("The " + runLabel(o) + " decided " + plural(diffs.length, "invoice") + " differently (" + diffs.map(function (p) { return invNumber(p[0].number) + ": " + (PILL[p[0].decision.status] || [0, p[0].decision.status])[1].toLowerCase() + " here, " + (PILL[p[1].decision.status] || [0, p[1].decision.status])[1].toLowerCase() + " there"; }).join("; ") + ")." + (cautious ? " Every difference has the live Grok run being more cautious, never less." : ""));
      } else rec.push("The " + runLabel(o) + " reached the same outcome on every invoice.");
    }
    h.push('<section class="m-sec"><h3>7. Recommendations</h3><p class="small muted">Each one is triggered by a finding above.</p><ol class="recs">' + rec.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ol></section>");

    // compare table
    if (o) {
      h.push('<section class="m-sec"><h3>Compare with the ' + runLabel(o) + '</h3><p class="small muted">Offline, the VP and critic are fixed rules written from the same prompts, with no API calls. Live, Grok does the risk review, the VP and the critic. The critic only reviews approvals, so when the live VP holds an invoice the critic never runs.</p><div class="tbl-wrap"><table class="r-t"><thead><tr><th>Invoice</th><th>' + (isLive(r) ? "Live" : "Offline") + "</th><th>" + (isLive(o) ? "Live" : "Offline") + "</th></tr></thead><tbody>" +
        invs.map(function (i) { var j = o.invoices.find(function (x) { return x.file === i.file; }); var d = j && j.decision.status !== i.decision.status; return "<tr" + (d ? ' class="diff"' : "") + "><td><b>" + esc(invNumber(i.number)) + "</b>" + dupTag(i) + '<div class="mono small muted">' + esc(i.file) + "</div></td><td>" + pill(i.decision.status) + "</td><td>" + (j ? pill(j.decision.status) : "-") + "</td></tr>"; }).join("") + "</tbody></table></div></section>");
    }
    $("memo").innerHTML = h.join("");
  }

  /* ---------- events ---------- */
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t.closest("#go") || t.closest("#go-top")) { startRun("live"); return; }
    if (t.closest("#go-offline")) { startRun("offline"); return; }
    if (t.closest("#replay")) { startRun(REPORT); return; }
    if (t.closest("#pause")) { if (P && !P.finished) { P.playing = !P.playing; P.last = performance.now(); setPauseLabel(); updateBar(); if (P.playing) closeInspector(); } return; }
    if (t.closest("#skip")) { skipToEnd(); return; }
    var sp = t.closest("[data-speed]");
    if (sp) { if (P) P.speed = +sp.dataset.speed; document.querySelectorAll("[data-speed]").forEach(function (x) { x.classList.toggle("on", x === sp); x.setAttribute("aria-pressed", x === sp); }); if (P) updateBar(); return; }
    var q = t.closest("[data-q]");
    if (q) { inspect(+q.dataset.q); return; }
    if (t.closest("#insp-close")) { var k0 = document.querySelector(".q-item.picked"); closeInspector(); if (P && !P.finished) { P.playing = true; P.last = performance.now(); setPauseLabel(); updateBar(); } if (k0) k0.focus({ preventScroll: true }); return; }
    var rp = t.closest("[data-rep]");
    if (rp) { REPORT = rp.dataset.rep; renderReport(); setRun(REPORT); renderAll(); return; }
    var of = t.closest("[data-open-file]");
    if (of) { setRun(REPORT, "case"); SELECTED = of.dataset.openFile; renderAll(); jump("demo"); return; }
    var b = t.closest("[data-run]");
    if (b) { setRun(b.dataset.run); renderAll(); if (DATA.runs[b.dataset.run] && REPORT !== b.dataset.run) { REPORT = b.dataset.run; if (!$("report").hidden) renderReport(); else syncRepButtons(); } return; }
    var st = t.closest("[data-set]");
    if (st) { setRun(MODE, st.dataset.set); renderAll(); return; }
    var c = t.closest("#filters .chip");
    if (c) { FILTER = c.dataset.f; document.querySelectorAll("#filters .chip").forEach(function (x) { x.classList.toggle("on", x === c); x.setAttribute("aria-pressed", x === c); }); renderInbox(); return; }
    var i = t.closest(".inv");
    if (i) { SELECTED = i.dataset.file; renderInbox(); renderDetail(); if (window.innerWidth < 900) $("detail").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth" }); return; }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !$("inspector").hidden) $("insp-close").click();
  });

  fetch("/data/demo.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
    DATA = d;
    var qs = new URLSearchParams(location.search);
    var want = qs.get("inv");
    setRun("live", "case");
    setRun(qs.get("run") || "live", qs.get("set") || "case");
    if (DATA.runs[MODE]) REPORT = MODE;
    if (want && run().invoices.some(function (i) { return i.file === want; })) SELECTED = want;
    renderOverview(); renderAll();
    if (location.hash === "#report") { P = null; startRun("live"); skipToEnd(); }
  }).catch(function () { $("honesty").textContent = "Could not load run data."; $("detail").textContent = "Could not load run data."; });
})();
