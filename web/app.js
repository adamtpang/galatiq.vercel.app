(function () {
  "use strict";
  var DATA = null, SRC = {}, MODE = "live", SET = "case", FILTER = "all", SELECTED = null, REPORT = "live", P = null;
  var PILL = { APPROVED: ["approve", "Approved"], REJECTED: ["reject", "Rejected"], PENDING_HUMAN: ["review", "Held for a human"] };
  var BY = { hard_rules: "hard rules", hard_hold: "a hard hold rule", vp: "the VP agent", "vp+critic": "the VP after critic review", deadlock: "deadlock, VP and critic disagree", error: "error fallback" };
  var TRIG = { over_threshold: "over the limit", near_limit: "near the limit", high_risk: "high risk" };
  var SEV = { block: "Blocking: rules out payment", warn: "Warning: does not block on its own", info: "Info: noted for the record" };
  var AGENT = { ingestion: "Ingest", validation: "Validate", risk: "Risk", approval: "Approval", memo: "Memo", payment: "Payment", hitl: "Review" };
  var STAGES = [["ingestion", "Ingest", "Read the file"], ["validation", "Validate", "Stock, math, dates, duplicates"], ["risk", "Risk", "Fraud score; Grok checks claims with read-only tools"], ["vp", "VP", "Proposes approve, hold or reject"], ["critic", "Critic", "Second agent that challenges VP approvals"], ["outcome", "Outcome", "Pay, reject, or hold for a person"]];
  var README = "https://github.com/adamtpang/galatiq.vercel.app#quickstart-offline-about-a-minute";
  var SCALE = 25, MIN_STEP = 130, INTRO = 280, OUTRO = 170;
  var $ = function (id) { return document.getElementById(id); };
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  function money(v) {
    if (v == null) return "-";
    var neg = v < 0; v = Math.abs(v);
    return (neg ? "-$" : "$") + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function whole(v) { return money(v).replace(/\.00$/, ""); }
  function pill(status) { var p = PILL[status] || ["", status || "-"]; return '<span class="pill ' + p[0] + '">' + p[1] + "</span>"; }
  function statusName(s) { return (PILL[s] || [0, s])[1]; }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
  function key(mode, set) { return (set && set !== "case" ? set + "_" : "") + mode; }
  function run() { return DATA.runs[key(MODE, SET)]; }
  function invNumber(n) { return n ? String(n).replace(/\s+R(\d+)$/, ", Revision $1") : "No invoice number"; }
  function vendorHtml(v) { return v ? esc(v) : '<span class="missing">Missing vendor</span>'; }
  function flag(inv, code) { return inv.flags.find(function (f) { return f.code === code; }); }
  function base(p) { return String(p || "").split("/").pop(); }
  function hr() { return DATA.policy.high_risk_score; }
  function isLive(r) { return r.mode !== "offline"; }
  function runName(mode) { var r = DATA.runs[mode]; return mode === "live" ? "Live " + ((r && r.model) || "Grok") : "Offline rules"; }
  function runLabel(r) { return isLive(r) ? "live " + (r.model || "Grok") + " run" : "offline rules run"; }
  function list(a) { return a && a.length ? "<ul class='reasons'>" + a.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>" : ""; }
  function more(label, body, open) { return body ? "<details class='more'" + (open ? " open" : "") + "><summary>" + label + "</summary><div class='more-b'>" + body + "</div></details>" : ""; }
  function fmtClock(ms) { var s = Math.max(0, Math.round(ms / 1000)), m = Math.floor(s / 60); return m + ":" + String(s % 60).padStart(2, "0"); }
  function fmtDur(ms) { var s = Math.round(ms / 1000); if (s < 1) return ms + " ms"; if (s < 60) return s + " s"; return Math.floor(s / 60) + " min " + (s % 60) + " s"; }
  function fmtWhen(iso) {
    var d = new Date(iso);
    var date = d.toLocaleDateString("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", year: "numeric" });
    var time = d.toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
    return { date: date, time: time, full: date + ", " + time };
  }
  function dupNote(inv) {
    var f = flag(inv, "DUPLICATE_INVOICE");
    if (f) return "Duplicate of " + base(f.evidence.first_seen) + ". Not paid twice.";
    f = flag(inv, "SUPERSEDED_BY_REVISION");
    if (f) return "Replaced by " + base(f.evidence.superseded_by) + ". Not paid.";
    f = flag(inv, "REVISION_SUPERSEDES");
    if (f) return "Revision 1 of " + base(f.evidence.supersedes) + ". Only this version can be paid.";
    return "";
  }
  function dupTag(i) { return flag(i, "DUPLICATE_INVOICE") ? '<span class="tag">Duplicate</span>' : flag(i, "SUPERSEDED_BY_REVISION") ? '<span class="tag">Superseded</span>' : ""; }
  function riskText(r) { var d = r.deterministic_score; return d != null && r.score !== d ? "risk " + r.score + " (rules " + d + ")" : "risk " + r.score; }
  function isFraudBlocked(inv) { return inv.decision.status === "REJECTED" && (inv.risk.score || 0) >= hr(); }
  function grokReasons(inv) { return (inv.risk.llm && inv.risk.llm.extra_reasons) || []; }
  function ruleReasons(inv) { return (inv.risk.reasons || []).filter(function (r) { return !/^\(Grok\) /.test(r); }); }
  function reviewCmd(i) {
    var repaired = i.decision && (i.decision.reasons || []).some(function (r) { return /^LLM_REPAIRED/.test(r); });
    return (repaired ? '<p class="small">Grok rebuilt this invoice from the raw text (decision 10). This shows the original next to Grok\'s reading:</p><code class="block">python main.py review ' + esc(i.number) + "</code>" : "") +
      '<code class="block">python main.py review ' + esc(i.number) + ' --approve --note "..."</code>';
  }
  function blocks(i) { return i.flags.filter(function (f) { return f.severity === "block"; }).map(function (f) { return f.code; }); }
  function hasBlock(i) { return blocks(i).length > 0; }

  /* ---------- original file and extracted fields ---------- */
  function parseCsv(t) {
    return t.replace(/\r/g, "").split("\n").filter(function (l) { return l.trim() !== ""; }).map(function (l) {
      var out = [], cur = "", q = false;
      for (var i = 0; i < l.length; i++) { var c = l[i]; if (c === '"') q = !q; else if (c === "," && !q) { out.push(cur); cur = ""; } else cur += c; }
      out.push(cur); return out;
    });
  }
  function originalHtml(file) {
    var s = SRC[file];
    if (!s) return '<p class="small muted">Original file not available.</p>';
    var head = '<div class="orig-meta small muted">' + esc(s.folder + "/" + file) + " · " + esc(s.format.toUpperCase()) + ' · <a href="' + esc(s.url) + '" target="_blank" rel="noopener">Open file</a></div>';
    if (s.format === "pdf") {
      return head + (s.pages || []).map(function (p, k) { return '<img class="pdf-page" src="' + esc(p) + '" alt="Page ' + (k + 1) + " of " + esc(file) + '" loading="lazy">'; }).join("") +
        more("Text layer the parser reads", "<pre>" + esc(s.text) + "</pre>");
    }
    if (s.format === "json") {
      var pretty = null; try { pretty = JSON.stringify(JSON.parse(s.text), null, 2); } catch (e) { pretty = null; }
      return head + (pretty == null ? '<p class="small warn-t">Not valid JSON as received. Shown as written.</p><pre>' + esc(s.text) + "</pre>" : "<pre>" + esc(pretty) + "</pre>");
    }
    if (s.format === "csv") {
      var rows = parseCsv(s.text);
      return head + '<div class="tbl-wrap"><table class="csv">' + rows.map(function (r, k) { return "<tr>" + r.map(function (c) { return (k === 0 ? "<th>" : "<td>") + esc(c) + (k === 0 ? "</th>" : "</td>"); }).join("") + "</tr>"; }).join("") + "</table></div>" + more("Raw CSV", "<pre>" + esc(s.text) + "</pre>");
    }
    return head + "<pre>" + esc(s.text) + "</pre>";
  }
  function extractedHtml(inv) {
    var x = inv.extracted;
    if (!x) return '<p class="small muted">No fields were extracted from this file.</p>';
    var row = function (k, v) { return "<div><dt>" + k + "</dt><dd>" + v + "</dd></div>"; };
    var ns = '<span class="muted">Not stated</span>';
    var items = inv.items.length ? '<table class="items"><thead><tr><th>Item as written</th><th>Matched</th><th class="r">Qty</th><th class="r">Price</th></tr></thead><tbody>' + inv.items.map(function (li) {
      return "<tr><td>" + esc(li.sku_raw) + (li.note ? '<div class="small muted">' + esc(li.note) + "</div>" : "") + "</td><td>" + (li.sku ? esc(li.sku) : '<span class="missing">Unknown</span>') + '</td><td class="r">' + esc(li.qty) + '</td><td class="r">' + money(li.unit_price) + "</td></tr>";
    }).join("") + "</tbody></table>" : '<p class="small muted">No line items.</p>';
    var cur = x.currency && x.currency !== "USD" ? " " + esc(x.currency) : "";
    return '<dl class="fields">' + row("Number", esc(invNumber(x.number))) + row("Vendor", vendorHtml(x.vendor) + (x.vendor_former_name ? '<div class="small muted">formerly ' + esc(x.vendor_former_name) + "</div>" : "")) +
      (x.vendor_address ? row("Address", esc(x.vendor_address)) : "") + row("Date", x.date_raw ? esc(x.date_raw) : ns) + row("Due", x.due_date_raw ? esc(x.due_date_raw) : ns) +
      row("Terms", x.terms ? esc(x.terms) : ns) + "</dl>" + items +
      '<dl class="fields sums">' + row("Subtotal", x.subtotal != null ? money(x.subtotal) + cur : ns) + row("Tax", x.tax != null ? money(x.tax) + cur : ns) + (x.shipping != null ? row("Shipping", money(x.shipping) + cur) : "") +
      row("Total", "<b>" + (x.total != null ? money(x.total) + cur : ns) + "</b>" + (cur ? '<div class="small muted">' + money(inv.total_usd) + " USD</div>" : "")) + "</dl>" +
      '<p class="small muted">Shown as written on the invoice, typos included.</p>';
  }
  function compareHtml(inv) {
    return '<div class="compare"><section><h4>Original</h4>' + originalHtml(inv.file) + "</section><section><h4>Extracted</h4>" + extractedHtml(inv) + "</section></div>";
  }
  function openSource(file) {
    $("src-title").textContent = file;
    $("src-body").innerHTML = originalHtml(file);
    var d = $("src-dialog");
    if (d.showModal) d.showModal(); else d.setAttribute("open", "");
    $("src-body").scrollTop = 0;
  }

  /* ---------- tool results, re-worded faithfully ---------- */
  function toolArgs(d) { return typeof d.args === "object" && d.args ? Object.keys(d.args).map(function (k) { return k + "=" + JSON.stringify(d.args[k]); }).join(", ") : String(d.args); }
  function toolSummary(d) {
    var r = d.result || {};
    if (d.tool === "lookup_vendor") return !r.found ? "Not in the vendor master" : "On file · approved " + (r.approved ? "yes" : "no") + " · bank " + (r.bank_on_file ? "on file" : "missing") + " · address " + (r.address ? "on file" : "none") + (r.aliases && r.aliases.length ? " · aliases " + r.aliases.join(", ") : "");
    if (d.tool === "query_inventory") return !r.found ? "Not in inventory" : "Stock " + r.stock + " · catalog " + money(r.catalog_unit_price_usd);
    if (d.tool === "vendor_history") { var n = (r.invoices || []).length; return n ? plural(n, "earlier invoice") : "No earlier invoices"; }
    return "";
  }

  /* ---------- one trace event: short title, one line, details on demand ---------- */
  function narrate(ev, inv, r) {
    var d = ev.detail || {}, o = { agent: ev.agent, title: "", what: "", body: "", cls: "" };
    switch (ev.agent + "." + ev.step) {
      case "ingestion.read": o.title = "Opened " + esc(inv.file); o.what = esc(String(d.format || "").toUpperCase()) + " · " + Number(d.chars).toLocaleString("en-US") + " characters"; break;
      case "ingestion.deterministic_parse":
        o.title = d.ok ? "Parsed by the " + esc((inv.format || "").toUpperCase()) + " parser" : "Parser could not read it";
        o.what = d.ok ? "No model call needed" : "Handing it to Grok";
        if (d.error) o.body = more("Parser error", '<code class="block">' + esc(d.error) + "</code>");
        o.cls = d.ok ? "" : "warn"; break;
      case "ingestion.llm_repair":
        if (d.attempts) {
          var last = d.attempts[d.attempts.length - 1];
          o.title = "Grok extracted it"; o.what = plural(d.attempts.length, "attempt") + (last && last.latency_s != null ? " · " + last.latency_s + " s" : "") + " · schema-checked";
          o.body = more("Attempts", d.attempts.map(function (a) { return "Attempt " + esc(a.attempt) + ": " + (a.ok ? "valid" : "failed, error sent back: " + esc(String(a.error).slice(0, 220))); }).join("<br>") + (d.prompt_tokens ? "<br>" + esc(d.prompt_tokens) + " prompt, " + esc(d.completion_tokens) + " completion tokens" : ""));
          o.cls = "good";
        } else { o.title = "Grok extraction failed"; o.what = esc(d.error); o.cls = "bad"; }
        break;
      case "ingestion.grok_cross_check":
        if (!d.ok) { o.title = "Grok cross-check failed"; o.what = esc(d.error); o.cls = "warn"; break; }
        o.title = d.agree ? "Grok read it too: same reading" : "Grok and the parser read it differently";
        o.what = d.agree ? "Independent Grok extraction matches the parser (vendor, number, total, lines, prices)" : esc((d.differences || []).join("; "));
        o.body = d.grok_reading ? more("Grok's reading", esc(d.grok_reading.vendor) + " · " + esc(d.grok_reading.number) + " · " + money(d.grok_reading.total) + "<br>" +
          (d.grok_reading.items || []).map(function (x) { return esc(x[1]) + " x " + esc(x[0]) + " @ " + money(x[2]); }).join("<br>")) : "";
        o.cls = d.agree ? "good" : "warn"; break;
      case "memo.memo":
        o.title = "Decision memo" + (d.by === "grok" ? " by Grok" : " (template, offline)"); o.what = esc(d.text);
        o.body = d.next_step ? '<p class="small muted">Next step: ' + esc(d.next_step) + "</p>" : ""; break;
      case "payment.guard_refused": o.title = "Payment refused by the last guard"; o.what = "Amount " + esc(d.amount) + " is not a finite number above zero"; o.cls = "bad"; break;
      case "ingestion.extracted":
        o.title = "Extracted " + esc(invNumber(inv.number));
        o.what = plural(inv.items.length, "line") + " · " + money(inv.total_usd) + (inv.currency && inv.currency !== "USD" ? " (" + esc(inv.currency) + " " + esc(inv.total) + ")" : "");
        o.body = more("Lines", inv.items.map(function (li) { return esc(li.qty) + " x " + esc(li.sku || li.sku_raw + " (unknown)") + " @ " + money(li.unit_price); }).join("<br>"));
        break;
      case "validation.validate":
        var nb = d.blocking.length, bl = inv.flags.filter(function (f) { return f.severity === "block"; });
        o.title = d.flags.length ? plural(d.flags.length, "flag") + (nb ? ", " + nb + " blocking" : "") : "Checks passed";
        o.what = nb ? bl.map(function (f) { return esc(f.message); }).join("<br>") : d.flags.length ? "Nothing blocking" : "Stock, math, dates, vendor, duplicates";
        if (inv.flags.length) o.body = more("All flags", '<ul class="fl">' + inv.flags.map(function (f) { return '<li><span class="sev ' + esc(f.severity) + '" title="' + esc(SEV[f.severity] || "") + '">' + esc(f.severity) + "</span><span>" + esc(f.message) + "</span></li>"; }).join("") + "</ul>");
        o.cls = nb ? "bad" : "good"; break;
      case "risk.tool_call":
        o.title = "<code>" + esc(d.tool) + "(" + esc(toolArgs(d)) + ")</code>"; o.what = esc(toolSummary(d));
        o.body = more("Raw result", "<pre>" + esc(JSON.stringify(d.result, null, 1)) + "</pre>"); o.cls = "tool"; break;
      case "risk.assess":
        var llm = d.llm, g = grokReasons(inv), rr = ruleReasons(inv), sig = inv.risk.signals || [];
        o.title = "Risk " + esc(d.score) + " / 100" + (llm && llm.score != null && d.score !== d.deterministic_score ? ", raised by Grok from " + esc(d.deterministic_score) : "");
        o.what = llm && !llm.error ? "Grok · " + plural(llm.tool_calls || 0, "tool call") + (llm.attempts && llm.attempts.length ? " · " + llm.attempts[llm.attempts.length - 1].latency_s + " s" : "") :
          llm && llm.error ? "Grok review errored" : isLive(r) ? "Rules only. Grok skips invoices that are already blocked." : "Rules only";
        o.body = (g.length ? more("Grok's reasoning (" + g.length + ")", list(g)) : "") +
          (sig.length || rr.length ? more("Rule signals (" + sig.length + ")", sig.length ? list(sig.map(function (s) { return s.reason + " (+" + s.weight + ")"; })) : list(rr)) : "");
        o.cls = d.score >= hr() ? "warn" : ""; break;
      case "approval.vp_propose":
        o.title = "VP proposes: " + esc(d.decision); o.what = isLive(r) ? "Grok as the VP" : "Rules version of the VP";
        o.body = more("VP's argument", list(d.reasons) + (d.conditions && d.conditions.length ? "<div class='sub-h'>Conditions</div>" + list(d.conditions) : "")); o.cls = "vp"; break;
      case "approval.critic_review":
        o.title = "Critic, round " + esc(d.round) + ": " + (d.verdict === "object" ? "objects" : "signs off"); o.what = esc(d.reason);
        o.cls = "crit " + (d.verdict === "object" ? "bad" : "good"); break;
      case "approval.vp_revise":
        o.title = "VP revises, round " + esc(d.round) + ": " + esc(d.decision);
        o.body = more("VP's argument", list(d.reasons) + (d.conditions && d.conditions.length ? "<div class='sub-h'>Conditions</div>" + list(d.conditions) : "")); o.cls = "vp"; break;
      case "approval.decide":
        var trig = (inv.decision.arguments && inv.decision.arguments.critic_triggers) || [];
        o.title = statusName(d.status) + " <span class='by'>by " + esc(BY[d.decided_by] || d.decided_by) + (d.critique_rounds ? ", " + plural(d.critique_rounds, "critic round") : "") + "</span>";
        o.what = list(d.reasons);
        var notes = [];
        if (d.decided_by === "hard_rules") notes.push("Blocking flags decide on their own.");
        else if (d.decided_by === "hard_hold") notes.push("Held for a person before the VP by a hard hold rule (prompt injection, renamed or lookalike vendor, changed bank details, Grok and parser disagree, or a layout nobody could confirm).");
        else if (trig.length && !d.critique_rounds) notes.push("Critic not run (" + trig.map(function (t) { return TRIG[t] || t; }).join(", ") + "): it only reviews approvals.");
        o.body = (notes.length ? '<p class="small muted">' + notes.join(" ") + "</p>" : "") + (d.conditions && d.conditions.length ? more("Next steps (" + d.conditions.length + ")", list(d.conditions), true) : "");
        o.cls = "decide " + (d.status === "APPROVED" ? "good" : d.status === "REJECTED" ? "bad" : "warn"); break;
      case "payment.paid": o.title = "Paid " + money(d.amount); o.what = "Mock bank · attempt " + esc(d.attempts);
        o.body = more("Bank reply", esc(d.bank_message) + '<br>Idempotency key <code>' + esc(d.idempotency_key) + "</code>"); o.cls = "good"; break;
      case "payment.bank_error": o.title = "Bank error, attempt " + esc(d.attempt); o.what = esc(d.error); o.cls = "bad"; break;
      case "payment.failed": o.title = "Payment failed"; o.what = esc((d.errors || []).join("; ")); o.cls = "bad"; break;
      case "payment.idempotency_skip": o.title = "Already paid, skipped"; break;
      case "payment.rejection_logged": o.title = "Not paid"; o.what = "Logged with reasons"; o.cls = "bad"; break;
      case "hitl.queued": o.title = "Queued for a person"; o.what = "No money moves until someone decides";
        o.body = more("Review command", reviewCmd(inv)); o.cls = "warn"; break;
      default: o.title = esc(ev.agent + " " + ev.step);
    }
    return o;
  }
  function stepHtml(ev, inv, r) {
    var o = narrate(ev, inv, r);
    return '<li class="step ' + o.cls + '"><div class="step-head"><span class="agent">' + esc(AGENT[o.agent] || o.agent) + '</span><span class="ms" title="' + esc(Number(ev.ms).toLocaleString("en-US")) + ' ms after this invoice started">' + fmtClock(ev.ms) + '</span></div><div class="step-title">' + o.title + "</div>" +
      (o.what ? '<div class="step-what">' + o.what + "</div>" : "") + o.body + "</li>";
  }

  /* ---------- invoice detail (explorer and run inspector) ---------- */
  function riskMeter(score) {
    var s = Math.max(0, Math.min(100, score || 0));
    return '<div class="meter" title="Risk score ' + s + ' of 100. ' + hr() + ' or more is high risk"><div class="meter-row"><span>Risk</span><span>' + s + " / 100</span></div><div class='meter-bar'><span style='left:" + s + "%'></span></div></div>";
  }
  function detailHtml(inv, r) {
    var d = inv.decision;
    var flags = inv.flags.length ? '<ul class="fl">' + inv.flags.map(function (f) {
      return '<li><span class="sev ' + esc(f.severity) + '" title="' + esc(SEV[f.severity] || "") + '">' + esc(f.severity) + '</span><span>' + esc(f.message) + ' <code class="small">' + esc(f.code) + "</code>" + more("Evidence", "<pre>" + esc(JSON.stringify(f.evidence, null, 1)) + "</pre>") + "</span></li>";
    }).join("") + "</ul>" : "";
    return '<div class="inv-head"><div><div class="small muted">' + esc(inv.file) + '</div><div class="inv-id">' + esc(invNumber(inv.number)) + dupTag(inv) + '</div><div class="inv-v">' + vendorHtml(inv.vendor) + "</div></div>" + pill(d.status) + "</div>" +
      (dupNote(inv) ? '<p class="note">' + esc(dupNote(inv)) + "</p>" : "") +
      '<div class="amount">' + money(inv.total_usd) + (inv.currency && inv.currency !== "USD" ? ' <span class="small muted">' + esc(inv.currency) + " " + esc(inv.total) + "</span>" : "") + "</div>" +
      riskMeter(inv.risk.score) +
      '<div class="why"><div class="sub-h">Why</div>' + list(d.reasons) + (d.conditions && d.conditions.length ? "<div class='sub-h'>Conditions</div>" + list(d.conditions) : "") +
      (inv.memo ? "<div class='sub-h'>Memo" + (inv.memo.by === "grok" ? " by Grok" : " (template)") + "</div><p class='small'>" + esc(inv.memo.text) + "</p>" : "") + "</div>" +
      compareHtml(inv) +
      more("Agent steps (" + inv.timeline.length + ")", "<ol class='timeline'>" + inv.timeline.map(function (ev) { return stepHtml(ev, inv, r); }).join("") + "</ol>") +
      (flags ? more("Flags (" + inv.flags.length + ")", flags) : "");
  }

  /* ---------- explorer ---------- */
  function labelButtons() {
    document.querySelectorAll("[data-rep]").forEach(function (b) { var r = DATA.runs[b.dataset.rep]; if (r) b.innerHTML = esc(runName(b.dataset.rep)) + '<span class="seg-sub">' + esc(fmtWhen(r.recorded_at).time) + "</span>"; });
    document.querySelectorAll("[data-run]").forEach(function (b) { var r = DATA.runs[key(b.dataset.run, SET)]; if (r) b.innerHTML = esc(runName(b.dataset.run)) + '<span class="seg-sub">' + esc(fmtWhen(r.recorded_at).time) + "</span>"; });
  }
  function renderSummary() {
    var r = run(), invs = r.invoices, paid = 0, nPaid = 0, rej = 0, held = 0, fraud = 0, fraudN = 0;
    invs.forEach(function (i) {
      if (i.payment && i.payment.status === "paid") { paid += i.payment.amount; nPaid++; }
      if (i.decision.status === "REJECTED") rej++;
      if (i.decision.status === "PENDING_HUMAN") held++;
      if (isFraudBlocked(i)) { fraud += i.total_usd || 0; fraudN++; }
    });
    $("showing").innerHTML = "Showing <b>" + esc(runName(MODE)) + "</b>, " + (SET === "extra" ? invs.length + " extra test invoices (added, not case data)" : SET === "critic" ? "extra invoice 2004 ($12,500, added, not case data) run on its own, so the critic loop runs" : "20 case invoices") + ", recorded " + esc(fmtWhen(r.recorded_at).full) + ". Same run as the report.";
    $("summary").innerHTML = card(money(paid), "paid · " + nPaid) + card(String(rej), "rejected") + card(String(held), "held") + card(money(fraud), "high-risk blocked · " + fraudN, "Rejected with risk score " + hr() + " or more");
    var o = DATA.runs[key(MODE === "offline" ? "live" : "offline", SET)], diff = [];
    if (o) r.invoices.forEach(function (i) { var j = o.invoices.find(function (x) { return x.file === i.file; }); if (j && j.decision.status !== i.decision.status) diff.push(invNumber(i.number)); });
    $("run-note").textContent = (MODE === "offline" ? "Offline: VP and critic are fixed rules, no API calls." : "Live: Grok reads every invoice (a cross-check against the parser), does the risk review, the VP and the critic, and writes every decision memo. The critic only reviews approvals over $10,000, near the limit or high risk. Live decisions can differ run to run even at temperature 0; hard rules run first, and Grok can only raise risk or hold, never pay what the rules block.") +
      (diff.length ? " Differs from the other run on " + diff.join(", ") + "." : o ? " Same outcomes as the other run." : "");
  }
  function card(big, cap, title) { return '<div class="sum"' + (title ? ' title="' + esc(title) + '"' : "") + '><div class="sum-big">' + esc(big) + '</div><div class="small muted">' + esc(cap) + "</div></div>"; }
  function renderInbox() {
    var html = run().invoices.filter(function (i) { return FILTER === "all" || i.decision.status === FILTER; }).map(function (i) {
      return '<li><button type="button" class="inv' + (i.file === SELECTED ? " on" : "") + '" data-file="' + esc(i.file) + '"' + (i.file === SELECTED ? ' aria-current="true"' : "") + ">" +
        '<span class="inv-main"><b>' + esc(invNumber(i.number)) + dupTag(i) + '</b><span class="small muted">' + (i.vendor ? esc(i.vendor) : '<span class="missing">Missing vendor</span>') + " · " + esc(i.file) + "</span></span>" +
        '<span class="inv-side"><span class="money">' + money(i.total_usd) + "</span>" + pill(i.decision.status) + "</span></button></li>";
    }).join("");
    $("inbox").innerHTML = html || '<li class="muted small pad">None in this run.</li>';
  }
  function renderDetail() {
    var inv = run().invoices.find(function (i) { return i.file === SELECTED; }) || run().invoices[0];
    SELECTED = inv.file; $("detail").innerHTML = detailHtml(inv, run());
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
    $("honesty").innerHTML = '<span class="dot" aria-hidden="true"></span><span><b>Replay, not a live call.</b> Real ' + esc(live.model) + " run recorded " + esc(w.full) + ". Every step comes from the committed trace. The system runs locally: <a href='" + README + "'>quickstart</a>.</span>";
    $("job-limit").textContent = whole(p.approval_threshold_usd) + " limit";
    var invs = live.invoices, fm = {};
    invs.forEach(function (i) { var f = (i.format || "?").toUpperCase(); fm[f] = (fm[f] || 0) + 1; });
    $("inbox-count").textContent = invs.length + " files";
    $("fmt-row").innerHTML = Object.keys(fm).sort(function (a, b) { return fm[b] - fm[a]; }).map(function (k) { return '<span class="fmt-chip">' + fm[k] + " " + esc(k) + "</span>"; }).join("");
    $("tiles").innerHTML = invs.map(function (i) { return '<li><button type="button" class="tile" data-src="' + esc(i.file) + '" title="See the original file"><span class="t-fmt">' + esc((i.format || "").toUpperCase()) + '</span><span class="t-name">' + esc(i.file.replace(/^invoice_/, "").replace(/\.[a-z]+$/, "")) + "</span></button></li>"; }).join("");
    var plan = schedule(live);
    $("go-note").textContent = "About " + fmtDur(Math.round(plan.total / 1000) * 1000) + " at 1x. The real run took " + fmtDur(live.duration_ms) + ".";
    $("go").disabled = false;
  }

  /* ---------- stage 2: playback ---------- */
  function schedule(r) {
    var evs = [], at = 0, prevReal = 0;
    r.invoices.forEach(function (inv, k) {
      at += INTRO; evs.push({ type: "start", inv: inv, k: k, at: at, real: inv.start_ms });
      inv.timeline.forEach(function (ev) {
        var real = inv.start_ms + ev.ms, gap = Math.max(0, real - prevReal), dwell = Math.max(MIN_STEP, gap / SCALE);
        at += dwell; prevReal = real;
        evs.push({ type: "ev", inv: inv, k: k, ev: ev, at: at, real: real, gap: gap, dwell: dwell });
      });
      at += OUTRO; evs.push({ type: "end", inv: inv, k: k, at: at, real: inv.start_ms + inv.duration_ms });
    });
    return { evs: evs, total: at };
  }
  function stageOf(ev) {
    if (ev.agent === "approval") return ev.step === "critic_review" ? "critic" : ev.step === "decide" ? "outcome" : "vp";
    if (ev.agent === "payment" || ev.agent === "hitl") return "outcome";
    return ev.agent;
  }
  function startRun(name) {
    if (!DATA || !DATA.runs[name]) return;
    var r = DATA.runs[name];
    if (P && P.raf) cancelAnimationFrame(P.raf);
    var plan = schedule(r);
    P = { r: r, evs: plan.evs, total: plan.total, T: 0, cur: 0, speed: P ? P.speed : 1, playing: true, done: 0, curInv: null, stage: {},
      tot: { paid: 0, nPaid: 0, rej: 0, held: 0, fraud: 0, nFraud: 0 }, real: 0, finished: false, last: 0, raf: 0 };
    $("run").hidden = false; $("report").hidden = true; closeInspector();
    $("run-eyebrow").textContent = "Replay · " + runLabel(r);
    $("run-h").textContent = isLive(r) ? "Grok is working" : "The rules are working";
    $("prog").setAttribute("aria-valuemax", r.invoices.length);
    $("speed-note").textContent = "1x = about " + fmtDur(Math.round(plan.total / 1000) * 1000) + " (real run took " + fmtDur(r.duration_ms) + ")";
    $("queue").innerHTML = r.invoices.map(function (inv, k) {
      return '<li><button type="button" class="q-item" data-q="' + k + '"><span class="q-num">' + (k + 1) + '</span><span class="q-main"><span class="q-file">' + esc(inv.file) + '</span><span class="small muted">' + esc(invNumber(inv.number)) + '</span></span><span class="q-st" id="qs-' + k + '"><span class="q-wait">Waiting</span></span></button></li>';
    }).join("");
    $("feed").innerHTML = ""; $("cur-head").innerHTML = ""; renderStepper();
    $("skip").disabled = false; $("pause").disabled = false; setPauseLabel();
    updateBar(); jump("run");
    P.last = performance.now(); P.raf = requestAnimationFrame(tick);
  }
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
        $("cur-head").innerHTML = '<div class="small muted">' + (k + 1) + " of " + P.r.invoices.length + " · " + esc(inv.file) + ' · <button type="button" class="linkish" data-src="' + esc(inv.file) + '">Original</button></div><div class="cur-title">' + esc(invNumber(inv.number)) + dupTag(inv) + '</div><div class="small muted">' + vendorHtml(inv.vendor) + " · " + money(inv.total_usd) + "</div>";
        $("feed").innerHTML = ""; renderStepper();
      }
      return;
    }
    if (e.type === "end") {
      P.done++; P.stage.complete = true;
      setQ(k, pill(inv.decision.status), "done");
      if (show) { renderStepper(); $("live-status").textContent = (k + 1) + " of " + P.r.invoices.length + ", " + inv.file + ": " + statusName(inv.decision.status) + "."; }
      return;
    }
    var ev = e.ev, st = stageOf(ev);
    Object.keys(P.stage).forEach(function (s) { if (P.stage[s] === "on") P.stage[s] = "done"; });
    P.stage[st] = "on";
    if (ev.step === "decide") {
      if (!inv.timeline.some(function (x) { return x.step === "critic_review"; })) P.stage.critic = "skipped";
      if (ev.detail.decided_by === "hard_rules" || ev.detail.decided_by === "hard_hold") { P.stage.vp = "skipped"; P.stage.critic = "skipped"; }
      var s = ev.detail.status;
      if (s === "REJECTED") { P.tot.rej++; if (isFraudBlocked(inv)) { P.tot.fraud += inv.total_usd || 0; P.tot.nFraud++; } }
      if (s === "PENDING_HUMAN") P.tot.held++;
    }
    if (ev.step === "paid") { P.tot.paid += ev.detail.amount || 0; P.tot.nPaid++; }
    if (show) { var feed = $("feed"); feed.insertAdjacentHTML("beforeend", stepHtml(ev, inv, P.r)); feed.scrollTop = feed.scrollHeight; renderStepper(); }
  }
  function setQ(k, html, cls) {
    var el = $("qs-" + k); if (!el) return;
    el.innerHTML = html;
    var b = el.closest(".q-item"); b.classList.remove("now", "done"); b.classList.add(cls);
    if (cls === "now") { var l = $("queue"); if (l.scrollHeight > l.clientHeight) l.scrollTop = b.parentNode.offsetTop - 60; }
  }
  function renderStepper() {
    var s = P ? P.stage : {};
    $("stepper").innerHTML = STAGES.map(function (x) {
      var v = s[x[0]] || (s.complete ? "skipped" : ""); if (v === "on" && s.complete) v = "done";
      return '<li class="stg ' + v + '" title="' + esc(x[2]) + '"' + (v === "on" ? ' aria-current="step"' : "") + ">" + x[1] + (v === "skipped" ? '<span class="sr-only"> (skipped)</span>' : v === "done" ? '<span class="sr-only"> (done)</span>' : "") + "</li>";
    }).join("");
  }
  function updateBar() {
    var n = P.r.invoices.length;
    $("prog-fill").style.width = (P.total ? Math.min(100, P.T / P.total * 100) : 0) + "%";
    $("prog").setAttribute("aria-valuenow", P.done);
    $("prog-label").textContent = P.done + " of " + n + " done";
    $("prog-eta").textContent = P.finished ? "Finished" : (P.playing ? "ETA " : "Paused · ") + fmtClock((P.total - P.T) / P.speed) + (P.playing ? "" : " left");
    $("prog-real").textContent = "About " + fmtClock(P.real) + " into the real run";
    var t = P.tot;
    $("totals").innerHTML = tcard(money(t.paid), "paid", "good") + tcard(String(t.rej), "rejected", "bad") + tcard(String(t.held), "held", "warn") + tcard(money(t.fraud), "high-risk blocked", "", "Rejected with risk score " + hr() + " or more");
    updateWaiting();
  }
  function tcard(big, cap, cls, title) { return '<div class="tot ' + cls + '"' + (title ? ' title="' + esc(title) + '"' : "") + '><span class="tot-big">' + esc(big) + '</span><span class="small muted">' + esc(cap) + "</span></div>"; }
  function updateWaiting() {
    var w = $("waiting"), nx = P.evs[P.cur];
    if (!P.finished && nx && nx.type === "ev" && isLive(P.r) && nx.gap > 1000 && (nx.ev.agent === "risk" || nx.ev.agent === "approval" || nx.ev.step === "llm_repair")) {
      var who = nx.ev.agent === "approval" ? "VP" : nx.ev.agent === "risk" ? "Risk agent" : "Ingest";
      var txt = who + " waiting on " + esc(P.r.model) + " · " + (nx.gap / 1000).toFixed(1) + " s recorded";
      if (w.dataset.t !== txt) { w.innerHTML = '<span class="spin" aria-hidden="true"></span><span>' + txt + '</span><span class="w-bar"><span id="w-fill"></span></span>'; w.dataset.t = txt; }
      $("w-fill").style.width = (Math.max(0, Math.min(1, 1 - (nx.at - P.T) / nx.dwell)) * 100) + "%";
      w.hidden = false;
    } else { w.hidden = true; w.dataset.t = ""; }
  }
  function setPauseLabel() { var b = $("pause"), paused = P && !P.playing; b.textContent = paused ? "Resume" : "Pause"; b.setAttribute("aria-pressed", paused ? "true" : "false"); }
  function skipToEnd() {
    if (!P || P.finished) return;
    var lastStart = -1;
    for (var i = P.evs.length - 1; i >= 0; i--) if (P.evs[i].type === "start") { lastStart = i; break; }
    while (P.cur < P.evs.length) { fire(P.evs[P.cur], P.cur >= lastStart); P.cur++; }
    P.T = P.total; finish(true);
  }
  function finish(scroll) {
    if (P.finished) return;
    P.finished = true; P.playing = false; updateBar();
    $("pause").disabled = true; $("skip").disabled = true; setPauseLabel();
    $("run-eyebrow").textContent = "Finished · " + runLabel(P.r);
    $("run-h").textContent = "All " + P.r.invoices.length + " handled";
    $("live-status").textContent = "Run complete. Report below.";
    REPORT = P.r.name.replace(/^extra_/, "");
    renderReport(); setRun(REPORT, "case"); renderAll();
    $("report").hidden = false;
    if (scroll) setTimeout(function () { jump("report"); }, REDUCED ? 0 : 450);
  }
  function jump(id) { var el = $(id); if (el) el.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" }); }
  function inspect(k) {
    if (!P) return;
    if (P.playing && !P.finished) { P.playing = false; setPauseLabel(); updateBar(); }
    var inv = P.r.invoices[k], reached = k < P.curInv || (k === P.curInv && P.stage.complete) || P.finished;
    $("insp-note").textContent = reached ? "Paused" : "Paused · not reached yet, showing its recorded result";
    $("insp-body").innerHTML = detailHtml(inv, P.r);
    document.querySelectorAll(".q-item.picked").forEach(function (x) { x.classList.remove("picked"); });
    var qb = document.querySelector('[data-q="' + k + '"]'); if (qb) qb.classList.add("picked");
    var box = $("inspector"), cardEl = box.closest(".feed-card");
    box.hidden = false; cardEl.classList.add("inspecting"); document.body.classList.add("sheet-open");
    box.scrollTop = 0; box.focus({ preventScroll: true });
    var navH = document.querySelector(".nav").offsetHeight;
    if (window.innerWidth > 900) {
      var top = cardEl.getBoundingClientRect().top;
      if (top < navH + 8 || top > window.innerHeight * 0.4) window.scrollTo({ top: window.scrollY + top - navH - 12, behavior: REDUCED ? "auto" : "smooth" });
    } else if (qb) {
      var sheetTop = box.getBoundingClientRect().top, qr = qb.getBoundingClientRect(), want = navH + Math.max(4, (sheetTop - navH - qr.height) / 2);
      if (qr.top < navH || qr.bottom > sheetTop) window.scrollTo({ top: window.scrollY + qr.top - want, behavior: "auto" });
    }
  }
  function closeInspector() {
    var box = $("inspector"); box.hidden = true;
    var c = box.closest(".feed-card"); if (c) c.classList.remove("inspecting");
    document.body.classList.remove("sheet-open");
    document.querySelectorAll(".q-item.picked").forEach(function (x) { x.classList.remove("picked"); });
  }

  /* ---------- stage 3: report ---------- */
  var CAT = [
    ["dup", "duplicate copies", function (i) { return !!flag(i, "DUPLICATE_INVOICE"); }],
    ["sup", "superseded by a revision", function (i) { return !!flag(i, "SUPERSEDED_BY_REVISION"); }],
    ["risk", "high risk, also failed hard rules", function (i) { return (i.risk.score || 0) >= hr() && hasBlock(i); }],
    ["stock", "not enough stock", function (i) { return blocks(i).some(function (c) { return c === "STOCK_EXCEEDED" || c === "ZERO_STOCK"; }); }],
    ["item", "items not in inventory", function (i) { return blocks(i).indexOf("UNKNOWN_ITEM") >= 0; }],
    ["data", "missing or invalid data", function (i) { return blocks(i).some(function (c) { return /^MISSING_|^NEGATIVE_|^INVALID_|UNREADABLE|PARSE/.test(c); }); }],
    ["math", "math does not add up", function (i) { return blocks(i).some(function (c) { return /MISMATCH/.test(c); }); }],
    ["vp", "rejected by the VP agent", function (i) { return !hasBlock(i); }],
    ["other", "other blocking flags", function () { return true; }]
  ];
  function catOf(i) { for (var c = 0; c < CAT.length; c++) if (CAT[c][2](i)) return CAT[c]; }
  function owners(inv) {
    var t = (inv.decision.conditions || []).concat(inv.decision.reasons || []).join(" "), o = [];
    if (/procurement/i.test(t)) o.push("Procurement"); if (/\bAP\b/.test(t)) o.push("AP");
    return o;
  }
  function invLine(i, right, extra) {
    return '<li><div class="r-row"><span><b>' + esc(invNumber(i.number)) + "</b>" + dupTag(i) + ' <span class="muted">' + vendorHtml(i.vendor) + '</span></span><span class="r-right">' + (right || money(i.total_usd)) + "</span></div>" +
      '<div class="r-sub small muted"><button type="button" class="linkish" data-open-file="' + esc(i.file) + '">' + esc(i.file) + "</button></div>" + (extra || "") + "</li>";
  }
  function statusRank(s) { return { APPROVED: 0, PENDING_HUMAN: 1, REJECTED: 2 }[s]; }
  function syncRepButtons() { document.querySelectorAll("[data-rep]").forEach(function (b) { b.classList.toggle("on", b.dataset.rep === REPORT); b.setAttribute("aria-pressed", b.dataset.rep === REPORT); }); }
  function renderReport() {
    var r = DATA.runs[REPORT], o = DATA.runs[REPORT === "live" ? "offline" : "live"], invs = r.invoices, n = invs.length, w = fmtWhen(r.recorded_at);
    syncRepButtons();
    var by = function (s) { return invs.filter(function (i) { return i.decision.status === s; }); };
    var paid = invs.filter(function (i) { return i.payment && i.payment.status === "paid"; }), rej = by("REJECTED"), held = by("PENDING_HUMAN"), appr = by("APPROVED");
    var paidSum = paid.reduce(function (a, i) { return a + i.payment.amount; }, 0);
    var hard = invs.filter(function (i) { return i.decision.decided_by === "hard_rules"; }).length;
    var hh = invs.filter(function (i) { return i.decision.decided_by === "hard_hold"; }).length;
    var reviewed = invs.filter(function (i) { return i.risk.llm && !i.risk.llm.error; }).length, tools = 0;
    invs.forEach(function (i) { i.timeline.forEach(function (e) { if (e.step === "tool_call") tools++; }); });
    var h = [];
    h.push('<p class="memo-note small muted">' + esc(runName(REPORT)) + " · recorded " + esc(w.full) + " · assembled from the trace; only the linking words are a template.</p>");
    h.push('<div class="st-cards"><div class="st approve"><b>' + appr.length + '</b><span>paid</span></div><div class="st reject"><b>' + rej.length + '</b><span>rejected</span></div><div class="st review"><b>' + held.length + '</b><span>need you</span></div><div class="st"><b>' + whole(paidSum) + "</b><span>paid out</span></div></div>");
    h.push('<section class="m-sec"><h3>What I did</h3><p>Read all ' + n + " files in " + fmtDur(r.duration_ms) + ". " + hard + " were settled by hard rules. " + (hh ? hh + " held by a hard hold rule, before the VP. " : "") + (isLive(r) ? (n - hard) + " got a Grok risk review (" + plural(tools, "tool call") + ") and " + (n - hard - hh) + " a VP decision." : (n - hard - hh) + " went through the rules VP" + (invs.some(function (i) { return i.decision.critique_rounds; }) ? " and critic" : "") + ".") + "</p></section>");

    var groups = {}, order = [];
    rej.forEach(function (i) { var c = catOf(i); if (!groups[c[0]]) { groups[c[0]] = { c: c, items: [] }; order.push(c[0]); } groups[c[0]].items.push(i); });
    order.sort(function (a, b) { return CAT.findIndex(function (c) { return c[0] === a; }) - CAT.findIndex(function (c) { return c[0] === b; }); });
    h.push('<section class="m-sec"><h3>Rejected ' + rej.length + "</h3>" + order.map(function (k) {
      var g = groups[k];
      return more('<span class="grp-n">' + g.items.length + "</span> " + esc(g.c[1]), '<ul class="r-list">' + g.items.map(function (i) { return invLine(i, null, '<div class="r-why small">' + esc((i.decision.reasons || []).join(" · ")) + "</div>"); }).join("") + "</ul>");
    }).join("") + "</section>");

    h.push('<section class="m-sec"><h3>Paid ' + whole(paidSum) + "</h3>" + (paid.length ? '<ul class="r-list">' + paid.map(function (i) {
      return invLine(i, money(i.payment.amount), (i.decision.conditions || []).length ? more("VP conditions", list(i.decision.conditions)) : "");
    }).join("") + "</ul>" : "<p>Nothing was paid.</p>") + "</section>");

    var hi = rej.filter(isFraudBlocked), hiSum = hi.reduce(function (a, i) { return a + (i.total_usd || 0); }, 0);
    h.push('<section class="m-sec"><h3>Blocked ' + whole(hiSum) + ' <span class="muted h-sub">high risk, score ' + hr() + "+</span></h3>" + (hi.length ? '<ul class="r-list">' + hi.map(function (i) {
      return invLine(i, money(i.total_usd), more("Risk " + esc(i.risk.score) + " · signals", list((i.risk.signals || []).map(function (s) { return s.reason; })) + '<p class="small muted">Stopped by ' + esc(blocks(i).join(", ")) + ".</p>"));
    }).join("") + "</ul>" : "<p>No high-risk invoices.</p>") + "</section>");

    h.push('<section class="m-sec"><h3>Need you ' + held.length + "</h3>" + (held.length ? held.map(function (i) {
      var ow = owners(i), crit = i.timeline.filter(function (e) { return e.step === "critic_review"; });
      return '<div class="hold"><div class="r-row"><span><b>' + esc(invNumber(i.number)) + '</b> <span class="muted">' + vendorHtml(i.vendor) + '</span></span><span class="r-right">' + money(i.total_usd) + "</span></div>" +
        '<div class="r-sub small muted">' + esc(riskText(i.risk)) + " · " + (ow.length ? esc(ow.join(" and ")) + " named by the VP" : "Owner: AP reviewer") + ' · <button type="button" class="linkish" data-open-file="' + esc(i.file) + '">' + esc(i.file) + "</button></div>" +
        '<div class="sub-h">Next steps</div>' + ((i.decision.conditions || []).length ? list(i.decision.conditions) : '<p class="small muted">None recorded.</p>') +
        more("Why I held it", list(i.decision.reasons) + (crit.length ? "<div class='sub-h'>Critic</div>" + list(crit.map(function (c) { return "Round " + c.detail.round + ": " + c.detail.reason; })) : "")) +
        more("Review command", reviewCmd(i)) + "</div>";
    }).join("") : "<p>Nothing is waiting.</p>") + "</section>");

    var codes = {};
    var pastDue = invs.filter(function (i) { return flag(i, "PAST_DUE"); });
    invs.forEach(function (i) { i.flags.forEach(function (f) { if (f.severity === "info" || f.code === "PAST_DUE") return; var c = codes[f.code] || (codes[f.code] = { sev: f.severity, files: [], msg: f.message }); if (c.files.indexOf(i.file) < 0) c.files.push(i.file); if (f.severity === "block") c.sev = "block"; }); });
    var ck = Object.keys(codes).sort(function (a, b) { return (codes[a].sev === "block" ? 0 : 1) - (codes[b].sev === "block" ? 0 : 1) || codes[b].files.length - codes[a].files.length; });
    var fixes = {};
    invs.forEach(function (i) { i.flags.forEach(function (f) { if (/OCR_CORRECTED|SKU_NORMALIZED|LINES_AGGREGATED/.test(f.code)) { fixes[f.code] = fixes[f.code] || []; if (fixes[f.code].indexOf(i.file) < 0) fixes[f.code].push(i.file); } }); });
    h.push('<section class="m-sec"><h3>Data errors found</h3><p>' + plural(ck.length, "kind") + " of error or warning. Most common: " + ck.slice(0, 3).map(function (c) { return "<code>" + esc(c) + "</code> (" + codes[c].files.length + ")"; }).join(", ") + ".</p>" + more("Show all", '<ul class="fl">' + ck.map(function (c) {
      var x = codes[c]; return '<li><span class="sev ' + x.sev + '" title="' + esc(SEV[x.sev]) + '">' + x.sev + '</span><span><code>' + esc(c) + "</code> · " + plural(x.files.length, "file") + '<div class="small muted">' + esc(x.msg) + "</div></span></li>";
    }).join("") + "</ul>" + (pastDue.length ? '<p class="small muted"><code>PAST_DUE</code>: ' + pastDue.length + " of " + invs.length + " were already past their due date when this run processed them. That warning is for people only; the agents do not see it, so it changes no decision.</p>" : "") + (Object.keys(fixes).length ? '<p class="small muted">Fixed automatically: ' + Object.keys(fixes).map(function (c) { return "<code>" + esc(c) + "</code> (" + fixes[c].length + ")"; }).join(", ") + ".</p>" : "")) + "</section>");

    var rec = [];
    invs.filter(function (i) { return flag(i, "VENDOR_RENAMED") && i.decision.status !== "REJECTED"; }).forEach(function (i) { var f = flag(i, "VENDOR_RENAMED"); rec.push("Call " + f.evidence.former + " on its contact on file to confirm the rename to " + f.evidence.vendor + ", then record the alias or reject " + invNumber(i.number) + "."); });
    var noAddr = [];
    invs.forEach(function (i) { i.timeline.forEach(function (e) { var d = e.detail; if (e.step === "tool_call" && d.tool === "lookup_vendor" && d.result && d.result.found && !d.result.address && noAddr.indexOf(d.result.name) < 0) noAddr.push(d.result.name); }); });
    if (noAddr.length) rec.push("Add vendor master addresses for " + plural(noAddr.length, "vendor") + " (" + noAddr.join("; ") + ").");
    var dupN = invs.filter(function (i) { return flag(i, "DUPLICATE_INVOICE"); });
    if (dupN.length) rec.push(plural(dupN.length, "invoice") + " arrived twice in different formats. Ask vendors for one format.");
    var unk = []; invs.forEach(function (i) { i.flags.forEach(function (f) { if (f.code === "UNKNOWN_ITEM") { var m = /'([^']+)'/.exec(f.message); if (m && unk.indexOf(m[1]) < 0) unk.push(m[1]); } }); });
    if (unk.length) rec.push("Check whether " + unk.join(", ") + " are new catalog items or vendor errors.");
    var stockN = rej.filter(function (i) { return blocks(i).indexOf("STOCK_EXCEEDED") >= 0 && !flag(i, "DUPLICATE_INVOICE"); });
    if (stockN.length) rec.push("Refresh the inventory table if it is stale, then re-run the " + plural(stockN.length, "stock rejection") + ".");
    var fx = invs.filter(function (i) { return flag(i, "CURRENCY_CONVERTED"); });
    if (fx.length) rec.push("Agree a " + fx.map(function (i) { return i.currency; }).filter(function (v, k, a) { return a.indexOf(v) === k; }).join("/") + " price list with " + fx.map(function (i) { return i.vendor; }).join(", ") + ". The run used a mock rate.");
    var diffs = o ? invs.map(function (i) { var j = o.invoices.find(function (x) { return x.file === i.file; }); return j && j.decision.status !== i.decision.status ? [i, j] : null; }).filter(Boolean) : [];
    if (diffs.length) {
      var cautious = diffs.every(function (p) { var lv = isLive(r) ? p[0] : p[1], of = isLive(r) ? p[1] : p[0]; return statusRank(lv.decision.status) > statusRank(of.decision.status); });
      rec.push("The " + runLabel(o) + " differs on " + plural(diffs.length, "invoice") + "." + (cautious ? " Grok was the more cautious each time." : ""));
    }
    h.push('<section class="m-sec"><h3>Recommendations</h3><ol class="recs">' + rec.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ol></section>");

    if (o) h.push('<section class="m-sec">' + more("Compare with the " + esc(runLabel(o)) + " (" + diffs.length + " differ)", '<div class="tbl-wrap"><table class="cmp"><thead><tr><th>Invoice</th><th>' + esc(runName(REPORT)) + "</th><th>" + esc(runName(REPORT === "live" ? "offline" : "live")) + "</th></tr></thead><tbody>" +
      invs.map(function (i) { var j = o.invoices.find(function (x) { return x.file === i.file; }); return "<tr" + (j && j.decision.status !== i.decision.status ? ' class="diff"' : "") + "><td>" + esc(invNumber(i.number)) + dupTag(i) + '<div class="small muted">' + esc(i.file) + "</div></td><td>" + pill(i.decision.status) + "</td><td>" + (j ? pill(j.decision.status) : "-") + "</td></tr>"; }).join("") + "</tbody></table></div>") + "</section>");
    $("memo").innerHTML = h.join("");
  }

  /* ---------- events ---------- */
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (t.closest("#go")) { startRun("live"); return; }
    if (t.closest("#go-offline")) { startRun("offline"); return; }
    if (t.closest("#replay")) { startRun(REPORT); return; }
    if (t.closest("#pause")) { if (P && !P.finished) { P.playing = !P.playing; P.last = performance.now(); setPauseLabel(); updateBar(); if (P.playing) closeInspector(); } return; }
    if (t.closest("#skip")) { skipToEnd(); return; }
    var src = t.closest("[data-src]"); if (src) { openSource(src.dataset.src); return; }
    if (t.closest("#src-close")) { $("src-dialog").close(); return; }
    if (t === $("src-dialog")) { $("src-dialog").close(); return; }
    var sp = t.closest("[data-speed]");
    if (sp) { if (P) P.speed = +sp.dataset.speed; document.querySelectorAll("[data-speed]").forEach(function (x) { x.classList.toggle("on", x === sp); x.setAttribute("aria-pressed", x === sp); }); if (P) updateBar(); return; }
    var q = t.closest("[data-q]"); if (q) { inspect(+q.dataset.q); return; }
    if (t.closest("#insp-close")) { var k0 = document.querySelector(".q-item.picked"); closeInspector(); if (P && !P.finished) { P.playing = true; P.last = performance.now(); setPauseLabel(); updateBar(); } if (k0) k0.focus({ preventScroll: true }); return; }
    var rp = t.closest("[data-rep]"); if (rp) { REPORT = rp.dataset.rep; renderReport(); setRun(REPORT); renderAll(); return; }
    var of = t.closest("[data-open-file]"); if (of) { setRun(REPORT, "case"); SELECTED = of.dataset.openFile; renderAll(); jump("demo"); return; }
    var b = t.closest("[data-run]");
    if (b) { setRun(b.dataset.run); renderAll(); if (DATA.runs[b.dataset.run] && REPORT !== b.dataset.run) { REPORT = b.dataset.run; if (!$("report").hidden) renderReport(); else syncRepButtons(); } return; }
    var st = t.closest("[data-set]"); if (st) { setRun(MODE, st.dataset.set); renderAll(); return; }
    var c = t.closest("#filters .chip");
    if (c) { FILTER = c.dataset.f; document.querySelectorAll("#filters .chip").forEach(function (x) { x.classList.toggle("on", x === c); x.setAttribute("aria-pressed", x === c); }); renderInbox(); return; }
    var i = t.closest(".inv");
    if (i) { SELECTED = i.dataset.file; renderInbox(); renderDetail(); var dt = $("detail"); if (window.innerWidth < 900) dt.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth" }); else if (dt.getBoundingClientRect().top < 0) window.scrollTo({ top: window.scrollY + dt.getBoundingClientRect().top - 80 }); return; }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("inspector").hidden) $("insp-close").click(); });

  function frac(a, b) { return a + " of " + b; }
  function evCard(big, cap, detail) { return '<div class="sum"><div class="sum-big">' + esc(big) + '</div><div class="small muted">' + esc(cap) + "</div>" + (detail ? '<div class="small">' + esc(detail) + "</div>" : "") + "</div>"; }
  function renderEvals(E) {
    var cards = [], x = E.extraction || {}, ad = E.adversarial || {}, sr = E.separate_run, sl = E.separate_run_live, cr = E.cache_repeatability;
    var ag = (E.agreement || []).find(function (a) { return /eval run, samples/.test(a.label); });
    var cl = E.cost_latency && E.cost_latency.batches && E.cost_latency.batches.samples;
    if (x.offline) cards.push(evCard(frac(x.offline.overall.correct, x.offline.overall.scored), "fields extracted correctly, offline parsers",
      x.live_pipeline ? "Live pipeline: " + frac(x.live_pipeline.overall.correct, x.live_pipeline.overall.scored) + "." : ""));
    if (ad.offline) cards.push(evCard(frac(ad.offline.caught, ad.offline.total), "adversarial invoices caught, offline",
      ad.live ? "Live " + E.model + ": " + frac(ad.live.caught, ad.live.total) + ". Caught = not approved and not paid." : ""));
    if (sr || sl) cards.push(evCard(frac((sl || sr).caught, (sl || sr).total), "caught as a separate later run" + (sl ? ", live" : ""),
      (sr ? "Offline: " + frac(sr.caught, sr.total) + ". " : "") + (sl ? "Live once: " + sl.calls + " Grok calls, $" + sl.billed_usd + ", " + Math.round(sl.wall_s) + " s. " : "") +
      (sr && sr.duplicate_3006 ? "3006, a copy of INV-1001 under a new number, is " + sr.duplicate_3006.decision.toLowerCase() + " by the hard rules." : "")));
    if (cr) cards.push(evCard(frac(cr.identical, cr.invoices), "identical on a live re-run with the decision cache",
      "First run " + cr.first.api_calls + " API calls ($" + cr.first.billed_usd + ", " + Math.round(cr.first.span_s) + " s); re-run " + cr.second.api_calls + " calls, " + cr.second.span_s + " s."));
    if (ag) cards.push(evCard(frac(ag.agree, ag.invoices), "live decisions that match the offline rules",
      ag.disagreement_routing ? (function (d) { var n = ag.invoices - ag.agree, lv = (d.paid_on_one_side || []).filter(function (p) { return p.paid_by === "live"; }).length;
        return n + (n === 1 ? " differs" : " differ") + "; disagreement routing sends " + (d.to_human === 1 ? "it" : "them") + " to a person. Live paid " + (lv ? lv + " invoice(s)" : "nothing") + " the rules would not."; })(ag.disagreement_routing) : ""));
    var un = E.unseen || {};
    if (un.offline) cards.push(evCard(frac(un.offline.total - un.offline.rejected, un.offline.total), "unseen layouts not rejected offline (" + un.offline.held + " held for a person)",
      un.live ? "Live: " + frac(un.live.read_correctly, un.live.total) + " read correctly by Grok, " + frac(un.live.paid, un.live.total) + " paid, " + un.live.held + " held, " + un.live.rejected + " rejected. Layouts the parsers were never tuned on." : "Layouts the parsers were never tuned on."));
    if (cl) cards.push(evCard("$" + cl.billed_usd, "Grok cost for the 20 samples, live",
      cl.calls + " calls, " + cl.latency_mean_s + " s per invoice on average over all 20. Offline costs $0."));
    $("ev-cards").innerHTML = cards.join("");
    $("ev-note").textContent = "From evals/results, exported to /data/evals.json. Offline " + (E.offline_generated_at || "") + (E.live_generated_at ? "; live " + E.live_generated_at : "") + ".";
    $("ev-foot").innerHTML = 'Details, traces and the live/offline disagreements: <a href="https://github.com/adamtpang/galatiq.vercel.app/tree/main/evals/results">evals/results on GitHub</a>.';
  }
  fetch("/data/evals.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(renderEvals).catch(function () { $("ev-note").textContent = "Could not load eval results."; });

  Promise.all([
    fetch("/data/demo.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }),
    fetch("/data/sources.json").then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; })
  ]).then(function (res) {
    DATA = res[0]; SRC = res[1] || {};
    var qs = new URLSearchParams(location.search), want = qs.get("inv");
    setRun("live", "case");
    setRun(qs.get("run") || "live", qs.get("set") || "case");
    if (DATA.runs[MODE]) REPORT = MODE;
    if (want && run().invoices.some(function (i) { return i.file === want; })) SELECTED = want;
    renderOverview(); renderAll();
    if (location.hash === "#report") { startRun("live"); skipToEnd(); }
  }).catch(function () { $("honesty").textContent = "Could not load run data."; });
})();
