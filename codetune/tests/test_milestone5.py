"""
Milestone 5 tests: ML pass selector, Copilot (+ refactoring), dashboard API.
"""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from codetune.copilot import CopilotSession, classify, find_suggestions, hoist_loop_invariants
from codetune.dashboard import make_server
from codetune.dashboard.page import PAGE_HTML
from codetune.digital_twin import DigitalTwin
from codetune.frontend.parser import parse_source
from codetune.ir.ir_printer import print_function
from codetune.ir.translators import get_translator
from codetune.ml import DecisionTree, MLPassSelector, RandomForest, featurize
from codetune.ml.corpus import LANGUAGES, generate_corpus, oracle_labels
from codetune.ml.ml_selector import FEATURE_NAMES
from codetune.optimizer.pass_manager import optimize_program
from codetune.optimizer.registry import PASS_ORDER
from codetune.validation import FunctionValidator

HERE = os.path.dirname(__file__)
SAMPLES = os.path.join(os.path.dirname(__file__), "data")
SAMPLES = os.path.join(HERE, "data")
ROOT = os.path.join(HERE, "..")


def sample(name):
    with open(os.path.join(SAMPLES, name), encoding="utf-8") as fh:
        return fh.read()


def program(code, lang):
    tree, src = parse_source(code, lang)
    assert not tree.root_node.has_error
    return get_translator(lang, src).translate_program(tree.root_node)


HOIST_C = """int f(int n, int a, int b) {
    int s = 0;
    int i = 0;
    while (i < 8) {
        s = s + a * b + i;
        i = i + 1;
    }
    int u = n * n + 1;
    int w = n * n + 2;
    return s + u + w;
}
"""


@pytest.fixture(scope="module")
def ml():
    return MLPassSelector.train(n_programs=1200, seed=0)


# =============================================================== decision tree / forest

def test_tree_learns_a_threshold_and_explains_itself():
    X = [[float(i), float(i % 3)] for i in range(40)]
    y = [1 if i > 20 else 0 for i in range(40)]
    t = DecisionTree(max_depth=3).fit(X, y, ["size", "noise"])
    assert all(t.predict(x) == yy for x, yy in zip(X, y))
    assert t.predict_proba([30.0, 0.0]) == 1.0 and t.predict_proba([5.0, 0.0]) == 0.0
    assert t.decision_path([30.0, 0.0])[0].startswith("size >")
    assert "if size <=" in t.to_rules() and "P(useful)" in t.to_rules()


def test_tree_on_constant_labels_is_a_single_leaf():
    t = DecisionTree().fit([[1.0], [2.0], [3.0]], [1, 1, 1], ["x"])
    assert t.predict_proba([9.0]) == 1.0 and t.decision_path([9.0]) == []


def test_forest_probabilities_and_serialisation_round_trip():
    X = [[float(i)] for i in range(60)]
    y = [1 if i >= 30 else 0 for i in range(60)]
    f = RandomForest(n_trees=7, max_depth=3, seed=1).fit(X, y, ["x"])
    p = f.predict_proba([55.0])
    assert 0.0 <= p <= 1.0 and f.predict([55.0]) == 1 and f.predict([2.0]) == 0
    g = RandomForest.from_dict(json.loads(json.dumps(f.to_dict())))
    assert all(f.predict_proba([float(i)]) == g.predict_proba([float(i)]) for i in range(0, 60, 7))


# =============================================================== corpus / labels

def test_corpus_is_deterministic_covers_all_languages_and_both_classes():
    a, b = generate_corpus(160, seed=3), generate_corpus(160, seed=3)
    assert [print_function(x[0]) for x in a] == [print_function(x[0]) for x in b]
    assert {x[1] for x in a} == set(LANGUAGES)
    for p in PASS_ORDER:
        vals = {x[2][p] for x in a}
        assert vals == {0, 1}, f"{p} needs both positive and negative examples"


def test_oracle_labels_match_the_real_optimizer():
    demo = program(sample("twin_demo.c"), "c").functions[0]
    assert oracle_labels(demo, "c") == {p: 1 for p in PASS_ORDER}
    trivial = program("int f(int x) {\n    return x;\n}\n", "c").functions[0]
    assert oracle_labels(trivial, "c") == {p: 0 for p in PASS_ORDER}


# =============================================================== ML selector

def test_ml_selector_meets_the_report_accuracy_target_and_beats_the_baseline(ml):
    r = ml.eval_report
    assert r.overall_accuracy > 0.75 and r.meets_target                # report: > 75%
    assert r.overall_accuracy > r.baseline_accuracy + 0.03
    assert "MET" in r.to_text()
    assert set(r.per_pass) == set(PASS_ORDER)


def test_ml_recommendations_have_confidence_and_a_readable_reason(ml):
    f = program(sample("twin_demo.c"), "c").functions[0]
    recs = ml.select(f, "c")
    assert [r.pass_name for r in recs] == PASS_ORDER
    for r in recs:
        assert 0.0 <= r.confidence <= 1.0 and "P(useful)" in r.reason
        assert isinstance(r.evidence["decision_path"], list)
    assert sum(r.selected for r in recs) >= 3
    assert "if " in ml.explain("strength_reduction")


def test_ml_selector_skips_constant_passes_on_code_with_no_constants(ml):
    f = program("int f(int x) {\n    return x;\n}\n", "c").functions[0]
    sel = {r.pass_name for r in ml.select(f, "c") if r.selected}
    assert "constant_folding" not in sel and "constant_propagation" not in sel


@pytest.mark.parametrize("name", ["twin_demo.c", "twin_demo.cpp", "twin_demo.java", "twin_demo.py"])
def test_ml_selector_plugs_into_the_validated_pipeline(ml, name):
    lang = {"c": "c", "cpp": "cpp", "java": "java", "py": "python"}[name.rsplit(".", 1)[1]]
    report = optimize_program(program(sample(name), lang), selector=ml, validate=True)
    assert report.all_validated and report.total_changes > 0


def test_ml_save_load_roundtrip_and_load_or_train(ml, tmp_path):
    path = str(tmp_path / "m.json")
    ml.save(path)
    again = MLPassSelector.load(path)
    f = program(sample("twin_demo.c"), "c").functions[0]
    assert [r.confidence for r in ml.select(f, "c")] == [r.confidence for r in again.select(f, "c")]
    assert again.eval_report.overall_accuracy == pytest.approx(ml.eval_report.overall_accuracy)

    fresh = str(tmp_path / "new.json")
    sel = MLPassSelector.load_or_train(fresh, n_programs=80, seed=2)
    assert os.path.exists(fresh) and len(sel.models) == 4

    blob = json.load(open(path))
    blob["features"] = blob["features"][:-1]
    json.dump(blob, open(path, "w"))
    with pytest.raises(ValueError):
        MLPassSelector.load(path)


def test_training_is_reproducible():
    a, b = MLPassSelector.train(n_programs=120, seed=5), MLPassSelector.train(n_programs=120, seed=5)
    f = program(sample("twin_demo.c"), "c").functions[0]
    assert [r.confidence for r in a.select(f, "c")] == [r.confidence for r in b.select(f, "c")]
    assert len(FEATURE_NAMES) == len(featurize(__import__("codetune.analysis.feature_extractor", fromlist=["x"]).FeatureExtractor().extract(f), "c"))


# =============================================================== refactoring

def test_hoisting_moves_invariant_work_out_of_the_loop_and_is_verified():
    t = DigitalTwin.from_source(HOIST_C, "c")
    new, changes = hoist_loop_invariants(t.original, "c")
    text = print_function(new)
    assert changes and "_hoisted1 = (a * b)" in text and "s + _hoisted1" in text
    assert text.index("_hoisted1 =") < text.index("while")
    assert t.validator.check(new).passed
    assert t._metrics(new).predicted_cost < t.baseline.predicted_cost


@pytest.mark.parametrize("lang,code", [
    ("python", "def f(a, b):\n    s = 0\n    i = 0\n    while i < 8:\n        s = s + a * b\n        i = i + 1\n    return s\n"),
    ("java", "class T {\n    int f(int a, int b) {\n        int s = 0;\n        int i = 0;\n        while (i < 8) {\n"
             "            s = s + a * b;\n            i = i + 1;\n        }\n        return s;\n    }\n}\n"),
])
def test_hoisting_works_in_python_and_java(lang, code):
    t = DigitalTwin.from_source(code, lang)
    new, changes = hoist_loop_invariants(t.original, lang)
    assert changes and t.validator.check(new).passed


def test_hoisting_leaves_loop_variant_or_impure_code_alone():
    variant = ("int f(int n) {\n    int s = 0;\n    int i = 0;\n    int k = 3;\n    while (i < 5) {\n"
               "        k = k + 1;\n        s = s + k * n;\n        i = i + 1;\n    }\n    return s;\n}\n")
    call = ("int g(int x) {\n    return x;\n}\nint f(int n) {\n    int s = 0;\n    int i = 0;\n    while (i < 5) {\n"
            "        s = s + g(n) * n;\n        i = i + 1;\n    }\n    return s;\n}\n")
    division = ("int f(int n, int d) {\n    int s = 0;\n    int i = 0;\n    while (i < 5) {\n"
                "        s = s + n / d;\n        i = i + 1;\n    }\n    return s;\n}\n")
    for code, fname in ((variant, "f"), (call, "f"), (division, "f")):
        p = program(code, "c")
        func = next(f for f in p.functions if f.name == fname)
        assert hoist_loop_invariants(func, "c")[1] == [], code      # k changes / call / may trap


def test_hoisted_names_never_clash_with_existing_variables():
    code = HOIST_C.replace("int s = 0;", "int s = 0;\n    int _hoisted1 = 5;").replace("return s + u + w;", "return s + u + w + _hoisted1;")
    t = DigitalTwin.from_source(code, "c")
    new, changes = hoist_loop_invariants(t.original, "c")
    assert "_hoisted2" in print_function(new) and t.validator.check(new).passed


def test_hoisting_preserves_behaviour_on_hundreds_of_random_programs():
    checked = changed = 0
    for func, lang, _ in generate_corpus(240, seed=11):
        prog = type(program("int f(int n) {\n    return n;\n}\n", "c"))(source_language=lang, functions=[func])
        new, ch = hoist_loop_invariants(func, lang)
        checked += 1
        if ch:
            changed += 1
            assert FunctionValidator(prog, "f", max_cases=40).check(new).passed, print_function(func)
    assert checked == 240 and changed >= 5


def test_suggestion_analysers_find_the_expected_patterns():
    kinds = lambda code, lang: {s.kind for s in find_suggestions(
        program(code, lang).functions[-1], program(code, lang), lang)}
    assert {"hoist", "cse"} <= kinds(HOIST_C, "c")
    assert "unused" in kinds("int f(int n) {\n    int dead = n * 3;\n    return n;\n}\n", "c")
    assert "loop_bound" in kinds("int f(int n) {\n    int i = 0;\n    while (i < n) {\n        i = i + 1;\n    }\n    return i;\n}\n", "c")
    assert "heavy_op_in_loop" in kinds("int f(int n) {\n    int i = 1;\n    int s = 0;\n    while (i < 9) {\n        s = s + n / i;\n"
                                       "        i = i + 1;\n    }\n    return s;\n}\n", "c")
    assert "untyped" in kinds("def f(n):\n    return n\n", "python")


# =============================================================== copilot

QUESTIONS = [
    ("why is this loop slow?", "slow"), ("what is the bottleneck", "slow"),
    ("how can I optimize this function?", "optimize"), ("any tips to speed up?", "optimize"),
    ("what changed?", "changes"), ("why did you change line 7?", "changes"), ("why did you remove waste?", "changes"),
    ("what if I apply CP before SR?", "whatif"), ("what if I only apply dce", "whatif"),
    ("apply strength reduction after constant propagation", "whatif"),
    ("is it safe?", "safety"), ("will this break my program", "safety"),
    ("which passes did you choose?", "selection"), ("how confident are you", "selection"),
    ("why did you choose constant folding?", "selection"),
    ("what is constant folding?", "learn"), ("teach me about liveness", "learn"), ("digital twin", "learn"),
    ("explain simpler", "simpler"), ("more detail please", "deeper"), ("set level advanced", "set_level"),
    ("help", "help"), ("show me the features", "features"), ("asdf qwer", "unknown"),
]


@pytest.mark.parametrize("question,intent", QUESTIONS)
def test_intent_classification(question, intent):
    assert classify(question) == intent


@pytest.fixture(scope="module")
def session():
    return CopilotSession(sample("twin_demo.c"), "c")


def test_slow_answer_points_at_the_loop_with_real_numbers(session):
    a = session.ask("why is this loop slow?")
    assert a.intent == "slow" and "loop at line 6" in a.text and "iterations" in a.text
    top = a.data["hotspots"][0]
    assert top["kind"] == "While" and top["share_pct"] > 50 and top["trips"] == 10


def test_optimize_answer_quotes_the_twin_and_validation(session):
    a = session.ask("how can I optimize this function?")
    assert "adaptive" in a.text or "canonical" in a.text
    assert "27.0% lower" in a.text and "0 mismatches" in a.text


def test_optimize_offers_a_verified_refactoring_when_passes_cannot_help():
    s = CopilotSession(HOIST_C, "c")
    a = s.ask("how can I optimize this function?")
    assert "find nothing to improve" in a.text and "Refactoring I verified" in a.text
    assert "_hoisted1" in a.text and a.data["refactoring_gain_pct"] > 10
    r = s.refactoring
    assert r["valid"] and r["combined_valid"] and r["combined_cost"] < s.twin.baseline.predicted_cost


def test_changes_can_be_filtered_by_line(session):
    a = session.ask("why did you change line 7?")
    assert a.data["count"] == 2 and "(i << 3)" in a.text
    b = session.ask("why did you change line 1?")
    assert "Nothing was changed on line 1" in b.text


def test_whatif_order_agrees_with_the_digital_twin(session):
    a = session.ask("what if I apply constant propagation before strength reduction?")
    assert "Apply CP before SR" in a.text
    assert a.data["verdict"] == session.twin.what_if_order("CP", "SR")["verdict"]
    b = session.ask("what if I apply strength reduction after constant propagation?")
    assert "Apply CP before SR" in b.text                      # same question, other wording
    c = session.ask("what if I only apply dead code elimination?")
    assert "cheaper than the original" in c.text


def test_safety_selection_and_features_answers(session):
    assert "PASSED" in session.ask("is it safe?").text
    sel = session.ask("which passes did you choose and how sure are you?").text
    assert "confidence 0.85" in sel and "constant_propagation" in sel
    assert "loop(s)" in session.ask("show me the features").text


def test_learning_mode_adapts_to_level_and_links_to_the_users_code():
    s = CopilotSession(sample("twin_demo.c"), "c", level="beginner")
    beginner = s.ask("what is constant folding?").text
    assert "like writing 6 on a form" in beginner and "In YOUR code" in beginner
    s.ask("set level advanced")
    advanced = s.ask("what is constant folding?").text
    assert "operational" in advanced and advanced != beginner
    simpler = s.ask("explain simpler")
    assert s.level == "intermediate" and simpler.text.startswith("(level: intermediate)")
    s.ask("explain simpler")
    assert "already at the beginner level" in s.ask("explain simpler").text
    s.ask("more detail please")
    assert s.level == "intermediate"


def test_ml_opinion_appears_in_the_selection_answer(ml):
    s = CopilotSession(sample("twin_demo.c"), "c", ml_selector=ml)
    text = s.ask("which passes did you choose?").text
    assert "ML selector" in text and "agree on" in text


def test_alerts_are_proactive_and_specific(session):
    alerts = " ".join(session.alerts())
    assert "'waste' is assigned but never read" in alerts and "27.0%" in alerts


def test_llm_hook_rephrases_but_keeps_the_facts_and_survives_failures():
    seen = []
    s = CopilotSession(sample("twin_demo.c"), "c", llm=lambda prompt: seen.append(prompt) or "FRIENDLY ANSWER")
    a = s.ask("is it safe?")
    assert a.text == "FRIENDLY ANSWER" and "PASSED" in a.data["facts"]
    assert "ONLY the facts" in seen[0] and "PASSED" in seen[0]

    broken = CopilotSession(sample("twin_demo.c"), "c", llm=lambda prompt: 1 / 0)
    b = broken.ask("is it safe?")
    assert "PASSED" in b.text and "ZeroDivisionError" in b.data["llm_error"]


def test_update_source_resynchronises_the_whole_context():
    s = CopilotSession(sample("twin_demo.c"), "c")
    old = s.twin.baseline.predicted_cost
    s.update_source(sample("twin_demo.c").replace("i < 10", "i < 40"))
    assert s.twin.baseline.predicted_cost > old * 2
    assert "40 iterations" in s.ask("why is this slow?").text or "about 40" in s.ask("why is this slow?").text


def test_bad_input_raises_a_clear_error():
    with pytest.raises(ValueError, match="syntax error"):
        CopilotSession("int f( {", "c")
    with pytest.raises(ValueError, match="unsupported"):
        CopilotSession("int f(int n) {\n    return n > 0 ? 1 : 2;\n}\n", "c")
    with pytest.raises(ValueError):
        CopilotSession(sample("twin_demo.c"), "c", level="expert")


@pytest.mark.parametrize("name,lang", [("twin_demo.py", "python"), ("twin_demo.java", "java"), ("twin_demo.cpp", "cpp")])
def test_copilot_works_for_every_language(name, lang):
    s = CopilotSession(sample(name), lang)
    for q in ("why is this slow?", "how can I optimize this function?", "what changed?", "is it safe?"):
        assert s.ask(q).text.strip()


# =============================================================== dashboard

@pytest.fixture(scope="module")
def server(ml):
    srv = make_server(port=0, ml_selector=ml)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def call(server, method, path, body=None, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=60)
    payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
    c.request(method, path, payload, {"Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read()
    return r.status, dict(r.getheaders()), data


def test_server_is_local_only_and_serves_an_offline_page(server):
    assert server.server_address[0] == "127.0.0.1"
    status, headers, body = call(server, "GET", "/")
    html = body.decode()
    assert status == 200 and "CodeTune" in html and headers["X-Content-Type-Options"] == "nosniff"
    assert "http://" not in html and "https://" not in html          # no CDN / external resources
    assert "<script src" not in html


def test_page_javascript_is_syntactically_valid(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    js = re.search(r"<script>(.*)</script>", PAGE_HTML, re.S).group(1)
    f = tmp_path / "page.js"
    f.write_text(js, encoding="utf-8")
    out = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("name,lang", [("twin_demo.c", "c"), ("twin_demo.cpp", "cpp"),
                                       ("twin_demo.java", "java"), ("twin_demo.py", "python")])
def test_analyze_returns_the_whole_pipeline_for_every_language(server, name, lang):
    status, headers, body = call(server, "POST", "/api/analyze", {"code": sample(name), "language": lang})
    d = json.loads(body)
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    for key in ("ir", "features", "selection", "ml_selection", "ml_eval", "optimization", "twin", "hotspots",
                "suggestions", "alerts", "session_id"):
        assert key in d
    assert d["optimization"]["validation"]["passed"] and d["twin"]["recommendation"]["saving_pct"] > 15
    assert d["ml_eval"]["overall"] > 0.75 and len(d["ml_selection"]) == 4
    assert abs(sum(h["share_pct"] for h in d["hotspots"]) - 100) < 1
    assert any(row[2] != "same" for row in d["optimization"]["diff"])


def test_chat_uses_the_analysis_session_and_level(server):
    d = json.loads(call(server, "POST", "/api/analyze", {"code": sample("twin_demo.c"), "language": "c"})[2])
    status, _, body = call(server, "POST", "/api/chat", {"session_id": d["session_id"],
                                                         "message": "what is constant folding?", "level": "advanced"})
    r = json.loads(body)
    assert status == 200 and r["level"] == "advanced" and "operational" in r["text"] and r["followups"]


@pytest.mark.parametrize("body,needle", [
    ({"code": "int f( {", "language": "c"}, "syntax error"),
    ({"code": "x", "language": "cobol"}, "language must be"),
    ({"code": "   ", "language": "c"}, "no code"),
    ({"code": "a" * 60000, "language": "c"}, "too long"),
])
def test_analyze_rejects_bad_input_with_a_clear_400(server, body, needle):
    status, _, raw = call(server, "POST", "/api/analyze", body)
    assert status == 400 and needle in json.loads(raw)["error"]


def test_api_error_handling(server):
    assert call(server, "POST", "/api/analyze", raw="not json")[0] == 400
    assert call(server, "POST", "/api/analyze", raw="[1, 2]")[0] == 400
    assert call(server, "POST", "/api/chat", {"session_id": "nope", "message": "hi"})[0] == 400
    assert call(server, "GET", "/nothing")[0] == 404
    assert call(server, "POST", "/nothing", {})[0] == 404
    assert call(server, "GET", "/api/health")[0] == 200
    samples = json.loads(call(server, "GET", "/api/samples")[2])
    assert "twin_demo.c" in samples and samples["twin_demo.py"]["language"] == "python"


# =============================================================== command-line tools

def run(cmd, tmp):
    return subprocess.run([sys.executable] + cmd, capture_output=True, text=True, cwd=str(tmp), timeout=300)


def test_train_selector_cli(tmp_path):
    out = run([os.path.join(ROOT, "train_selector.py"), "--programs", "160", "--out", str(tmp_path / "m.json"),
               "--rules", "--compare", os.path.join(SAMPLES, "twin_demo.c")], tmp_path)
    assert out.returncode == 0, out.stderr
    assert "Model saved" in out.stdout and "decision rules for strength_reduction" in out.stdout and "agree" in out.stdout
    assert (tmp_path / "m.json").exists()


def test_copilot_cli_one_shot(tmp_path):
    out = run([os.path.join(ROOT, "copilot_demo.py"), os.path.join(SAMPLES, "twin_demo.py"),
               "--ask", "why is this slow?", "--ask", "what if I apply cp before sr?", "--level", "advanced"], tmp_path)
    assert out.returncode == 0, out.stderr
    assert "loop at line 6" in out.stdout and "Apply CP before SR" in out.stdout