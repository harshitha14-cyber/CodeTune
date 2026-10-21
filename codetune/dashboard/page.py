"""The dashboard's single HTML page (no external files, no CDN: works offline)."""

PAGE_HTML = r"""<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8"><title>CodeTune</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#f4f6fa;--card:#fff;--line:#d9dee7;--ink:#18202b;--mute:#667085;--accent:#4f46e5;--accent2:#7c3aed;--ok:#168a45;--bad:#d92d20;--warn:#b54708;
--okbg:#e8f7ee;--badbg:#fdecea;--warnbg:#fff4df;--code:#f0f2f7;--shadow:0 1px 2px rgba(16,24,40,.06),0 4px 14px rgba(16,24,40,.06)}
[data-theme=dark]{--bg:#0f141b;--card:#171e28;--line:#2a3442;--ink:#e6eaf1;--mute:#94a0b4;--accent:#8b84ff;--accent2:#b18cff;--ok:#4ade80;--bad:#ff7b72;--warn:#f0b429;
--okbg:#12301f;--badbg:#3a1a1a;--warnbg:#3a2e12;--code:#0f141b;--shadow:0 1px 2px rgba(0,0,0,.4)}
*{box-sizing:border-box} html,body{margin:0}
body{font-family:Inter,system-ui,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink);font-size:14.5px;line-height:1.45}
header{display:flex;align-items:center;gap:.9rem;padding:.65rem 1.2rem;background:linear-gradient(90deg,#312e81,#6d28d9);color:#fff}
.logo{font-weight:800;font-size:1.2rem;letter-spacing:.2px} header small{opacity:.8;flex:1}
.pill{border:1px solid rgba(255,255,255,.45);background:rgba(255,255,255,.12);color:#fff;border-radius:999px;padding:.25rem .8rem;cursor:pointer;font-size:.85rem}
.pill.on{background:#16a34a;border-color:#16a34a}
main{display:grid;grid-template-columns:minmax(340px,40%) 1fr;gap:1rem;padding:1rem;max-width:1600px;margin:0 auto;align-items:start}
@media(max-width:980px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:.85rem 1rem;margin-bottom:1rem;box-shadow:var(--shadow)}
h2{font-size:1rem;margin:.1rem 0 .6rem} h3{font-size:.92rem;margin:1rem 0 .4rem}
button,select,input{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.35rem .6rem}
button{cursor:pointer} button:hover{border-color:var(--accent)}
button.primary{background:linear-gradient(90deg,var(--accent),var(--accent2));border:0;color:#fff;font-weight:600;padding:.5rem 1.1rem}
button:disabled{opacity:.55;cursor:wait}
.row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin:.4rem 0}
.grow{flex:1}
.editor{position:relative;display:flex;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--code)}
.editor.drag{outline:2px dashed var(--accent)}
#gutter{width:3.1rem;padding:.55rem .4rem;text-align:right;color:var(--mute);background:var(--card);border-right:1px solid var(--line);overflow:hidden;user-select:none;font:12.5px/1.55 Consolas,Menlo,monospace}
#gutter div.err{background:var(--badbg);color:var(--bad);font-weight:700}
#code{flex:1;height:360px;border:0;border-radius:0;resize:vertical;padding:.55rem;background:transparent;font:12.5px/1.55 Consolas,Menlo,monospace;white-space:pre;overflow:auto;outline:none;tab-size:4}
.err-box{margin-top:.5rem;padding:.55rem .75rem;border-radius:8px;background:var(--badbg);color:var(--bad);border:1px solid var(--bad);white-space:pre-wrap;font-size:.88rem}
details summary{cursor:pointer;color:var(--accent);font-weight:600} details ul{margin:.4rem 0 0 1.1rem;padding:0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.7rem;margin-bottom:1rem}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:.65rem .9rem;box-shadow:var(--shadow)}
.stat b{display:block;color:var(--mute);font-weight:600;font-size:.75rem;text-transform:uppercase;letter-spacing:.4px}
.stat span{font-size:1.35rem;font-weight:700} .stat small{display:block;color:var(--mute)}
.tabs{display:flex;gap:.2rem;border-bottom:1px solid var(--line);margin-bottom:.8rem;flex-wrap:wrap}
.tab{background:none;border:0;border-bottom:3px solid transparent;border-radius:0;padding:.55rem .9rem;color:var(--mute)}
.tab.on{border-bottom-color:var(--accent);color:var(--ink);font-weight:700}
table{border-collapse:collapse;width:100%;font-size:.86rem} th,td{border:1px solid var(--line);padding:.3rem .5rem;text-align:left;vertical-align:top}
th{background:var(--code);font-weight:600}
pre{background:var(--code);padding:.6rem .75rem;border-radius:8px;overflow:auto;font:12.5px/1.5 Consolas,Menlo,monospace;margin:.3rem 0;border:1px solid var(--line)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:.7rem} @media(max-width:1250px){.two{grid-template-columns:1fr}}
.two h3{margin-top:0}
.diff td{white-space:pre;font:12px/1.45 Consolas,Menlo,monospace;padding:.05rem .4rem;width:50%}
.del{background:var(--badbg)}.add{background:var(--okbg)}
.pipe{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.5rem;margin-bottom:.8rem}
.stage{border:1px solid var(--line);border-radius:10px;padding:.5rem .65rem;background:var(--card);border-left:4px solid var(--accent)}
.stage b{display:block;font-size:.75rem;color:var(--mute)} .stage.ok{border-left-color:var(--ok)} .stage.bad{border-left-color:var(--bad)}
.barwrap{display:flex;align-items:center;gap:.45rem;min-width:140px}
.bar{height:11px;border-radius:4px;background:var(--accent);display:inline-block} .bar.base{background:#98a2b3} .bar.bad{background:var(--bad)} .bar.best{background:var(--ok)}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}.warn{color:var(--warn)}.mute{color:var(--mute)}
.alert{border-left:4px solid var(--warn);background:var(--warnbg);padding:.4rem .65rem;margin:.35rem 0;border-radius:6px;font-size:.86rem}
.rec{border:1px solid var(--ok);background:var(--okbg);border-radius:10px;padding:.55rem .85rem;margin:.4rem 0}
.why{border-left:4px solid var(--accent);padding:.25rem .7rem;margin:.5rem 0;background:var(--code);border-radius:0 8px 8px 0}
#chat{height:380px;overflow:auto;border:1px solid var(--line);border-radius:10px;padding:.6rem;background:var(--code)}
.msg{margin:.45rem 0;max-width:94%;padding:.45rem .7rem;border-radius:12px;white-space:pre-wrap;font-size:.9rem}
.msg.me{background:linear-gradient(90deg,var(--accent),var(--accent2));color:#fff;margin-left:auto;border-bottom-right-radius:3px}
.msg.bot{background:var(--card);border:1px solid var(--line);border-bottom-left-radius:3px}
.msg pre{white-space:pre;margin:.4rem 0}
.chip{border:1px solid var(--accent);color:var(--accent);background:transparent;border-radius:999px;padding:.15rem .65rem;font-size:.8rem}
.typing{color:var(--mute);font-style:italic}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:20}
.modal[hidden]{display:none} .dialog{background:var(--card);border-radius:14px;padding:1.1rem 1.3rem;width:min(520px,92vw);box-shadow:0 20px 60px rgba(0,0,0,.35)}
.dialog input{width:100%;margin:.25rem 0 .7rem}
#toasts{position:fixed;right:1rem;bottom:1rem;display:flex;flex-direction:column;gap:.4rem;z-index:30}
.toast{background:#1f2937;color:#fff;padding:.5rem .8rem;border-radius:8px;box-shadow:var(--shadow);font-size:.86rem}.toast.bad{background:var(--bad)}.toast.ok{background:var(--ok)}
.empty{text-align:center;color:var(--mute);padding:2.2rem 1rem}
.empty h2{color:var(--ink)}
</style></head><body>
<header><span class="logo">CodeTune</span><small>explainable adaptive compiler &middot; Digital Twin &middot; AI Copilot</small>
  <button class="pill" id="llmBtn" title="Gemini language model settings">Gemini: off</button>
  <button class="pill" id="themeBtn" title="light / dark">Dark mode</button></header>
<main>
<section>
  <div class="card"><h2>Your code</h2>
    <div class="row">
      <select id="lang" title="source language"><option value="auto">Auto-detect language</option><option value="c">C</option><option value="cpp">C++</option><option value="java">Java</option><option value="python">Python</option></select>
      <select id="func" title="function to analyse"><option value="">first function</option></select>
      <span class="grow"></span>
      <button id="uploadBtn">Open file</button><select id="sample" title="examples"><option value="">Examples</option></select><button id="clearBtn">Clear</button>
      <input type="file" id="file" hidden accept=".c,.h,.cpp,.cc,.cxx,.hpp,.java,.py,.txt">
    </div>
    <div class="editor" id="editor"><div id="gutter"></div>
      <textarea id="code" spellcheck="false" wrap="off" placeholder="Paste or type a C, C++, Java or Python function here, or drop a file onto this box...&#10;&#10;def f(n):&#10;    s = 0&#10;    for i in range(n):&#10;    &#9;s += i * 8&#10;    return s"></textarea></div>
    <div class="row"><button class="primary" id="go">Analyze &amp; optimize</button><label class="mute"><input type="checkbox" id="auto"> analyze as I type</label><span class="grow"></span><span id="status" class="mute">Ctrl+Enter</span></div>
    <div id="errbox" class="err-box" hidden></div>
    <details style="margin-top:.6rem"><summary>What code can I use?</summary><ul class="mute">
      <li>Functions in C, C++, Java (methods in a class) or Python, with int / bool / double and strings.</li>
      <li>Statements: variables, assignments, <code>+= -= *= ...</code>, <code>i++</code>, if / else if / else, while, <code>for</code> loops (Python: <code>for i in range(...)</code>), return, calls.</li>
      <li>Not yet: arrays, pointers, structs, break / continue, switch, do-while, ternary <code>?:</code>, casts, <code>for x in list</code>.</li>
      <li>Calls to unknown functions are kept; <code>print</code>, <code>printf</code>, <code>Math.max</code> ... are understood.</li>
      <li>Your code is analysed by CodeTune's own interpreter &mdash; it is never run natively.</li></ul></details>
  </div>
  <div class="card"><h2>Proactive alerts</h2><div id="alerts" class="mute">Analyze some code first.</div></div>
</section>
<section>
  <div id="stats" class="stats" hidden></div>
  <div class="tabs" id="tabs"></div>
  <div id="pane"></div>
</section>
</main>
<div class="modal" id="modal" hidden><div class="dialog">
  <h2>Gemini language model</h2>
  <p class="mute">Gemini lets the Copilot phrase answers more naturally and answer open compiler-theory questions. It stays restricted to compiler design, your code and optimization.</p>
  <p class="warn"><b>Privacy:</b> when enabled, your question and a short summary of your code are sent to Google. The key is kept in memory by this local server only; it is never saved to disk or shown again. You can also set the GEMINI_API_KEY environment variable instead.</p>
  <label>API key (create one at aistudio.google.com/apikey)</label><input type="password" id="keyIn" placeholder="paste your Gemini API key" autocomplete="off">
  <label>Model</label><input id="modelIn" placeholder="gemini-flash-latest">
  <div id="llmMsg" class="mute" style="min-height:1.3rem"></div>
  <div class="row"><button class="primary" id="saveKey">Save</button><button id="testKey">Test</button><button id="clearKey">Remove key</button><span class="grow"></span><button id="closeModal">Close</button></div>
</div></div>
<div id="toasts"></div>
<script>
"use strict";
const TABS = ["Overview", "Optimized code", "Passes", "Digital Twin", "Insights", "Copilot"];
const EXT = {python: "py", c: "c", cpp: "cpp", java: "java"};
const state = {data: null, tab: "Overview", session: null, samples: {}, chat: [], llm: {enabled: false, model: ""}, seq: 0, timer: null, lastAnalysed: ""};
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
  if (!r.ok) { const e = new Error(j.error || r.statusText); e.line = j.line; throw e; }
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
    el("span", {"class": "mute", text: state.llm.enabled ? "Gemini on (" + state.llm.model + ")" : "offline mode - add a Gemini key for open questions"})));
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
  ({"Overview": renderOverview, "Optimized code": renderOptimized, "Passes": renderPasses, "Digital Twin": renderTwin, "Insights": renderInsights, "Copilot": renderCopilot})[state.tab](card, state.data);
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
    if (state.tab === "Overview") { state.tab = "Optimized code"; renderTabs(); renderPane(); }
  } catch (e) {
    if (seq !== state.seq) return;
    state.data = null; state.session = null; renderStats(); renderAlerts(); renderPane(); showError(e.message, e.line || 0);
  } finally { if (seq === state.seq) { btn.disabled = false; btn.textContent = "Analyze & optimize"; } }
}

/* ------------------------------------------------------------------ gemini settings */
function paintLlm() { const b = $("llmBtn"); b.textContent = state.llm.enabled ? "Gemini: on" : "Gemini: off"; b.className = "pill" + (state.llm.enabled ? " on" : ""); $("modelIn").placeholder = state.llm.model || "gemini-flash-latest"; }
async function refreshLlm() { try { state.llm = await api("/api/llm"); } catch (e) {} paintLlm(); }
async function llmAction(action) {
  const msg = $("llmMsg"); msg.className = "mute"; msg.textContent = action === "test" ? "Testing\u2026" : "Working\u2026";
  try {
    const r = await api("/api/llm", {action: action, api_key: $("keyIn").value.trim(), model: $("modelIn").value.trim()});
    state.llm = r; $("keyIn").value = ""; paintLlm();
    if (action === "test") { msg.className = r.ok ? "ok" : "bad"; msg.textContent = r.ok ? "Connected: " + r.reply : "Failed: " + r.error; }
    else { msg.className = "ok"; msg.textContent = action === "clear" ? "Key removed." : (r.enabled ? "Saved. Gemini is on (" + r.model + ")." : "Saved. Add a key to turn Gemini on."); }
  } catch (e) { msg.className = "bad"; msg.textContent = e.message; }
}

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
  $("llmBtn").onclick = () => { $("modal").hidden = false; $("llmMsg").textContent = ""; $("modelIn").value = state.llm.model || ""; };
  $("closeModal").onclick = () => { $("modal").hidden = true; };
  $("modal").onclick = (e) => { if (e.target === $("modal")) $("modal").hidden = true; };
  $("saveKey").onclick = () => llmAction("set"); $("testKey").onclick = () => llmAction("test"); $("clearKey").onclick = () => llmAction("clear");
  fetch("/api/samples").then((r) => r.json()).then((s) => {
    state.samples = s; const sel = $("sample");
    Object.keys(s).forEach((n) => sel.appendChild(el("option", {value: n, text: n})));
    sel.onchange = () => { const x = state.samples[sel.value]; if (x) { loadText(x.code, sel.value); } sel.value = ""; };
  }).catch(() => {});
}
init();
</script></body></html>
"""