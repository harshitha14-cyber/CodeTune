"""
Milestone 3 tests: semantic validation (differential testing) and reporting.

The most important tests deliberately plug in WRONG optimization passes and
check that validation catches and rolls them back.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from codetune.frontend.parser import parse_file, parse_source
from codetune.ir import ir_nodes as ir
from codetune.ir.ir_utils import clone, walk_stmts
from codetune.ir.translators import get_translator
from codetune.optimizer.base import Change, OptimizationPass, PassResult, map_exprs_in_block
from codetune.optimizer.pass_manager import optimize_program
from codetune.reporting.report_generator import (build_report_data, to_html, to_json, to_markdown,
                                                 write_report)
from codetune.validation import FunctionValidator, generate_inputs

HERE = os.path.dirname(__file__)
SAMPLES = os.path.join(os.path.dirname(__file__), "data")
SAMPLES = os.path.join(HERE, "data")
DEMO = os.path.join(HERE, "..", "demo.py")


def compile_src(code, lang):
    tree, src = parse_source(code, lang)
    assert not tree.root_node.has_error
    return get_translator(lang, src).translate_program(tree.root_node)


def load_sample(name):
    tree, src, lang = parse_file(os.path.join(SAMPLES, name))
    return get_translator(lang, src).translate_program(tree.root_node)


# ----------------------------------------------------------- deliberately wrong passes

class MulBecomesAdd(OptimizationPass):
    """WRONG: rewrites every `a * b` as `a + b`."""
    name = "mul_becomes_add"

    def run(self, func, language):
        new, changes = clone(func), []

        def fix(e):
            if isinstance(e, ir.BinOp):
                e.left, e.right = fix(e.left), fix(e.right)
                if e.op == "*":
                    e.op = "+"
                    changes.append(Change(self.name, e.line, "* -> +"))
            return e
        map_exprs_in_block(new.body, fix)
        return PassResult(new, changes)


class BlindShift(OptimizationPass):
    """WRONG for Python: assumes every `x * 8` has an int x (type never checked)."""
    name = "blind_shift"

    def run(self, func, language):
        new, changes = clone(func), []

        def fix(e):
            if isinstance(e, ir.BinOp):
                e.left, e.right = fix(e.left), fix(e.right)
                if e.op == "*" and isinstance(e.right, ir.Literal) and e.right.value == 8:
                    e.op, e.right = "<<", ir.Literal(value=3, type="int", line=e.line)
                    changes.append(Change(self.name, e.line, "* 8 -> << 3"))
            return e
        map_exprs_in_block(new.body, fix)
        return PassResult(new, changes)


class BreakLoop(OptimizationPass):
    """WRONG: turns `i = i + 1` into `i = i + 0`, so loops never end."""
    name = "break_loop"

    def run(self, func, language):
        new, changes = clone(func), []
        for s in walk_stmts(new.body):
            if isinstance(s, ir.Assign) and isinstance(s.value, ir.BinOp) and s.value.op == "+" \
                    and isinstance(s.value.right, ir.Literal) and s.value.right.value == 1:
                s.value.right.value = 0
                changes.append(Change(self.name, s.line, "+ 1 -> + 0"))
        return PassResult(new, changes)


# ----------------------------------------------------------- input generation

def test_inputs_include_boundaries_and_are_deterministic():
    prog = compile_src("int f(int a, int b) {\n    return a + b;\n}\n", "c")
    func = prog.functions[0]
    cases = generate_inputs(func, "c", max_cases=100)
    assert cases == generate_inputs(func, "c", max_cases=100)          # reproducible
    assert 0 < len(cases) <= 100
    flat = {v for c in cases for v in c}
    assert {0, 1, -1, 2 ** 31 - 1, -2 ** 31} <= flat                   # boundary values present


def test_python_inputs_include_floats_because_types_are_unknown():
    prog = compile_src("def f(n):\n    return n\n", "python")
    flat = [v for c in generate_inputs(prog.functions[0], "python") for v in c]
    assert any(isinstance(v, float) for v in flat) and any(isinstance(v, int) for v in flat)


# ----------------------------------------------------------- validator

def test_validator_accepts_equivalent_and_measures_cost():
    prog = compile_src("int f(int n) {\n    return n * 8;\n}\n", "c")
    good = clone(prog.functions[0])
    good.body.statements[0].value = ir.BinOp(op="<<", left=ir.Identifier(name="n"),
                                             right=ir.Literal(value=3, type="int"))
    res = FunctionValidator(prog, "f").check(good)
    assert res.passed and res.tests_conclusive > 10 and not res.mismatches


def test_validator_catches_wrong_candidate_with_a_counterexample():
    prog = compile_src("int f(int n) {\n    return n * 8;\n}\n", "c")
    bad = clone(prog.functions[0])
    bad.body.statements[0].value.op = "+"
    res = FunctionValidator(prog, "f").check(bad)
    assert not res.passed and res.mismatches
    assert "original" in str(res.mismatches[0])


def test_validator_catches_a_python_rewrite_that_is_only_valid_for_ints():
    prog = compile_src("def f(n):\n    return n * 8\n", "python")
    bad = clone(prog.functions[0])
    bad.body.statements[0].value = ir.BinOp(op="<<", left=ir.Identifier(name="n"),
                                            right=ir.Literal(value=3, type="int"))
    res = FunctionValidator(prog, "f").check(bad)
    assert not res.passed                      # float input: original ok, shift raises


def test_validator_flags_non_termination():
    prog = compile_src("int f(int n) {\n    int i = 0;\n    while (i < 3) {\n        i = i + 1;\n    }\n"
                       "    return i;\n}\n", "c")
    bad = clone(prog.functions[0])
    loop = next(s for s in walk_stmts(bad.body) if isinstance(s, ir.While))
    loop.body.statements[0].value.right.value = 0
    res = FunctionValidator(prog, "f").check(bad)
    assert not res.passed and "did not terminate" in res.mismatches[0].optimized


def test_validator_distinguishes_int_from_float_results():
    prog = compile_src("def f():\n    return 4\n", "python")
    bad = clone(prog.functions[0])
    bad.body.statements[0].value = ir.Literal(value=4.0, type="float")
    assert not FunctionValidator(prog, "f").check(bad).passed


def test_validator_warns_when_comparison_is_vacuous():
    prog = compile_src("int f(int n) {\n    return mystery(n);\n}\n", "c")      # undefined callee
    res = FunctionValidator(prog, "f").check(clone(prog.functions[0]))
    assert res.passed and res.warnings


# ----------------------------------------------------------- rollback in the pipeline

def _run_with(code, lang, wrong_pass, extra=("constant_folding",)):
    prog = compile_src(code, lang)
    return optimize_program(prog, passes=[wrong_pass.name, *extra], validate=True,
                            pass_overrides={wrong_pass.name: wrong_pass})


def test_pipeline_rolls_back_a_wrong_pass_and_keeps_the_good_one():
    code = "int f(int n) {\n    int k = 2 * 3;\n    return n * 4 + k;\n}\n"
    rep = _run_with(code, "c", MulBecomesAdd())
    fr = rep.functions["f"]
    assert [r.pass_name for r in fr.rejected] == ["mul_becomes_add"]
    assert "mul_becomes_add" not in fr.applied_passes and "constant_folding" in fr.applied_passes
    assert fr.validation.passed and rep.all_validated
    assert any(c.pass_name == "constant_folding" for c in fr.changes)     # good pass still applied
    assert not any(c.pass_name == "mul_becomes_add" for c in fr.changes)  # bad one fully undone


def test_pipeline_rejects_python_blind_shift():
    rep = _run_with("def f(n):\n    return n * 8\n", "python", BlindShift(), extra=())
    fr = rep.functions["f"]
    assert fr.rejected and fr.validation.passed
    assert "<<" not in rep.to_text().split("After:")[1]


def test_pipeline_rejects_non_terminating_rewrite():
    code = "int f(int n) {\n    int i = 0;\n    while (i < 3) {\n        i = i + 1;\n    }\n    return i;\n}\n"
    rep = _run_with(code, "c", BreakLoop(), extra=())
    assert rep.functions["f"].rejected and rep.all_validated


@pytest.mark.parametrize("fname", ["optimize_demo.py", "optimize_demo.c", "optimize_demo.cpp",
                                   "optimize_demo.java"])
def test_real_passes_are_validated_on_all_samples(fname):
    rep = optimize_program(load_sample(fname), validate=True)
    fr = rep.functions["demo"]
    assert fr.validation.passed and not fr.rejected
    assert fr.validation.optimized_cost < fr.validation.original_cost


# ----------------------------------------------------------- reporting

@pytest.fixture(scope="module")
def demo_report():
    return optimize_program(load_sample("optimize_demo.c"), validate=True)


def test_report_data_has_everything_the_project_report_promises(demo_report):
    data = build_report_data(demo_report)
    f = data["functions"][0]
    assert f["features_before"] and f["features_after"]
    assert f["selection"] and all(0 <= s["confidence"] <= 1 and s["reason"] for s in f["selection"])
    assert f["code_before"] != f["code_after"]
    assert f["validation"]["passed"] and f["validation"]["cost_reduction_pct"] > 0
    assert f["explanations"] and f["changes"]
    json.loads(to_json(data))                                  # fully serialisable


def test_markdown_and_html_render(demo_report):
    data = build_report_data(demo_report)
    md, html_text = to_markdown(data), to_html(data)
    for needle in ("Pass selection", "Semantic validation", "PASSED", "constant_folding", "confidence"):
        assert needle.lower() in md.lower()
    assert "<table" in html_text and "Before" in html_text and "<script" not in html_text


def test_html_escapes_code():
    prog = compile_src("int f(int n) {\n    return n < 5;\n}\n", "c")
    html_text = to_html(build_report_data(optimize_program(prog, validate=True)))
    assert "&lt;" in html_text and "(n < 5)" not in html_text


def test_write_report_creates_three_files(tmp_path, demo_report):
    paths = write_report(demo_report, str(tmp_path), basename="x")
    assert set(paths) == {"md", "html", "json"}
    for p in paths.values():
        assert os.path.getsize(p) > 200


def test_cli_end_to_end(tmp_path):
    out = subprocess.run([sys.executable, DEMO, os.path.join(SAMPLES, "optimize_demo.c"),
                          "--optimize", "--report", str(tmp_path)],
                         capture_output=True, text=True, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert "Validation: PASSED" in out.stdout
    assert (tmp_path / "optimize_demo.html").exists()