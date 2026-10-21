"""
Report for the Digital Twin: strategy comparison, recommendation, prediction
accuracy and version history -- as a JSON-serialisable dict, Markdown or a
self-contained HTML page with simple bar charts.
"""

import html
import json
import os
from typing import Dict, List, Optional

from ..ir.ir_printer import print_function
from .cost_model import CLOCK_GHZ, COST_WEIGHTS, estimated_time_ns


def build_twin_data(twin, experiments, recommendation=None, accuracy=None, what_ifs=None) -> Dict:
    b = twin.baseline
    rows = []
    for e in experiments:
        m = e.metrics
        rows.append({
            "strategy": e.strategy.name, "plan": e.strategy.describe(), "valid": e.valid, "error": e.error,
            "predicted_cost": None if m is None else round(m.predicted_cost, 1),
            "measured_cost": None if m is None or m.measured_cost is None else round(m.measured_cost, 1),
            "prediction_error_pct": None if m is None else m.prediction_error_pct,
            "estimated_time_ns": None if m is None else round(estimated_time_ns(m.predicted_cost), 1),
            "code_size": None if m is None else m.code_size,
            "memory_bytes": None if m is None else m.memory_bytes,
            "saving_pct": e.saving_pct, "measured_saving_pct": e.measured_saving_pct,
            "transformations": len(e.changes), "optimization_time_ms": e.opt_time_ms,
            "mismatches": [] if e.validation is None else [str(x) for x in e.validation.mismatches[:3]],
        })
    data = {
        "function": twin.func_name, "language": twin.language, "revision": twin.revision,
        "baseline": {"predicted_cost": round(b.predicted_cost, 1),
                     "measured_cost": None if b.measured_cost is None else round(b.measured_cost, 1),
                     "code_size": b.code_size, "memory_bytes": b.memory_bytes, "lines": b.lines},
        "cost_model": {"weights": COST_WEIGHTS, "clock_ghz": CLOCK_GHZ,
                       "note": "one cost unit ~ one CPU cycle (modelled, not measured on hardware)"},
        "strategies": rows,
        "history": twin.history(),
        "original_code": print_function(twin.original),
    }
    if recommendation is not None:
        data["recommendation"] = {"strategy": recommendation.experiment.strategy.name,
                                  "saving_pct": recommendation.saving_pct, "reason": recommendation.reason,
                                  "optimized_code": print_function(recommendation.experiment.func)}
    if accuracy is not None:
        data["accuracy"] = {"mean_error_pct": accuracy.mean_error_pct, "within_15_pct": accuracy.within_15_pct,
                            "rank_agreement": accuracy.rank_agreement, "winner_matches": accuracy.winner_matches}
    if what_ifs:
        data["what_if"] = [{"question": w.question, "answer": w.answer} for w in what_ifs]
    return data


def to_json(data: Dict) -> str:
    return json.dumps(data, indent=2)


def to_markdown(data: Dict) -> str:
    L: List[str] = [f"# Digital Twin report: `{data['function']}` ({data['language']})", "",
                    f"Baseline: predicted cost **{data['baseline']['predicted_cost']}**, measured "
                    f"**{data['baseline']['measured_cost']}**, code size {data['baseline']['code_size']}, "
                    f"stack {data['baseline']['memory_bytes']} bytes.", ""]
    if "recommendation" in data:
        r = data["recommendation"]
        L += ["## Recommendation", "", f"**{r['strategy']}** - {r['reason']}", ""]
    L += ["## Strategy comparison", "",
          "| Strategy | Valid | Predicted | Measured | Error % | Saving % | Size | Stack B |", "|---|---|---|---|---|---|---|---|"]
    for s in data["strategies"]:
        L.append(f"| {s['strategy']} | {'yes' if s['valid'] else 'NO'} | {s['predicted_cost']} | {s['measured_cost']} "
                 f"| {s['prediction_error_pct']} | {s['saving_pct']} | {s['code_size']} | {s['memory_bytes']} |")
    if "accuracy" in data:
        a = data["accuracy"]
        L += ["", "## Prediction accuracy", "",
              f"- mean error vs measured: **{a['mean_error_pct']}%** (target: within 15%)",
              f"- strategies predicted within 15%: **{round(100 * a['within_15_pct'])}%**",
              f"- strategy pairs ranked the same as reality: **{round(100 * a['rank_agreement'])}%**",
              f"- predicted winner is also the measured winner: **{'yes' if a['winner_matches'] else 'no'}**"]
    if data.get("what_if"):
        L += ["", "## What-if"] + [f"- {w['question']} {w['answer']}" for w in data["what_if"]]
    L += ["", "## Version history", ""] + [
        f"- v{v['id']}{' (head)' if v['head'] else ''}: {v['label']} - cost {v['predicted_cost']}, size {v['code_size']}"
        for v in data["history"]]
    L += ["", "Cost model: " + data["cost_model"]["note"], ""]
    return "\n".join(L)


_CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem auto;max-width:1100px;padding:0 1rem;color:#1b1f23}
h1{border-bottom:2px solid #444;padding-bottom:.3rem} h2{margin-top:2rem;background:#eef2f7;padding:.4rem .7rem;border-radius:6px}
table{border-collapse:collapse;width:100%} th,td{border:1px solid #d0d7de;padding:.35rem .6rem;text-align:left}
th{background:#f6f8fa} .bar{height:14px;background:#2da44e;border-radius:3px} .bar.base{background:#8c959f}
.bar.bad{background:#cf222e} .ok{color:#1a7f37;font-weight:600}.bad{color:#cf222e;font-weight:600}
.rec{background:#dafbe1;border:1px solid #2da44e;border-radius:6px;padding:.6rem 1rem} pre{background:#f6f8fa;padding:.6rem;overflow:auto}
"""


def to_html(data: Dict) -> str:
    e = html.escape
    rows = [s for s in data["strategies"] if s["predicted_cost"] is not None]
    top = max([s["predicted_cost"] for s in rows] + [data["baseline"]["predicted_cost"], 1])
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>Digital Twin: {e(data['function'])}</title>"
           f"<style>{_CSS}</style></head><body><h1>Digital Twin: <code>{e(data['function'])}</code> "
           f"({e(data['language'])})</h1>"]
    if "recommendation" in data:
        r = data["recommendation"]
        out.append(f"<div class='rec'><b>Recommended:</b> {e(r['strategy'])}<br>{e(r['reason'])}</div>")
    out.append("<h2>Strategy comparison (predicted cost, lower is better)</h2><table><tr><th>Strategy</th><th>Valid</th>"
               "<th style='width:32%'>Predicted cost</th><th>Measured</th><th>Error %</th><th>Saving %</th>"
               "<th>Size</th><th>Stack B</th></tr>")
    for s in data["strategies"]:
        if s["predicted_cost"] is None:
            out.append(f"<tr><td>{e(s['strategy'])}</td><td class='bad'>NO</td><td colspan='6'>{e(s['error'] or '')}</td></tr>")
            continue
        w = round(100 * s["predicted_cost"] / top)
        cls = "bar" + (" bad" if not s["valid"] else (" base" if s["saving_pct"] <= 0 else ""))
        out.append(f"<tr><td>{e(s['strategy'])}<br><small>{e(s['plan'])}</small></td>"
                   f"<td class='{'ok' if s['valid'] else 'bad'}'>{'yes' if s['valid'] else 'NO'}</td>"
                   f"<td><div class='{cls}' style='width:{w}%'></div>{s['predicted_cost']}</td>"
                   f"<td>{s['measured_cost']}</td><td>{s['prediction_error_pct']}</td><td>{s['saving_pct']}</td>"
                   f"<td>{s['code_size']}</td><td>{s['memory_bytes']}</td></tr>")
    out.append("</table>")
    if "accuracy" in data:
        a = data["accuracy"]
        out.append(f"<h2>Prediction accuracy</h2><p>Mean error <b>{a['mean_error_pct']}%</b> (target &le; 15%); "
                   f"{round(100 * a['within_15_pct'])}% of strategies within 15%; "
                   f"{round(100 * a['rank_agreement'])}% of pairs ranked like reality; predicted winner "
                   f"{'is' if a['winner_matches'] else 'is NOT'} the measured winner.</p>")
    if data.get("what_if"):
        out.append("<h2>What-if</h2><ul>" + "".join(f"<li><b>{e(w['question'])}</b> {e(w['answer'])}</li>"
                                                      for w in data["what_if"]) + "</ul>")
    if "recommendation" in data:
        out.append("<h2>Original vs recommended code</h2><table><tr><th>Original</th><th>Recommended</th></tr><tr>"
                   f"<td><pre>{e(data['original_code'])}</pre></td>"
                   f"<td><pre>{e(data['recommendation']['optimized_code'])}</pre></td></tr></table>")
    out.append("<h2>Version history</h2><ul>" + "".join(
        f"<li>v{v['id']}{' <b>(head)</b>' if v['head'] else ''}: {e(v['label'])} &mdash; cost {v['predicted_cost']}, "
        f"size {v['code_size']}</li>" for v in data["history"]) + "</ul>")
    out.append(f"<p><small>{e(data['cost_model']['note'])}</small></p></body></html>")
    return "".join(out)


def write_twin_report(data: Dict, out_dir: str, basename: str = "digital_twin") -> Dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for ext, text in (("md", to_markdown(data)), ("html", to_html(data)), ("json", to_json(data))):
        path = os.path.join(out_dir, f"{basename}.{ext}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        paths[ext] = path
    return paths