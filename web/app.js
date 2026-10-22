(function () {
  var DATA = null, MODE = "offline", SET = "case", FILTER = "all", SELECTED = null;
  var PILL = { APPROVED: ["approve", "Approved"], REJECTED: ["reject", "Rejected"], PENDING_HUMAN: ["review", "Needs review"] };
  var $ = function (id) { return document.getElementById(id); };

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
  function key(mode, set) { return (set === "extra" ? "extra_" : "") + mode; }
  function run() { return DATA.runs[key(MODE, SET)]; }
  function other() { return DATA.runs[key(MODE === "offline" ? "live" : "offline", SET)]; }
  function invNumber(n) { return n ? String(n).replace(/\s+R(\d+)$/, ", Revision $1") : "No invoice number"; }
  function vendorHtml(v) { return v ? esc(v) : '<span class="missing">Missing vendor</span>'; }
  function flag(inv, code) { return inv.flags.find(function (f) { return f.code === code; }); }
  function base(p) { return String(p || "").split("/").pop(); }
  function dupNote(inv) {
    var f = flag(inv, "DUPLICATE_INVOICE");
    if (f) return "Duplicate of " + base(f.evidence.first_seen) + ", not paid twice";
    f = flag(inv, "SUPERSEDED_BY_REVISION");
    if (f) return "Replaced by a later revision (" + base(f.evidence.superseded_by) + "), not paid";
    f = flag(inv, "REVISION_SUPERSEDES");
    if (f) return "Revision 1 of " + base(f.evidence.supersedes) + "; only this version can be paid";
    return "";
  }
  function riskText(r) {
    var det = r.deterministic_score;
    if (det != null && r.score !== det) return "risk: rules " + det + ", Grok raised to " + r.score;
    return "risk " + r.score;
  }
  function isFraudBlocked(inv) {
    return inv.decision.status === "REJECTED" && (inv.risk.score || 0) >= DATA.policy.high_risk_score;
  }

  function renderSummary() {
    var invs = run().invoices, paid = 0, nPaid = 0, rej = 0, held = 0, fraud = 0, fraudN = 0;
    invs.forEach(function (i) {
      if (i.payment && i.payment.status === "paid") { paid += i.payment.amount; nPaid++; }
      if (i.decision.status === "REJECTED") rej++;
      if (i.decision.status === "PENDING_HUMAN") held++;
      if (isFraudBlocked(i)) { fraud += i.total_usd || 0; fraudN++; }
    });
    $("summary").innerHTML =
      card(money(paid), nPaid + " invoices paid") +
      card(String(rej), "rejected, with reasons logged") +
      card(String(held), "sent to a human") +
      card(money(fraud), fraudN + " high-risk invoices blocked", "Rejected invoices with risk score " + DATA.policy.high_risk_score + " or more");
    var r = run();
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
      var dup = flag(i, "DUPLICATE_INVOICE") ? '<span class="tag dup">Duplicate</span>' : flag(i, "SUPERSEDED_BY_REVISION") ? '<span class="tag dup">Superseded</span>' : "";
      return '<li><button class="inv' + (i.file === SELECTED ? " on" : "") + '" data-file="' + esc(i.file) + '">' +
        '<span class="inv-main"><b>' + esc(invNumber(i.number)) + dup + '</b><span class="small' + (i.vendor ? " muted" : "") + '">' + vendorHtml(i.vendor) + '</span></span>' +
        '<span class="inv-side"><span class="money">' + money(i.total_usd) + "</span>" + pill(i.decision.status) + "</span>" +
        '<span class="inv-meta mono small muted">' + esc(i.file) + " · " + esc(riskText(i.risk)) + (blocks ? " · " + blocks + " blocking" : "") +
        (dn ? '<span class="why">' + esc(dn) + "</span>" : "") + "</span>" +
        "</button></li>";
    }).join("");
    $("inbox").innerHTML = html || '<li class="muted small pad">No invoices with this status in this run.</li>';
  }

  function stepView(ev, inv) {
    var d = ev.detail || {}, title = "", body = "", cls = "";
    switch (ev.agent + "." + ev.step) {
      case "ingestion.read": title = "Read " + esc(d.format) + " file"; body = esc(d.chars) + " characters"; break;
      case "ingestion.deterministic_parse": title = d.ok ? "Parsed by deterministic parser" : "Parser could not read it"; body = esc(d.error || ""); break;
      case "ingestion.llm_repair":
        if (d.attempts) {
          title = "Grok extracted it (" + d.attempts.length + (d.attempts.length === 1 ? " attempt" : " attempts") + ", " + esc(d.model) + ")";
          body = d.attempts.map(function (a) { return "Attempt " + esc(a.attempt) + ": " + (a.ok ? "valid against the schema" : "failed validation, error sent back: " + esc(String(a.error).slice(0, 220))); }).join("<br>");
          cls = "good";
        } else { title = "Grok extraction failed"; body = esc(d.error); cls = "bad"; }
        break;
      case "risk.tool_call": title = "Grok called " + esc(d.tool) + "(" + esc(typeof d.args === "object" ? Object.keys(d.args).map(function (k) { return k + "=" + JSON.stringify(d.args[k]); }).join(", ") : d.args) + ")";
        body = '<span class="mono small">' + esc(JSON.stringify(d.result)) + "</span>"; break;
      case "ingestion.extracted": title = "Extracted " + inv.items.length + " line items"; body = inv.items.map(function (li) {
        return esc(li.qty) + " x " + esc(li.sku || li.sku_raw + " (unknown)") + " @ " + money(li.unit_price) + (li.note ? " (" + esc(li.note) + ")" : "");
      }).join("<br>"); break;
      case "validation.validate": title = "Validated: " + d.flags.length + " flags, " + d.blocking.length + " blocking";
        body = d.flags.length ? esc(d.flags.join(", ")) : "No flags"; cls = d.blocking.length ? "bad" : "good"; break;
      case "risk.assess": title = "Risk score " + esc(d.score) + (d.llm && d.llm.score != null && d.score !== d.deterministic_score ? " (rules " + esc(d.deterministic_score) + ", Grok raised it to " + esc(d.score) + ")" : "");
        body = (d.reasons || []).map(esc).join("<br>") || "No risk signals"; break;
      case "approval.vp_propose": title = "VP proposes: " + esc(d.decision); body = list(d.reasons) + cond(d.conditions); cls = "vp"; break;
      case "approval.critic_review": title = "Critic, round " + esc(d.round) + ": " + (d.verdict === "object" ? "objects" : "signs off"); body = esc(d.reason); cls = "critic " + (d.verdict === "object" ? "bad" : "good"); break;
      case "approval.vp_revise": title = "VP revises, round " + esc(d.round) + ": " + esc(d.decision); body = list(d.reasons) + cond(d.conditions); cls = "vp"; break;
      case "approval.decide": title = "Decision: " + (PILL[d.status] || [0, d.status])[1] + " by " + esc({ hard_rules: "hard rules", vp: "the VP", "vp+critic": "the VP after critic review", deadlock: "deadlock (VP and critic disagree)", error: "error fallback" }[d.decided_by] || d.decided_by) + (d.critique_rounds ? ", " + d.critique_rounds + " critic rounds" : "");
        body = list(d.reasons); cls = d.status === "APPROVED" ? "good" : d.status === "REJECTED" ? "bad" : "warn"; break;
      case "payment.paid": title = "Paid " + money(d.amount) + " on attempt " + esc(d.attempts); body = '<span class="mono small">bank: ' + esc(d.bank_message) + "<br>key " + esc(d.idempotency_key) + "</span>"; cls = "good"; break;
      case "payment.bank_error": title = "Bank error, attempt " + esc(d.attempt); body = esc(d.error); cls = "bad"; break;
      case "payment.failed": title = "Payment failed"; body = esc((d.errors || []).join("; ")); cls = "bad"; break;
      case "payment.idempotency_skip": title = "Already paid, skipped"; break;
      case "payment.rejection_logged": title = "Not paid. Rejection logged to the audit trail"; cls = "bad"; break;
      case "hitl.queued": title = "Queued for human review"; body = '<span class="mono small">python main.py review ' + esc(inv.number) + " --approve</span>"; cls = "warn"; break;
      default: title = esc(ev.agent + " " + ev.step);
    }
    return '<li class="step ' + cls + '"><div class="step-head"><span class="agent">' + esc(ev.agent) + '</span><span class="ms mono small muted">' + esc(ev.ms) + ' ms</span><span class="step-title">' + title +
      "</span></div>" + (body ? '<div class="step-body">' + body + "</div>" : "") + "</li>";
  }
  function list(a) { return a && a.length ? "<ul class='reasons'>" + a.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>" : ""; }
  function cond(a) { return a && a.length ? "<div class='conds'><b>Conditions</b>" + list(a) + "</div>" : ""; }

  function riskMeter(score) {
    var s = Math.max(0, Math.min(100, score || 0));
    return '<div class="meter"><div class="meter-row"><span>Risk</span><span class="mono">' + s + " / 100</span></div>" +
      '<div class="meter-bar"><span style="left:' + s + '%"></span></div></div>';
  }

  function renderDetail() {
    var inv = run().invoices.find(function (i) { return i.file === SELECTED; }) || run().invoices[0];
    SELECTED = inv.file;
    var d = inv.decision;
    var flags = inv.flags.length ? '<table class="flags-t"><thead><tr><th>Severity</th><th>Code</th><th>Finding</th></tr></thead><tbody>' +
      inv.flags.map(function (f) {
        return '<tr><td><span class="sev ' + esc(f.severity) + '">' + esc(f.severity) + "</span></td><td class='mono small'>" + esc(f.code) +
          "</td><td>" + esc(f.message) + "<details><summary>evidence</summary><pre>" + esc(JSON.stringify(f.evidence, null, 1)) + "</pre></details></td></tr>";
      }).join("") + "</tbody></table>" : '<p class="muted small">No flags.</p>';
    $("detail").innerHTML =
      '<div class="inv-head"><div><div class="mono small muted">' + esc(inv.file) + '</div><div class="inv-id">' + esc(invNumber(inv.number)) + " · " + vendorHtml(inv.vendor) + "</div>" +
      (inv.vendor ? '<div class="as-written">Names and labels are shown as written on the invoice, typos included.</div>' : "") + "</div>" + pill(d.status) + "</div>" +
      (dupNote(inv) ? '<div class="note">' + esc(dupNote(inv)) + ".</div>" : "") +
      '<div class="amount">' + money(inv.total_usd) + (inv.currency && inv.currency !== "USD" ? ' <span class="small muted">(' + esc(inv.currency) + " " + esc(inv.total) + ")</span>" : "") + "</div>" +
      riskMeter(inv.risk.score) +
      '<div class="decision"><b>Why</b>' + list(d.reasons) + cond(d.conditions) + "</div>" +
      "<h3 class='dh'>Agent timeline</h3><ol class='timeline'>" + inv.timeline.map(function (ev) { return stepView(ev, inv); }).join("") + "</ol>" +
      "<h3 class='dh'>Flags</h3>" + flags;
  }

  function renderHero() {
    var r = DATA.runs.offline, inv = r.invoices.find(function (i) { return i.decision.critique_rounds > 0; }) || r.invoices[0];
    var crit = inv.timeline.filter(function (e) { return e.step === "critic_review"; });
    $("hero-card").innerHTML =
      '<div class="preview-top"><span class="label">Real output</span><span class="label muted">offline run</span></div>' +
      '<div class="inv-head"><div><div class="mono small muted">' + esc(inv.file) + '</div><div class="inv-id">' + esc(invNumber(inv.number)) + "</div></div>" + pill(inv.decision.status) + "</div>" +
      '<div class="amount">' + money(inv.total_usd) + "</div>" + riskMeter(inv.risk.score) +
      '<ul class="flags">' + crit.map(function (c) { return '<li><span class="sev warn">critic ' + esc(c.detail.round) + "</span>" + esc(c.detail.reason) + "</li>"; }).join("") + "</ul>" +
      '<div class="steps"><span class="s done">Ingest</span><span class="s done">Validate</span><span class="s done">VP ⇄ Critic x' + esc(inv.decision.critique_rounds) + '</span><span class="s hold">Human review</span></div>' +
      '<a class="small hero-link" href="#demo" data-open="' + esc(inv.file) + '">See the full trace</a>';
  }

  function setRun(mode, set) {
    set = set || SET;
    if (!DATA.runs[key(mode, set)]) return;
    MODE = mode; SET = set;
    document.querySelectorAll("[data-run]").forEach(function (x) { x.classList.toggle("on", x.dataset.run === MODE); x.disabled = !DATA.runs[key(x.dataset.run, SET)]; });
    document.querySelectorAll("[data-set]").forEach(function (x) { x.classList.toggle("on", x.dataset.set === SET); x.disabled = !DATA.runs[key(MODE, x.dataset.set)]; });
    if (!run().invoices.some(function (i) { return i.file === SELECTED; })) SELECTED = run().invoices[0].file;
  }

  function renderAll() { renderSummary(); renderInbox(); renderDetail(); }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-run]");
    if (b) { setRun(b.dataset.run); renderAll(); return; }
    var st = e.target.closest("[data-set]");
    if (st) { setRun(MODE, st.dataset.set); renderAll(); return; }
    var c = e.target.closest("#filters .chip");
    if (c) { FILTER = c.dataset.f; document.querySelectorAll("#filters .chip").forEach(function (x) { x.classList.toggle("on", x === c); }); renderInbox(); return; }
    var i = e.target.closest(".inv");
    if (i) { SELECTED = i.dataset.file; renderInbox(); renderDetail(); if (window.innerWidth < 900) $("detail").scrollIntoView({ behavior: "smooth" }); return; }
    var h = e.target.closest("[data-open]");
    if (h) { SELECTED = h.dataset.open; setRun("offline", "case"); renderAll(); }
  });

  fetch("/data/demo.json").then(function (r) { return r.json(); }).then(function (d) {
    DATA = d;
    var q = new URLSearchParams(location.search);
    SELECTED = q.get("inv");
    setRun("offline", "case");
    setRun(q.get("run") || "offline", q.get("set") || "case");
    renderHero(); renderAll();
  }).catch(function () { $("detail").textContent = "Could not load run data."; });
})();
