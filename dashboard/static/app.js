"use strict";
const TABS = ["Flow", "Overview", "Optimized code", "Passes", "Digital Twin", "Insights", "Copilot"];
const EXT = {python: "py", c: "c", cpp: "cpp", java: "java"};
const state = {data: null, tab: "Flow", flowSel: 0, flowTimer: null, session: null, samples: {}, chat: [], llm: {enabled: false, model: ""}, seq: 0, timer: null, lastAnalysed: ""};
const $ = (id) => document.getElementById(id);

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  Object.keys(props || {}).forEach((k) => {
    const v = props[k];
    if (k === "text") node.textContent = v;
    else if (k === "class") node.className = v;
    else if (k === "value") node.value = v;
    else if (k === "checked") node.checked = !!v;
    else if (k === "disabled") node.disabled = !!v;
    else if (k.slice(0, 2) === "on") node[k] = v;
    else node.setAttribute(k, v);
  });
  kids.forEach((c) => { if (c !== null && c !== undefined && c !== false) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
  return node;
}
function table(headers, rows) {
  const t = el("table"), head = el("tr");
  headers.forEach((h) => head.appendChild(el("th", {text: h})));
  t.appendChild(head);
  rows.forEach((r) => {
    const tr = el("tr");
    r.forEach((cell) => { const td = el("td"); if (cell instanceof Node) td.appendChild(cell); else td.textContent = String(cell === null || cell === undefined ? "" : cell); tr.appendChild(td); });
    t.appendChild(tr);
  });
  const wrap = el("div", {style: "overflow:auto"}); wrap.appendChild(t); return wrap;
}
function bar(value, max, cls) {
  const w = max > 0 ? Math.max(2, Math.round(100 * value / max)) : 2;
  return el("span", {"class": "barwrap"}, el("span", {"class": "bar " + (cls || ""), style: "width:" + Math.round(w * 1.1) + "px"}), String(value));
}
function toast(msg, kind) {
  const t = el("div", {"class": "toast " + (kind || ""), text: msg}); $("toasts").appendChild(t);
  setTimeout(() => { if (t.parentNode) t.parentNode.removeChild(t); }, 3800);
}
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const j = await r.json();
  if (!r.ok) { const e = new Error(j.error || r.statusText); e.line = j.line; e.advice = j.advice; throw e; }
  return j;
}
function copyText(text) {
  const done = () => toast("Copied to clipboard", "ok");
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => toast("Copy failed", "bad"));
  else { const ta = el("textarea", {value: text}); document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); done(); } catch (e) { toast("Copy failed", "bad"); } ta.remove(); }
}
function download(name, text) {
  const a = el("a", {href: URL.createObjectURL(new Blob([text], {type: "text/plain"})), download: name});
  document.body.appendChild(a); a.click(); a.remove();
}
function setTheme(t) { document.documentElement.setAttribute("data-theme", t); try { localStorage.setItem("ct-theme", t); } catch (e) {} $("themeBtn").textContent = t === "dark" ? "Light mode" : "Dark mode"; }

/* ------------------------------------------------------------------ editor */
function detectLanguage(code) {
  if (/^\s*def\s+\w+\s*\(.*\)\s*(->\s*[\w\[\], ]+)?\s*:/m.test(code)) return "python";
  if (/#include|\bstd::|\busing\s+namespace\b|\bcout\b/.test(code)) return /std::|cout|using\s+namespace|\bclass\b|template\s*</.test(code) ? "cpp" : "c";
  if (/\bclass\s+\w+/.test(code) && /\b(public|private|static|void|int|double|boolean)\b/.test(code)) return "java";
  return /[{};]/.test(code) ? "c" : "python";
}
function currentLanguage() { const v = $("lang").value; return v === "auto" ? detectLanguage($("code").value) : v; }
function updateGutter(errLine) {
  const g = $("gutter"), n = Math.min($("code").value.split("\n").length, 3000);
  g.textContent = "";
  for (let i = 1; i <= n; i++) g.appendChild(el("div", {"class": i === errLine ? "err" : "", text: String(i)}));
  g.scrollTop = $("code").scrollTop;
}
function showError(msg, line) {
  const b = $("errbox"); b.hidden = !msg; b.textContent = msg ? msg : "";
  updateGutter(line || 0);
}
function loadText(text, name) {
  $("code").value = text; showError(""); updateGutter();
  if (name) { const e = (name.split(".").pop() || "").toLowerCase(); const m = {py: "python", c: "c", h: "c", cpp: "cpp", cc: "cpp", cxx: "cpp", hpp: "cpp", java: "java"}[e]; $("lang").value = m || "auto"; }
  $("func").textContent = ""; $("func").appendChild(el("option", {value: "", text: "first function"}));
}
function readFile(file) {
  if (!file) return;
  if (file.size > 200000) { toast("That file is too large (200 KB limit)", "bad"); return; }
  const fr = new FileReader(); fr.onload = () => { loadText(String(fr.result), file.name); toast("Loaded " + file.name, "ok"); analyze(); }; fr.readAsText(file);
}

/* ------------------------------------------------------------------ rendering */
function renderStats() {
  const box = $("stats"), d = state.data;
  box.textContent = ""; box.hidden = !d;
  if (!d) return;
  const o = d.optimized, v = d.optimization.validation;
  const card = (t, big, small, cls) => el("div", {"class": "stat"}, el("b", {text: t}), el("span", {"class": cls || "", text: big}), el("small", {text: small || ""}));
  box.appendChild(card("Predicted cost", Math.round(o.cost_before) + " \u2192 " + Math.round(o.cost_after), "work units per call"));
  box.appendChild(card("Saving", o.saving_pct + "%", o.strategy, o.saving_pct > 0 ? "ok" : "mute"));
  box.appendChild(card("Behaviour check", v.passed ? "PASSED" : "FAILED", v.tests_conclusive + "/" + v.tests_total + " differential tests", v.passed ? "ok" : "bad"));
  box.appendChild(card("Transformations", String(d.optimization.changes.length), d.function + "() \u00b7 " + d.language));
}
function renderAlerts() {
  const box = $("alerts"); box.textContent = "";
  const a = state.data ? state.data.alerts : [];
  if (!a.length) { box.appendChild(el("span", {"class": "mute", text: state.data ? "Nothing stands out - nice code." : "Analyze some code first."})); return; }
  a.forEach((m) => box.appendChild(el("div", {"class": "alert", text: m})));
}
function renderTabs() {
  const box = $("tabs"); box.textContent = "";
  TABS.forEach((t) => box.appendChild(el("button", {"class": "tab" + (t === state.tab ? " on" : ""), text: t, onclick: () => { state.tab = t; renderTabs(); renderPane(); }})));
}
function stage(title, text, cls) { return el("div", {"class": "stage " + (cls || "")}, el("b", {text: title}), el("span", {text: text})); }

/* ------------------------------------------------------------------ flow diagram */
const SVGNS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, text) {
  const n = document.createElementNS(SVGNS, tag);
  Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, attrs[k]));
  if (text !== undefined) n.textContent = text;
  return n;
}
function flowNodes(d) {
  const f = d.features, o = d.optimization, v = o.validation, rec = d.twin.recommendation, sel = d.selection.filter((s) => s.selected);
  const nch = o.changes.length, sv = d.optimized.saving_pct;
  return [
    {title: "Your code", sub: d.language.toUpperCase() + " \u00b7 " + d.line_count + " lines", tab: null,
     what: "The source you pasted. CodeTune only reads it - your program is never run natively, only simulated by CodeTune's own interpreter.",
     here: "Analysing " + d.function + "()" + (d.functions.length > 1 ? " (also found: " + d.functions.filter((n) => n !== d.function).join(", ") + ")" : "") + "."},
    {title: "Parse \u2192 IR", sub: d.functions.length + " function" + (d.functions.length === 1 ? "" : "s"), tab: "Overview",
     what: "A parser (tree-sitter) turns the text into a syntax tree. It is then translated into ONE common intermediate representation (IR), so the same optimizer works for Python, C, C++ and Java.",
     here: "Open the Overview tab to see the common IR generated from your " + d.language + " code."},
    {title: "Analyze", sub: f.loop_count + " loops \u00b7 " + f.branch_count + " branches", tab: "Overview",
     what: "Static analysis measures the code: loops, branches, constants, expensive operations. These numbers decide which optimizations are worth trying.",
     here: f.loop_count + " loop(s), " + f.branch_count + " branch(es), " + f.constant_count + " constant(s) found."},
    {title: "Select passes", sub: sel.length + " of " + d.selection.length + " chosen", tab: "Passes",
     what: "A rule-based selector (plus an optional machine-learning selector) decides which optimization passes to run, with a reason for each.", here: "chips", chips: d.selection},
    {title: "Optimize", sub: nch + " change" + (nch === 1 ? "" : "s"), tab: "Optimized code",
     what: "The chosen passes rewrite the IR repeatedly until nothing changes: constant propagation, constant folding, strength reduction (e.g. x*8 \u2192 x<<3) and dead-code elimination.",
     here: nch ? "counts" : "No safe rewrite was possible, so the code is unchanged.", counts: o.change_counts},
    {title: "Validate", sub: v.passed ? "PASSED" : "FAILED", status: v.passed ? "ok" : "bad", tab: "Passes",
     what: "The original and optimized code are run on boundary and random inputs; their results must match. If any test differs, the optimization is rejected.",
     here: v.tests_conclusive + " of " + v.tests_total + " differential tests were conclusive, " + v.mismatches.length + " mismatch(es)."},
    {title: "Digital Twin", sub: rec ? rec.strategy : "-", tab: "Digital Twin",
     what: "A cost model predicts how expensive each optimization strategy is, compares the prediction with the measured cost, and recommends the best valid one.",
     here: rec ? "Recommended: " + rec.strategy + " - " + rec.reason : "No strategy beat the original.", twin: true},
    {title: "Result", sub: (sv > 0 ? "-" : "") + sv + "% cost", status: sv > 0 ? "ok" : "", tab: "Optimized code",
     what: "The verified, explained, optimized code you can copy or download.",
     here: "Predicted cost " + d.optimized.cost_before + " \u2192 " + d.optimized.cost_after + " (" + sv + "% lower).", result: true},
  ];
}
function flowDetail(box, d, n, idx) {
  box.textContent = "";
  box.appendChild(el("h3", {text: (idx + 1) + ". " + n.title}));
  box.appendChild(el("p", {}, el("b", {text: "What happens: "}), n.what));
  if (n.here === "chips") {
    box.appendChild(el("p", {}, el("b", {text: "In your code: "}), "green = will run, grey = skipped (hover for the reason)."));
    const row = el("div", {"class": "chips"});
    n.chips.forEach((s) => row.appendChild(el("span", {"class": "chip " + (s.selected ? "on" : "off"), title: s.reason, text: s.pass + (s.selected ? "  \u2713" : "  \u2013")})));
    box.appendChild(row);
  } else if (n.here === "counts") {
    box.appendChild(el("p", {}, el("b", {text: "In your code: "}), "transformations applied per pass:"));
    const row = el("div", {"class": "chips"});
    Object.keys(n.counts).forEach((p) => row.appendChild(el("span", {"class": "chip on", text: p + " \u00d7 " + n.counts[p]})));
    box.appendChild(row);
  } else box.appendChild(el("p", {}, el("b", {text: "In your code: "}), n.here));
  if (n.twin) {
    const rows = d.twin.strategies.filter((s) => s.predicted_cost !== null), top = Math.max(1, d.twin.baseline.predicted_cost, ...rows.map((s) => s.predicted_cost));
    rows.forEach((s) => box.appendChild(el("div", {"class": "row"}, el("span", {style: "width:9rem", text: s.strategy}), bar(s.predicted_cost, top, !s.valid ? "bad" : (d.twin.recommendation && s.strategy === d.twin.recommendation.strategy ? "best" : "base")))));
  }
  if (n.result) {
    const top = Math.max(1, d.optimized.cost_before, d.optimized.cost_after);
    box.appendChild(el("div", {"class": "row"}, el("span", {style: "width:5rem", text: "before"}), bar(d.optimized.cost_before, top, "base")));
    box.appendChild(el("div", {"class": "row"}, el("span", {style: "width:5rem", text: "after"}), bar(d.optimized.cost_after, top, "best")));
  }
  if (n.tab) box.appendChild(el("div", {"class": "row"}, el("button", {"class": "primary", text: "Open the " + n.tab + " tab \u2192", onclick: () => { state.tab = n.tab; renderTabs(); renderPane(); }})));
}
function renderFlow(pane, d) {
  const nodes = flowNodes(d), W = 112, H = 78, G = 24, Y = 16;
  const root = svg("svg", {viewBox: "0 0 " + (nodes.length * (W + G) - G) + " " + (H + 2 * Y), "class": "flowsvg", role: "img", "aria-label": "CodeTune pipeline"});
  const defs = svg("defs"), mk = svg("marker", {id: "arr", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse"});
  mk.appendChild(svg("path", {d: "M0 0L10 5L0 10z", "class": "arrowhead"})); defs.appendChild(mk); root.appendChild(defs);
  const arrows = [], boxes = [], detail = el("div", {"class": "flowdetail"});
  function select(i) { state.flowSel = i; boxes.forEach((b, j) => b.setAttribute("class", "fnode " + (nodes[j].status || "") + (j === i ? " sel" : "") + (j <= i ? " reached" : "")));
    arrows.forEach((a, j) => a.setAttribute("class", "farrow" + (j < i ? " lit" : ""))); flowDetail(detail, d, nodes[i], i); }
  nodes.forEach((n, i) => {
    const x = i * (W + G);
    if (i) { const a = svg("line", {x1: x - G + 2, y1: Y + H / 2, x2: x - 2, y2: Y + H / 2, "marker-end": "url(#arr)", "class": "farrow"}); arrows.push(a); root.appendChild(a); }
    const g = svg("g", {"class": "fnode", tabindex: "0", role: "button", "aria-label": n.title}); g.style.cursor = "pointer";
    g.appendChild(svg("rect", {x: x, y: Y, width: W, height: H, rx: 12}));
    g.appendChild(svg("text", {x: x + W / 2, y: Y + 18, "class": "fnum"}, String(i + 1)));
    g.appendChild(svg("text", {x: x + W / 2, y: Y + 40, "class": "ftitle"}, n.title));
    g.appendChild(svg("text", {x: x + W / 2, y: Y + 60, "class": "fsub"}, n.sub.length > 17 ? n.sub.slice(0, 16) + "\u2026" : n.sub));
    g.addEventListener("click", () => { stopFlow(); select(i); });
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); stopFlow(); select(i); } });
    boxes.push(g); root.appendChild(g);
  });
  const play = el("button", {text: "\u25b6 Play the pipeline", onclick: () => {
    if (state.flowTimer) { stopFlow(); return; }
    let i = 0; select(0); play.textContent = "\u25a0 Stop";
    state.flowTimer = setInterval(() => { i++; if (i >= nodes.length) { stopFlow(); return; } select(i); }, 900); }});
  function stopFlow() { if (state.flowTimer) { clearInterval(state.flowTimer); state.flowTimer = null; } play.textContent = "\u25b6 Play the pipeline"; }
  pane.appendChild(el("div", {"class": "row"}, el("h3", {text: "How CodeTune processed your code", style: "margin:0"}), el("span", {"class": "grow"}), play));
  pane.appendChild(el("p", {"class": "mute", text: "Click any box to see what that stage did to YOUR code, or press Play to watch the whole pipeline."}));
  pane.appendChild(el("div", {style: "overflow-x:auto"}, el("div", {style: "min-width:900px"}, root)));
  pane.appendChild(detail); select(Math.min(state.flowSel, nodes.length - 1));
}

function renderOverview(pane, d) {
  const f = d.features, v = d.optimization.validation, rec = d.twin.recommendation;
  const selected = d.selection.filter((s) => s.selected).length;
  pane.appendChild(el("div", {"class": "pipe"},
    stage("1  Front-end", d.line_count + " lines \u2192 IR (" + d.functions.length + " function" + (d.functions.length === 1 ? "" : "s") + ")"),
    stage("2  Features", f.loop_count + " loops, " + f.branch_count + " branches, " + f.constant_count + " constants"),
    stage("3  Selection", selected + " of " + d.selection.length + " passes chosen"),
    stage("4  Transform", d.optimization.changes.length + " transformations"),
    stage("5  Validation", v.passed ? "PASSED " + v.tests_conclusive + "/" + v.tests_total : "FAILED", v.passed ? "ok" : "bad"),
    stage("6  Digital Twin", rec ? rec.strategy + " (-" + rec.saving_pct + "%)" : "-")));
  const det = el("details", {}, el("summary", {text: "Common IR (identical for every source language)"}), el("pre", {text: d.ir}));
  pane.appendChild(det);
  pane.appendChild(el("h3", {text: "Static features"}));
  pane.appendChild(table(["feature", "value"], Object.keys(f).filter((k) => k !== "function_name").map((k) => [k, f[k]])));
}

function renderOptimized(pane, d) {
  const o = d.optimized, ext = EXT[d.language] || "txt";
  pane.appendChild(el("div", {"class": "rec"}, el("b", {text: o.saving_pct > 0 ? "Verified faster version: " : "Already efficient: "}),
    o.saving_pct > 0 ? o.saving_pct + "% lower predicted cost (" + o.strategy + "). Same results as your original on boundary and random test inputs."
                     : "no safe rewrite lowers the cost, so the code is unchanged."));
  pane.appendChild(el("div", {"class": "row"}, el("button", {"class": "primary", text: "Copy optimized code", onclick: () => copyText(o.code)}),
    el("button", {text: "Download", onclick: () => download("optimized." + ext, o.code)}),
    el("span", {"class": "mute", text: "for loops appear as the equivalent while loops"})));
  pane.appendChild(el("div", {"class": "two"}, el("div", {}, el("h3", {text: "Your code (normalised)"}), el("pre", {text: o.original})),
                                              el("div", {}, el("h3", {text: "Optimized"}), el("pre", {text: o.code}))));
  const det = el("details", {}, el("summary", {text: "Line-by-line comparison"}));
  const t = el("table", {"class": "diff"}), head = el("tr");
  head.appendChild(el("th", {text: "Before"})); head.appendChild(el("th", {text: "After"})); t.appendChild(head);
  o.diff.forEach((row) => { const tr = el("tr");
    tr.appendChild(el("td", {"class": row[2] === "chg" || row[2] === "del" ? "del" : "", text: row[0]}));
    tr.appendChild(el("td", {"class": row[2] === "chg" || row[2] === "add" ? "add" : "", text: row[1]})); t.appendChild(tr); });
  det.appendChild(el("div", {style: "overflow:auto"}, t)); pane.appendChild(det);
  pane.appendChild(el("h3", {text: "Why these changes?"}));
  if (!o.why.length) pane.appendChild(el("p", {"class": "mute", text: "Nothing was changed."}));
  o.why.forEach((w) => pane.appendChild(el("div", {"class": "why"}, el("b", {text: w.title + " (" + w.count + "x)"}), el("div", {text: w.explanation}),
    el("div", {"class": "mute", text: w.examples.join("   |   ")}))));
}

function selectionTable(list) {
  return table(["pass", "confidence", "decision", "reason"], list.map((s) => [s.pass, bar(s.confidence, 1, s.selected ? "" : "base"),
    el("span", {"class": s.selected ? "ok" : "mute", text: s.selected ? "run" : "skip"}), s.reason]));
}
function renderPasses(pane, d) {
  const o = d.optimization;
  pane.appendChild(el("h3", {text: "Rule-based selector (features + dry run)"})); pane.appendChild(selectionTable(d.selection));
  if (d.ml_selection) {
    pane.appendChild(el("h3", {text: "ML selector (random forest, static features only)"})); pane.appendChild(selectionTable(d.ml_selection));
    if (d.ml_eval) pane.appendChild(el("p", {"class": "mute", text: "Held-out accuracy " + d.ml_eval.overall.toFixed(3) + " (majority baseline " + d.ml_eval.baseline.toFixed(3) + ", target > 0.75)"}));
  }
  pane.appendChild(el("h3", {text: "What changed and why"}));
  const counts = Object.keys(o.change_counts);
  if (!counts.length) pane.appendChild(el("p", {text: "No transformations were applied."}));
  counts.forEach((p) => pane.appendChild(el("p", {}, el("b", {text: p + " (" + o.change_counts[p] + "): "}), o.explanations[p] || "")));
  if (o.changes.length) { const det = el("details", {}, el("summary", {text: "All " + o.changes.length + " transformations"}));
    det.appendChild(table(["line", "pass", "change"], o.changes.map((c) => [c.line, c.pass, c.description]))); pane.appendChild(det); }
  o.rejected.forEach((r) => pane.appendChild(el("p", {"class": "bad", text: "Rejected: " + r.pass + " - " + r.reason})));
  const v = o.validation;
  pane.appendChild(el("h3", {text: "Semantic validation"}));
  pane.appendChild(el("p", {}, el("span", {"class": v.passed ? "ok" : "bad", text: v.passed ? "PASSED  " : "FAILED  "}),
    v.tests_conclusive + "/" + v.tests_total + " conclusive differential tests, " + v.mismatches.length + " mismatch(es). Operations executed " + v.cost_before + " \u2192 " + v.cost_after + " (" + v.cost_reduction_pct + "% fewer)."));
  v.warnings.forEach((w) => pane.appendChild(el("p", {"class": "warn", text: "warning: " + w})));
}

function renderTwin(pane, d) {
  const tw = d.twin, rows = tw.strategies.filter((s) => s.predicted_cost !== null);
  const top = Math.max(1, tw.baseline.predicted_cost, ...rows.map((s) => s.predicted_cost));
  const best = tw.recommendation ? tw.recommendation.strategy : "";
  if (tw.recommendation) pane.appendChild(el("div", {"class": "rec"}, el("b", {text: "Recommended: "}), tw.recommendation.strategy + " - " + tw.recommendation.reason));
  pane.appendChild(el("h3", {text: "Strategy comparison (predicted cost, lower is better)"}));
  pane.appendChild(table(["strategy", "valid", "predicted", "measured", "error %", "saving %", "size", "stack B"], tw.strategies.map((s) => {
    if (s.predicted_cost === null) return [s.strategy, el("span", {"class": "bad", text: "NO"}), s.error || "", "", "", "", "", ""];
    return [s.strategy, el("span", {"class": s.valid ? "ok" : "bad", text: s.valid ? "yes" : "NO"}),
      bar(s.predicted_cost, top, !s.valid ? "bad" : (s.strategy === best ? "best" : (s.saving_pct <= 0 ? "base" : ""))), s.measured_cost, s.prediction_error_pct, s.saving_pct, s.code_size, s.memory_bytes];
  })));
  if (tw.accuracy) pane.appendChild(el("p", {text: "Prediction accuracy: mean error " + tw.accuracy.mean_error_pct + "% (target <= 15%), " + Math.round(100 * tw.accuracy.within_15_pct) +
    "% of strategies within 15%, " + Math.round(100 * tw.accuracy.rank_agreement) + "% of pairs ranked like reality."}));
}

function renderInsights(pane, d) {
  pane.appendChild(el("h3", {text: "Cost hotspots"}));
  const top = Math.max(1, ...d.hotspots.map((h) => h.share_pct));
  pane.appendChild(table(["line", "code", "share of cost"], d.hotspots.map((h) => [h.line, h.code, bar(h.share_pct, top, h === d.hotspots[0] ? "bad" : "")])));
  pane.appendChild(el("h3", {text: "Refactoring suggestions"}));
  if (!d.suggestions.length) pane.appendChild(el("p", {"class": "mute", text: "None - nothing to improve by hand."}));
  d.suggestions.forEach((s) => pane.appendChild(el("p", {}, el("b", {text: "[" + s.severity + "] line " + s.line + ": "}), s.message + " " + s.fix)));
  if (d.refactoring) { pane.appendChild(el("h3", {text: "Verified refactoring"})); pane.appendChild(el("p", {text: d.refactoring.summary})); pane.appendChild(el("pre", {text: d.refactoring.code})); }
}

/* ------------------------------------------------------------------ copilot */
function rich(box, text) {
  const re = /```([A-Za-z+]*)\n?([\s\S]*?)```/g; let last = 0, m;
  const plain = (s) => { if (s) box.appendChild(document.createTextNode(s)); };
  while ((m = re.exec(text)) !== null) {
    plain(text.slice(last, m.index));
    const code = m[2].replace(/\n$/, "");
    box.appendChild(el("pre", {text: code})); box.appendChild(el("button", {"class": "chip", text: "Copy code", onclick: () => copyText(code)}));
    last = m.index + m[0].length;
  }
  plain(text.slice(last));
}
function drawMsg(who, text, typing) {
  const log = $("chat"), box = el("div", {"class": "msg " + (who === "me" ? "me" : "bot") + (typing ? " typing" : "")});
  if (who === "me" || typing) box.textContent = text; else rich(box, text);
  log.appendChild(box); log.scrollTop = log.scrollHeight; return box;
}
function addMsg(who, text) { state.chat.push({who: who, text: text}); if ($("chat")) drawMsg(who, text); }
async function ask(q) {
  if (!state.session) { toast("Analyze some code first", "bad"); return; }
  addMsg("me", q);
  const typing = $("chat") ? drawMsg("bot", "thinking\u2026", true) : null;
  try {
    const r = await api("/api/chat", {session_id: state.session, message: q, level: $("level") ? $("level").value : "beginner"});
    if (typing) typing.remove();
    addMsg("bot", r.text + (r.llm_error ? "\n\n(Gemini note: " + r.llm_error + ")" : ""));
    const f = $("follow"); if (f) { f.textContent = ""; (r.followups || []).forEach((s) => f.appendChild(el("button", {"class": "chip", text: s, onclick: () => ask(s)}))); }
  } catch (e) { if (typing) typing.remove(); addMsg("bot", "Error: " + e.message); }
}
function renderCopilot(pane) {
  const lvl = el("select", {id: "level"}); ["beginner", "intermediate", "advanced"].forEach((l) => lvl.appendChild(el("option", {value: l, text: l})));
  pane.appendChild(el("div", {"class": "row"}, el("span", {"class": "mute", text: "Explain at level:"}), lvl, el("span", {"class": "grow"}),
    el("span", {"class": "mute", text: state.llm.enabled ? "Gemini on (" + state.llm.model + ")" : "offline mode - set GEMINI_API_KEY in .env for open questions"})));
  pane.appendChild(el("div", {id: "chat"}));
  const input = el("input", {id: "q", placeholder: "Ask about your code, e.g. show me the optimized code and why", style: "flex:1;min-width:220px"});
  const send = () => { const v = input.value.trim(); if (v) { input.value = ""; ask(v); } };
  input.onkeydown = (e) => { if (e.key === "Enter") send(); };
  pane.appendChild(el("div", {"class": "row"}, input, el("button", {"class": "primary", text: "Ask", onclick: send})));
  const quick = ["show me the optimized code and why", "why is this slow?", "how can I optimize this function?", "what changed?", "is it safe?", "which passes did you choose?", "what is constant folding?"];
  const qs = el("div", {"class": "row"}); quick.forEach((s) => qs.appendChild(el("button", {"class": "chip", text: s, onclick: () => ask(s)}))); pane.appendChild(qs);
  pane.appendChild(el("div", {"class": "row", id: "follow"}));
  if (!state.chat.length) state.chat.push({who: "bot", text: "Hi! I explain what CodeTune did to your code and answer compiler-design questions about it. Pick a question below or type your own."});
  state.chat.forEach((m) => drawMsg(m.who, m.text));
}
function renderPane() {
  const pane = $("pane"); pane.textContent = "";
  if (!state.data) {
    pane.appendChild(el("div", {"class": "card empty"}, el("h2", {text: "Paste your own code to begin"}),
      el("p", {text: "Type or paste a function, drop a file onto the editor, or open an example. CodeTune will optimize it, prove it still behaves the same and explain every change."})));
    return;
  }
  const card = el("div", {"class": "card"}); pane.appendChild(card);
  ({"Flow": renderFlow, "Overview": renderOverview, "Optimized code": renderOptimized, "Passes": renderPasses, "Digital Twin": renderTwin, "Insights": renderInsights, "Copilot": renderCopilot})[state.tab](card, state.data);
}

/* ------------------------------------------------------------------ analyze */
async function analyze() {
  const code = $("code").value;
  if (!code.trim()) { showError("Please paste or type some code first.", 0); return; }
  const seq = ++state.seq, btn = $("go"), st = $("status");
  btn.disabled = true; btn.textContent = "Analyzing\u2026"; st.textContent = "";
  try {
    const d = await api("/api/analyze", {code: code, language: currentLanguage(), function: $("func").value || null});
    if (seq !== state.seq) return;
    state.data = d; state.session = d.session_id; state.chat = []; state.lastAnalysed = code;
    const sel = $("func"); sel.textContent = "";
    d.functions.forEach((n) => { const o = el("option", {value: n, text: n}); if (n === d.function) o.selected = true; sel.appendChild(o); });
    showError(""); renderStats(); renderAlerts(); renderPane(); st.textContent = "done \u00b7 " + d.language;
    state.flowSel = 0;
  } catch (e) {
    if (seq !== state.seq) return;
    state.data = null; state.session = null; renderStats(); renderAlerts(); renderPane(); showError(e.message + (e.advice ? "\n\n--- Gemini advice (not verified by CodeTune) ---\n" + e.advice : (state.llm.enabled ? "" : "\n\n(Add GEMINI_API_KEY to the .env file to get AI advice for code CodeTune cannot model.)")), e.line || 0);
  } finally { if (seq === state.seq) { btn.disabled = false; btn.textContent = "Analyze & optimize"; } }
}

/* ------------------------------------------------------------------ gemini settings */
function paintLlm() { const b = $("llmBtn"), l = state.llm; b.textContent = l.enabled ? "Gemini: on" : (l.cooldown ? "Gemini: paused (" + l.cooldown + "s)" : "Gemini: off"); b.className = "pill" + (l.enabled ? " on" : ""); }
async function refreshLlm() { try { state.llm = await api("/api/llm"); } catch (e) {} paintLlm(); }
setInterval(refreshLlm, 15000);

/* ------------------------------------------------------------------ init */
function init() {
  let theme = "light"; try { theme = localStorage.getItem("ct-theme") || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); } catch (e) {}
  setTheme(theme); renderTabs(); renderPane(); updateGutter(); refreshLlm();
  $("themeBtn").onclick = () => setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  $("go").onclick = analyze;
  $("clearBtn").onclick = () => { loadText(""); state.data = null; state.session = null; renderStats(); renderAlerts(); renderPane(); };
  $("uploadBtn").onclick = () => $("file").click();
  $("file").onchange = () => { readFile($("file").files[0]); $("file").value = ""; };
  $("func").onchange = () => analyze();
  const ta = $("code");
  ta.oninput = () => { updateGutter(); showError(""); if ($("auto").checked) { clearTimeout(state.timer); state.timer = setTimeout(() => { if (ta.value.trim() && ta.value !== state.lastAnalysed) analyze(); }, 1300); } };
  ta.onscroll = () => { $("gutter").scrollTop = ta.scrollTop; };
  ta.onkeydown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); analyze(); }
    else if (e.key === "Tab") { e.preventDefault(); const s = ta.selectionStart; ta.value = ta.value.slice(0, s) + "    " + ta.value.slice(ta.selectionEnd); ta.selectionStart = ta.selectionEnd = s + 4; updateGutter(); }
  };
  const ed = $("editor");
  ["dragenter", "dragover"].forEach((ev) => ed.addEventListener(ev, (e) => { e.preventDefault(); ed.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => ed.addEventListener(ev, (e) => { e.preventDefault(); ed.classList.remove("drag"); }));
  ed.addEventListener("drop", (e) => { const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) readFile(f); });
  fetch("/api/samples").then((r) => r.json()).then((s) => {
    state.samples = s; const sel = $("sample");
    Object.keys(s).forEach((n) => sel.appendChild(el("option", {value: n, text: n})));
    sel.onchange = () => { const x = state.samples[sel.value]; if (x) { loadText(x.code, sel.value); } sel.value = ""; };
  }).catch(() => {});
}
init();