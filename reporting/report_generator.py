"""
Phase 6 -- Explainability and reporting.

Turns an OptimizationReport into a human-readable report containing exactly
what the project report promises:

    detected features . selected optimizations + confidence . reason for each
    selection . before/after code . validation result . performance metrics

One JSON-serialisable dict (`build_report_data`) is the single source of truth;
Markdown, HTML and JSON are just renderings of it. The same dict is what the
dashboard (Milestone 5) and the Copilot will read.
"""

import difflib
import html
import json
import os
from collections import Counter
from typing import Dict, List

from ..ir.ir_printer import print_function

PASS_EXPLANATIONS = {
    "constant_propagation": "A variable that always holds the same value was replaced by that value, "
                            "which exposes further simplifications.",
    "constant_folding": "An expression made only of constants is computed once at compile time "
                        "instead of every time the program runs.",
    "strength_reduction": "An expensive operation (such as multiplication) was replaced by a cheaper "
                          "equivalent (a shift or an addition).",
    "dead_code_elimination": "Code that can never run, or whose result is never used, was removed "
                             "(side effects such as function calls are always kept).",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _function_data(r) -> Dict:
    counts = Counter(c.pass_name for c in r.changes)
    before_code, after_code = print_function(r.original), print_function(r.optimized)
    v = r.validation
    return {
        "name": r.name,
        "features_before": r.features_before.to_dict(),
        "features_after": r.features_after.to_dict(),
        "selection": [{"pass": x.pass_name, "confidence": x.confidence, "selected": x.selected,
                       "reason": x.reason} for x in r.recommendations],
        "applied_passes": r.applied_passes,
        "iterations": r.iterations,
        "changes": [{"pass": c.pass_name, "line": c.line, "description": c.description} for c in r.changes],
        "change_counts": dict(counts),
        "explanations": {p: PASS_EXPLANATIONS.get(p, "") for p in counts},
        "rejected": [{"pass": x.pass_name, "reason": x.reason,
                      "examples": [str(m) for m in x.mismatches[:3]]} for x in r.rejected],
        "code_before": before_code,
        "code_after": after_code,
        "validation": None if v is None else {
            "passed": v.passed, "tests_total": v.tests_total, "tests_conclusive": v.tests_conclusive,
            "mismatches": [str(m) for m in v.mismatches], "warnings": v.warnings,
            "cost_before": v.original_cost, "cost_after": v.optimized_cost,
            "cost_reduction_pct": v.cost_reduction_pct},
        "metrics": {
            "lines_before": len(before_code.splitlines()), "lines_after": len(after_code.splitlines()),
            "transformations": len(r.changes)},
    }


def build_report_data(report, title: str = "CodeTune optimization report") -> Dict:
    return {"title": title, "language": report.language,
            "all_validated": report.all_validated,
            "total_changes": report.total_changes,
            "functions": [_function_data(r) for r in report.functions.values()]}


def to_json(data: Dict) -> str:
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

_KEY_FEATURES = ["constant_count", "variable_count", "branch_count", "loop_count",
                 "arithmetic_op_count", "mul_div_op_count"]


def to_markdown(data: Dict) -> str:
    L: List[str] = [f"# {data['title']}", "",
                    f"Language: **{data['language']}**  |  transformations: **{data['total_changes']}**  |  "
                    f"validation: **{'all passed' if data['all_validated'] else 'FAILED'}**", ""]
    for f in data["functions"]:
        L += [f"## Function `{f['name']}`", "", "### 1. Pass selection", "",
              "| Pass | Confidence | Decision | Reason |", "|---|---|---|---|"]
        for s in f["selection"]:
            L.append(f"| {s['pass']} | {s['confidence']:.2f} | {'run' if s['selected'] else 'skip'} | {s['reason']} |")
        L += ["", "### 2. What changed and why", ""]
        if not f["changes"]:
            L.append("No transformations were applied.")
        for p, n in f["change_counts"].items():
            L.append(f"- **{p}** ({n}): {f['explanations'][p]}")
        L += [""] + [f"  - line {c['line']}: `{c['description']}` ({c['pass']})" for c in f["changes"]]
        if f["rejected"]:
            L += ["", "### Rejected by validation", ""]
            for x in f["rejected"]:
                L.append(f"- **{x['pass']}**: {x['reason']}")
                L += [f"  - {e}" for e in x["examples"]]
        L += ["", "### 3. Code comparison", "", "Before:", "", "```", f["code_before"], "```", "",
              "After:", "", "```", f["code_after"], "```", "", "### 4. Features and metrics", "",
              "| Feature | Before | After |", "|---|---|---|"]
        for k in _KEY_FEATURES:
            L.append(f"| {k} | {f['features_before'][k]} | {f['features_after'][k]} |")
        L.append(f"| lines of code | {f['metrics']['lines_before']} | {f['metrics']['lines_after']} |")
        v = f["validation"]
        L += ["", "### 5. Semantic validation", ""]
        if v is None:
            L.append("Validation was not run.")
        else:
            L.append(f"Result: **{'PASSED' if v['passed'] else 'FAILED'}** - "
                     f"{v['tests_conclusive']}/{v['tests_total']} conclusive differential tests, "
                     f"{len(v['mismatches'])} mismatch(es).")
            L.append(f"Dynamic cost (operations executed over the tests): {v['cost_before']} -> "
                     f"{v['cost_after']} (**{v['cost_reduction_pct']}% fewer**).")
            L += [f"- warning: {w}" for w in v["warnings"]] + [f"- mismatch: {m}" for m in v["mismatches"]]
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# HTML (self-contained, side-by-side diff)
# ---------------------------------------------------------------------------

_CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem auto;max-width:1100px;padding:0 1rem;color:#1b1f23}
h1{border-bottom:2px solid #444;padding-bottom:.3rem} h2{margin-top:2.2rem;background:#eef2f7;padding:.4rem .7rem;border-radius:6px}
table{border-collapse:collapse;width:100%;margin:.6rem 0} th,td{border:1px solid #d0d7de;padding:.35rem .6rem;text-align:left;vertical-align:top}
th{background:#f6f8fa} code,pre{font-family:Consolas,Menlo,monospace;font-size:.88rem}
.diff td{white-space:pre;padding:.1rem .5rem;width:50%} .del{background:#ffebe9}.add{background:#dafbe1}
.ok{color:#1a7f37;font-weight:600}.bad{color:#cf222e;font-weight:600}.warn{color:#9a6700}
.run{color:#1a7f37;font-weight:600}.skip{color:#8c959f}
"""


def _side_by_side(before: str, after: str) -> str:
    a, b = before.splitlines(), after.splitlines()
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        left, right = a[i1:i2], b[j1:j2]
        for k in range(max(len(left), len(right))):
            l = left[k] if k < len(left) else ""
            r = right[k] if k < len(right) else ""
            lc = "del" if tag in ("replace", "delete") and k < len(left) else ""
            rc = "add" if tag in ("replace", "insert") and k < len(right) else ""
            rows.append(f'<tr><td class="{lc}">{html.escape(l)}</td><td class="{rc}">{html.escape(r)}</td></tr>')
    return '<table class="diff"><tr><th>Before</th><th>After</th></tr>' + "".join(rows) + "</table>"


def to_html(data: Dict) -> str:
    e = html.escape
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(data['title'])}</title>"
           f"<style>{_CSS}</style></head><body><h1>{e(data['title'])}</h1>",
           f"<p>Language <b>{e(data['language'])}</b> &middot; {data['total_changes']} transformations &middot; "
           f"validation <span class='{'ok' if data['all_validated'] else 'bad'}'>"
           f"{'all passed' if data['all_validated'] else 'FAILED'}</span></p>"]
    for f in data["functions"]:
        out.append(f"<h2>Function <code>{e(f['name'])}</code></h2><h3>Pass selection</h3>"
                   "<table><tr><th>Pass</th><th>Confidence</th><th>Decision</th><th>Reason</th></tr>")
        for s in f["selection"]:
            cls = "run" if s["selected"] else "skip"
            out.append(f"<tr><td>{e(s['pass'])}</td><td>{s['confidence']:.2f}</td>"
                       f"<td class='{cls}'>{'run' if s['selected'] else 'skip'}</td><td>{e(s['reason'])}</td></tr>")
        out.append("</table><h3>What changed and why</h3><ul>")
        for p, n in f["change_counts"].items():
            out.append(f"<li><b>{e(p)}</b> ({n}): {e(f['explanations'][p])}</li>")
        out.append("</ul>" if f["changes"] else "<li>No transformations applied.</li></ul>")
        if f["changes"]:
            out.append("<details><summary>All transformations</summary><ul>" + "".join(
                f"<li>line {c['line']}: <code>{e(c['description'])}</code> <i>({e(c['pass'])})</i></li>"
                for c in f["changes"]) + "</ul></details>")
        for x in f["rejected"]:
            out.append(f"<p class='bad'>Rejected: {e(x['pass'])} - {e(x['reason'])}</p>")
        out.append("<h3>Code comparison</h3>" + _side_by_side(f["code_before"], f["code_after"]))
        out.append("<h3>Features</h3><table><tr><th>Feature</th><th>Before</th><th>After</th></tr>")
        for k in _KEY_FEATURES:
            out.append(f"<tr><td>{k}</td><td>{f['features_before'][k]}</td><td>{f['features_after'][k]}</td></tr>")
        out.append("</table><h3>Semantic validation</h3>")
        v = f["validation"]
        if v is None:
            out.append("<p>Validation was not run.</p>")
        else:
            out.append(f"<p class='{'ok' if v['passed'] else 'bad'}'>{'PASSED' if v['passed'] else 'FAILED'}</p>"
                       f"<p>{v['tests_conclusive']}/{v['tests_total']} conclusive differential tests, "
                       f"{len(v['mismatches'])} mismatch(es). Dynamic cost {v['cost_before']} &rarr; "
                       f"{v['cost_after']} (<b>{v['cost_reduction_pct']}% fewer</b> operations).</p>")
            out += [f"<p class='warn'>warning: {e(w)}</p>" for w in v["warnings"]]
            out += [f"<p class='bad'>mismatch: {e(m)}</p>" for m in v["mismatches"]]
    out.append("</body></html>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def write_report(report, out_dir: str, basename: str = "codetune_report", title: str = None) -> Dict[str, str]:
    """Write .md, .html and .json next to each other; returns {format: path}."""
    os.makedirs(out_dir, exist_ok=True)
    data = build_report_data(report, title or "CodeTune optimization report")
    paths = {}
    for ext, text in (("md", to_markdown(data)), ("html", to_html(data)), ("json", to_json(data))):
        path = os.path.join(out_dir, f"{basename}.{ext}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        paths[ext] = path
    return paths