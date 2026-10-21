"""
CodeTune dashboard server (Milestone 5/6, report objective 5: "interactive dashboard
visualizing the complete compilation pipeline, optimization decisions and
performance impact").

Standard library only: a tiny threaded HTTP server that serves ONE page and a JSON
API. It never runs the user's code natively -- only CodeTune's own IR interpreter
(with a step limit) -- and it binds to 127.0.0.1 by default.

    GET  /               the dashboard page
    GET  /api/samples    bundled sample programs
    GET  /api/health
    POST /api/analyze    {code, language|"auto", function?}  -> full pipeline analysis + session_id
    POST /api/chat       {session_id, message, level?} -> Copilot answer
    GET  /api/llm        {enabled, model, source}        (never returns the key)
    POST /api/llm        {action: set|clear|test, api_key?, model?}
"""

import difflib
import json
import os
import re
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from ..copilot import CopilotSession
from ..copilot.knowledge import LEVELS
from ..copilot.llm import DEFAULT_MODEL, GeminiClient, LLMError
from ..digital_twin.twin_report import build_twin_data
from ..frontend.detect import detect_language
from ..ir.ir_printer import print_function, print_program
from ..reporting.report_generator import build_report_data
from .page import PAGE_HTML

SAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
LANG_BY_EXT = {".py": "python", ".c": "c", ".cpp": "cpp", ".java": "java"}
MAX_BODY = 1_000_000
MAX_CODE = 50_000
MAX_SESSIONS = 50


_MODEL_RE = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{8,200}$")
_LINE_RE = re.compile(r"line (\d+)")


def _diff_rows(before: str, after: str):
    a, b = before.splitlines(), after.splitlines()
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        left, right = a[i1:i2], b[j1:j2]
        for k in range(max(len(left), len(right))):
            l = left[k] if k < len(left) else ""
            r = right[k] if k < len(right) else ""
            kind = "same" if tag == "equal" else ("chg" if k < len(left) and k < len(right) else ("del" if k < len(left) else "add"))
            rows.append([l, r, kind])
    return rows


def analyze(code: str, language: str, function: Optional[str] = None, ml_selector=None, session=None):
    """Run the whole pipeline and return one JSON-serialisable dict (plus the live Copilot session)."""
    if not code.strip():
        raise ValueError("no code given")
    if language == "auto":
        language = detect_language(code)
    if language not in LANG_BY_EXT.values():
        raise ValueError(f"language must be one of {sorted(LANG_BY_EXT.values())} (or 'auto')")
    if len(code) > MAX_CODE:
        raise ValueError(f"code is too long (limit {MAX_CODE} characters)")

    s = CopilotSession(code, language, function, ml_selector=ml_selector)
    fr = s.fr
    report_fn = next(f for f in build_report_data(s.report)["functions"] if f["name"] == s.func_name)
    experiments = s.experiments
    twin_data = build_twin_data(s.twin, experiments, s.recommendation, s.twin.accuracy(experiments))

    refactoring = None
    r = s.refactoring
    if r and r["valid"]:
        final = r["combined_func"] if r["combined_valid"] and r["combined_func"] is not None else r["func"]
        cost = r["combined_cost"] if r["combined_valid"] else r["predicted_cost"]
        base = s.twin.baseline.predicted_cost
        refactoring = {"summary": f"{r['changes'][0].description}"
                                  f"{' (+' + str(len(r['changes']) - 1) + ' more)' if len(r['changes']) > 1 else ''}; "
                                  f"with the compiler passes on top: predicted cost {cost:.0f} vs {base:.0f} "
                                  f"({round(100.0 * (base - cost) / base, 1) if base else 0}% lower). Verified equivalent on "
                                  f"{r['validation'].tests_conclusive} tests.",
                       "code": print_function(final)}

    opt = s.optimized_source()
    optimized = {k: opt[k] for k in ("code", "original", "strategy", "cost_before", "cost_after", "saving_pct", "why")}
    optimized["diff"] = _diff_rows(opt["original"], opt["code"])

    return {
        "language": language, "functions": [f.name for f in s.program.functions], "function": s.func_name,
        "line_count": len(code.splitlines()), "ir": print_program(s.program),
        "features": fr.features_before.to_dict(),
        "selection": report_fn["selection"],
        "ml_selection": None if s.ml_recs is None else [{"pass": x.pass_name, "confidence": x.confidence,
                                                         "selected": x.selected, "reason": x.reason} for x in s.ml_recs],
        "ml_eval": None if ml_selector is None or ml_selector.eval_report is None else {
            "overall": ml_selector.eval_report.overall_accuracy, "baseline": ml_selector.eval_report.baseline_accuracy},
        "optimization": {k: report_fn[k] for k in ("changes", "change_counts", "explanations", "rejected",
                                                    "code_before", "code_after", "validation", "metrics")}
                        | {"diff": _diff_rows(report_fn["code_before"], report_fn["code_after"])},
        "twin": {k: twin_data[k] for k in ("baseline", "strategies", "history", "recommendation", "accuracy")},
        "hotspots": [{"line": h["line"], "code": h["code"], "share_pct": h["share_pct"]} for h in s.hotspots()],
        "suggestions": [{"kind": x.kind, "line": x.line, "severity": x.severity, "message": x.message, "fix": x.fix}
                        for x in s.suggestions],
        "refactoring": refactoring,
        "optimized": optimized,
        "alerts": s.alerts(),
    }, s


def _samples():
    out = {}
    if os.path.isdir(SAMPLES_DIR):
        for name in sorted(os.listdir(SAMPLES_DIR)):
            ext = os.path.splitext(name)[1]
            if ext in LANG_BY_EXT and name.startswith(("twin_demo", "optimize_demo")):
                with open(os.path.join(SAMPLES_DIR, name), encoding="utf-8") as fh:
                    out[name] = {"language": LANG_BY_EXT[ext], "code": fh.read()}
    return out


def make_server(host: str = "127.0.0.1", port: int = 8765, ml_selector=None, llm=None) -> ThreadingHTTPServer:
    """`llm`: a GeminiClient (or anything with .generate/.available/.model); default reads GEMINI_API_KEY."""
    sessions: "OrderedDict[str, CopilotSession]" = OrderedDict()
    lock = threading.Lock()
    client = llm if llm is not None else GeminiClient()
    key_source = {"value": "env" if getattr(client, "api_key", "") else "none"}

    def llm_status():
        return {"enabled": bool(client.available), "model": getattr(client, "model", DEFAULT_MODEL),
                "source": key_source["value"] if client.available else "none"}

    def llm_action(data):
        action = str(data.get("action", "set"))
        model = data.get("model")
        if model not in (None, ""):
            if not _MODEL_RE.match(str(model)):
                raise ValueError("invalid model name")
            client.model = str(model)
        if action == "clear":
            client.api_key = ""
            key_source["value"] = "none"
        elif action == "set":
            key = data.get("api_key")
            if key not in (None, ""):
                if not _KEY_RE.match(str(key)):
                    raise ValueError("that does not look like an API key")
                client.api_key = str(key)
                key_source["value"] = "ui"
        elif action == "test":
            if not client.available:
                return {**llm_status(), "ok": False, "error": "no API key is configured"}
            try:
                reply = client.generate("Reply with the single word OK.")
                return {**llm_status(), "ok": True, "reply": reply[:80]}
            except LLMError as e:
                return {**llm_status(), "ok": False, "error": str(e)}
        else:
            raise ValueError("unknown action")
        return llm_status()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):          # keep the console quiet
            pass

        def _send(self, status, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else (
                payload.encode("utf-8") if ctype.startswith("text/") else json.dumps(payload).encode("utf-8"))
            self.send_response(status)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("request too large")
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                raise ValueError("body is not valid JSON")
            if not isinstance(data, dict):
                raise ValueError("body must be a JSON object")
            return data

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE_HTML, "text/html")
            elif self.path == "/api/samples":
                self._send(200, _samples())
            elif self.path == "/api/health":
                self._send(200, {"status": "ok", "ml": ml_selector is not None})
            elif self.path == "/api/llm":
                self._send(200, llm_status())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                data = self._json_body()
                if self.path == "/api/analyze":
                    result, session = analyze(str(data.get("code", "")), str(data.get("language", "")),
                                              data.get("function") or None, ml_selector)
                    sid = uuid.uuid4().hex
                    with lock:
                        sessions[sid] = session
                        while len(sessions) > MAX_SESSIONS:
                            sessions.popitem(last=False)
                    result["session_id"] = sid
                    self._send(200, result)
                elif self.path == "/api/llm":
                    self._send(200, llm_action(data))
                elif self.path == "/api/chat":
                    with lock:
                        session = sessions.get(str(data.get("session_id", "")))
                    if session is None:
                        raise ValueError("unknown session - press Analyze first")
                    message = str(data.get("message", "")).strip()
                    if not message:
                        raise ValueError("empty message")
                    level = data.get("level")
                    if level in LEVELS:
                        session.level = level
                    session.set_llm(client if client.available else None)
                    ans = session.ask(message[:500])
                    self._send(200, {"text": ans.text, "intent": ans.intent, "followups": ans.followups,
                                     "level": session.level, "llm": bool(ans.data.get("llm")),
                                     "llm_error": ans.data.get("llm_error")})
                else:
                    self._send(404, {"error": "not found"})
            except ValueError as e:
                m = _LINE_RE.search(str(e))
                self._send(400, {"error": str(e), "line": int(m.group(1)) if m else None})
            except Exception as e:                      # never leak a traceback to the browser
                self._send(500, {"error": f"internal error: {type(e).__name__}"})

    return ThreadingHTTPServer((host, port), Handler)