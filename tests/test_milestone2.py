"""
Milestone 2 tests: optimization passes, pass selector, pipeline.

The key idea is DIFFERENTIAL TESTING: every optimization is checked by running
the original and the optimized IR on many inputs with the IR interpreter and
requiring identical results (or identical errors). A randomized program
generator (fuzzing) does this for hundreds of programs per language.
"""

import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from codetune.analysis.feature_extractor import FeatureExtractor
from codetune.analysis.pass_selector import RuleBasedPassSelector
from codetune.frontend.parser import parse_file, parse_source
from codetune.ir import ir_nodes as ir
from codetune.ir.interpreter import Interpreter, InterpreterError
from codetune.ir.ir_printer import print_function
from codetune.ir.translators import get_translator
from codetune.optimizer.constant_folding import ConstantFolding
from codetune.optimizer.constant_propagation import ConstantPropagation
from codetune.optimizer.dead_code_elimination import DeadCodeElimination
from codetune.optimizer.pass_manager import optimize_program
from codetune.optimizer.strength_reduction import StrengthReduction

SAMPLES = os.path.join(os.path.dirname(__file__), "data")
LANGS = ["python", "c", "cpp", "java"]


# ---------------------------------------------------------------- helpers

def compile_src(code, lang):
    tree, src = parse_source(code, lang)
    assert not tree.root_node.has_error
    return get_translator(lang, src).translate_program(tree.root_node)


def wrap_java(body):
    return "class T {\n" + body + "\n}\n"


def outcome(program, name, args):
    try:
        return ("ok", Interpreter(program).call(name, list(args)))
    except InterpreterError as e:
        return ("err", type(e).__name__)


def assert_equivalent(p1, p2, name, arg_sets):
    for args in arg_sets:
        a, b = outcome(p1, name, args), outcome(p2, name, args)
        assert a == b, f"{name}{tuple(args)}: original {a} != optimized {b}"


def run_pass(pass_cls, code, lang, fname="f"):
    prog = compile_src(code, lang)
    func = next(f for f in prog.functions if f.name == fname)
    res = pass_cls().run(func, lang)
    new_prog = ir.Program(source_language=lang, functions=[res.func if f.name == fname else f
                                                           for f in prog.functions])
    return prog, new_prog, res


INTS = [(n,) for n in range(-12, 13)]


# ---------------------------------------------------------------- constant folding

def test_folding_arithmetic_all_languages():
    srcs = {
        "python": "def f(n):\n    return n + 2 * 3 + 1\n",
        "c": "int f(int n) {\n    return n + 2 * 3 + 1;\n}\n",
        "cpp": "int f(int n) {\n    return n + 2 * 3 + 1;\n}\n",
        "java": wrap_java("int f(int n) {\n    return n + 2 * 3 + 1;\n}"),
    }
    for lang, code in srcs.items():
        before, after, res = run_pass(ConstantFolding, code, lang)
        assert len(res.changes) >= 1
        assert "6" in print_function(res.func)
        assert_equivalent(before, after, "f", INTS)


def test_folding_uses_language_division_rules():
    c_before, c_after, c_res = run_pass(ConstantFolding, "int f() {\n    return 7 / 2;\n}\n", "c")
    py_before, py_after, py_res = run_pass(ConstantFolding, "def f():\n    return 7 / 2\n", "python")
    assert c_res.func.body.statements[0].value.value == 3          # C: integer division
    assert py_res.func.body.statements[0].value.value == 3.5       # Python 3: true division
    c2 = run_pass(ConstantFolding, "int f() {\n    return -7 % 3;\n}\n", "c")[2]
    p2 = run_pass(ConstantFolding, "def f():\n    return -7 % 3\n", "python")[2]
    assert c2.func.body.statements[0].value.value == -1            # C: sign of dividend
    assert p2.func.body.statements[0].value.value == 2             # Python: sign of divisor


def test_folding_refuses_unsafe_cases():
    # division by zero must stay (the program should still fail at run time)
    res = run_pass(ConstantFolding, "int f() {\n    return 1 / 0;\n}\n", "c")[2]
    assert not res.changed
    # 32-bit overflow in C must NOT be folded to a bignum
    res = run_pass(ConstantFolding, "int f() {\n    return 2147483647 + 1;\n}\n", "c")[2]
    assert not res.changed
    # ...but Python ints are unbounded, so it IS safe there
    res = run_pass(ConstantFolding, "def f():\n    return 2147483647 + 1\n", "python")[2]
    assert res.func.body.statements[0].value.value == 2147483648


def test_folding_short_circuit_keeps_side_effects_correct():
    code = "int g(int x) {\n    return x;\n}\nint f(int n) {\n    return 0 && g(n);\n}\n"
    before, after, res = run_pass(ConstantFolding, code, "c")
    assert res.changed                                  # `0 && g(n)` -> false, g never called
    assert_equivalent(before, after, "f", INTS)


# ---------------------------------------------------------------- constant propagation

def test_propagation_basic_and_loop_safety():
    code = ("int f(int n) {\n    int a = 5;\n    int i = 0;\n    int s = 0;\n"
            "    while (i < 3) {\n        s = s + a;\n        i = i + 1;\n    }\n    return s;\n}\n")
    before, after, res = run_pass(ConstantPropagation, code, "c")
    text = print_function(res.func)
    assert "s + 5" in text                    # `a` is never reassigned -> replaced
    assert "(i < 3)" in text and "(s + 5)" in text
    # `i` and `s` change inside the loop -> must NOT be replaced by 0
    assert "(0 < 3)" not in text and "(0 + 5)" not in text
    assert_equivalent(before, after, "f", INTS)


def test_propagation_if_merge_only_keeps_agreeing_facts():
    code = ("int f(int n) {\n    int x = 1;\n    int y = 7;\n    if (n > 0) {\n        x = 2;\n"
            "    } else {\n        x = 3;\n    }\n    return x * 10 + y;\n}\n")
    before, after, res = run_pass(ConstantPropagation, code, "c")
    text = print_function(res.func)
    assert "(x * 10)" in text                 # x differs between branches -> kept as variable
    assert "+ 7" in text                      # y is 7 on both paths -> propagated
    assert_equivalent(before, after, "f", INTS)


def test_propagation_never_touches_globals():
    code = "int f(int n) {\n    counter = 5;\n    g(n);\n    return counter;\n}\nint g(int n) {\n    return n;\n}\n"
    res = run_pass(ConstantPropagation, code, "c")[2]
    assert not res.changed                    # `counter` is not a local: any call may change it


def test_propagation_respects_declared_float_type():
    code = "double f() {\n    double d = 3;\n    return d / 2;\n}\n"
    before, after, res = run_pass(ConstantPropagation, code, "c")
    assert outcome(before, "f", []) == outcome(after, "f", []) == ("ok", 1.5)


# ---------------------------------------------------------------- strength reduction

def test_strength_reduction_typed_languages_use_shifts():
    for lang, code in {
        "c": "int f(int n) {\n    return n * 8;\n}\n",
        "java": wrap_java("int f(int n) {\n    return n * 8;\n}"),
    }.items():
        before, after, res = run_pass(StrengthReduction, code, lang)
        assert "<< 3" in print_function(res.func)
        assert_equivalent(before, after, "f", INTS + [(2 ** 30,), (-2 ** 31,), (2 ** 31 - 1,)])


def test_strength_reduction_python_params_are_not_assumed_int():
    res = run_pass(StrengthReduction, "def f(n):\n    return n * 8\n", "python")[2]
    assert not res.changed                    # n could be a float or a string
    before, after, res = run_pass(StrengthReduction, "def f(n):\n    return n * 2\n", "python")
    assert "(n + n)" in print_function(res.func)  # always valid
    assert_equivalent(before, after, "f", [(3,), (2.5,), ("ab",)])


def test_strength_reduction_does_not_touch_division_or_modulo():
    code = "int f(int n) {\n    return n / 4 + n % 4;\n}\n"
    before, after, res = run_pass(StrengthReduction, code, "c")
    assert not res.changed                    # >> and & differ for negative n
    assert_equivalent(before, after, "f", INTS)


def test_algebraic_identities():
    code = "int f(int n) {\n    return n * 1 + 0 + n * 0;\n}\n"
    before, after, res = run_pass(StrengthReduction, code, "c")
    assert res.changed
    assert_equivalent(before, after, "f", INTS)


# ---------------------------------------------------------------- dead-code elimination

def test_dce_unreachable_and_constant_branch():
    code = ("int f(int n) {\n    if (1) {\n        return n;\n    } else {\n        return 0;\n    }\n"
            "    return 99;\n}\n")
    before, after, res = run_pass(DeadCodeElimination, code, "c")
    assert len(res.func.body.statements) == 1
    assert_equivalent(before, after, "f", INTS)


def test_dce_keeps_side_effects_of_dead_stores():
    code = ("int g(int x) {\n    return x;\n}\nint f(int n) {\n    int unused = g(n);\n    return n;\n}\n")
    before, after, res = run_pass(DeadCodeElimination, code, "c")
    text = print_function(res.func)
    assert "g(n)" in text                     # the call must survive
    assert "unused =" not in text             # but the useless store does not
    assert_equivalent(before, after, "f", INTS)


def test_dce_keeps_possibly_trapping_division():
    code = "int f(int n) {\n    int t = 10 / n;\n    return 1;\n}\n"
    before, after, res = run_pass(DeadCodeElimination, code, "c")
    assert "10 / n" in print_function(res.func)
    assert_equivalent(before, after, "f", INTS)       # n == 0 must still fail


def test_dce_loop_carried_value_is_live():
    code = ("int f(int n) {\n    int t = 0;\n    int s = 0;\n    int i = 0;\n"
            "    while (i < 4) {\n        s = s + t;\n        t = i;\n        i = i + 1;\n    }\n    return s;\n}\n")
    before, after, res = run_pass(DeadCodeElimination, code, "c")
    assert "t = i" in print_function(res.func)        # read by the NEXT iteration
    assert_equivalent(before, after, "f", INTS)


def test_dce_never_removes_stores_to_non_locals():
    res = run_pass(DeadCodeElimination, "int f(int n) {\n    total = n;\n    return 1;\n}\n", "c")[2]
    assert not res.changed                    # `total` is a global / field


def test_dce_removes_while_false():
    before, after, res = run_pass(
        DeadCodeElimination, "int f(int n) {\n    while (0) {\n        n = n + 1;\n    }\n    return n;\n}\n", "c")
    assert not any(isinstance(s, ir.While) for s in res.func.body.statements)
    assert_equivalent(before, after, "f", INTS)


# ---------------------------------------------------------------- selector

def test_selector_skips_everything_on_code_with_nothing_to_optimize():
    prog = compile_src("int f(int x) {\n    return x;\n}\n", "c")
    recs = RuleBasedPassSelector().select(prog.functions[0], "c")
    assert not any(r.selected for r in recs)
    report = optimize_program(prog)
    assert report.total_changes == 0
    assert report.functions["f"].applied_passes == []


def test_selector_confidence_is_valid_and_explained():
    prog = compile_src(open(os.path.join(SAMPLES, "optimize_demo.c")).read(), "c")
    recs = RuleBasedPassSelector().select(prog.functions[0], "c")
    assert {r.pass_name for r in recs if r.selected} == {
        "constant_propagation", "constant_folding", "strength_reduction", "dead_code_elimination"}
    for r in recs:
        assert 0.0 <= r.confidence <= 1.0 and r.reason


def test_selector_is_adaptive_to_the_code():
    only_mul = compile_src("int f(int n) {\n    return n * 4;\n}\n", "c")
    selected = {r.pass_name for r in RuleBasedPassSelector().select(only_mul.functions[0], "c") if r.selected}
    assert "strength_reduction" in selected
    assert "dead_code_elimination" not in selected


# ---------------------------------------------------------------- full pipeline

@pytest.mark.parametrize("fname,lang", [("optimize_demo.py", "python"), ("optimize_demo.c", "c"),
                                        ("optimize_demo.cpp", "cpp"), ("optimize_demo.java", "java")])
def test_pipeline_on_samples_preserves_behaviour(fname, lang):
    tree, src, detected = parse_file(os.path.join(SAMPLES, fname))
    assert detected == lang
    prog = get_translator(lang, src).translate_program(tree.root_node)
    report = optimize_program(prog)
    assert report.total_changes > 0
    assert_equivalent(report.original, report.optimized, "demo", [(n,) for n in range(-30, 31)])
    fr = report.functions["demo"]
    assert fr.features_after.constant_count < fr.features_before.constant_count
    assert fr.features_after.branch_count == 0 and fr.features_after.variable_count < fr.features_before.variable_count


def test_pipeline_is_idempotent():
    for fname in ("optimize_demo.py", "optimize_demo.c", "optimize_demo.java"):
        tree, src, lang = parse_file(os.path.join(SAMPLES, fname))
        prog = get_translator(lang, src).translate_program(tree.root_node)
        once = optimize_program(prog)
        twice = optimize_program(once.optimized)
        assert twice.total_changes == 0, [str(c) for fr in twice.functions.values() for c in fr.changes]


def test_pipeline_does_not_mutate_the_input_program():
    tree, src, lang = parse_file(os.path.join(SAMPLES, "optimize_demo.c"))
    prog = get_translator(lang, src).translate_program(tree.root_node)
    snapshot = print_function(prog.functions[0])
    optimize_program(prog)
    assert print_function(prog.functions[0]) == snapshot


# ---------------------------------------------------------------- fuzzing (differential testing)

def _rand_expr(rng, vars_, depth, lang):
    if depth == 0 or rng.random() < 0.3:
        if rng.random() < 0.5:
            return ir.Identifier(name=rng.choice(vars_), line=1)
        return ir.Literal(value=rng.choice([0, 1, 2, 3, 4, 5, 8, 16, 100]), type="int", line=1)
    op = rng.choice(["+", "-", "*", "*", "/", "%", "<", "==", "!=", ">"])
    left = _rand_expr(rng, vars_, depth - 1, lang)
    if op in ("/", "%"):
        right = ir.Literal(value=rng.choice([1, 2, 3, 7]), type="int", line=1)
    else:
        right = _rand_expr(rng, vars_, depth - 1, lang)
    return ir.BinOp(op=op, left=left, right=right, line=1)


def _rand_block(rng, vars_, depth, lang, counter):
    stmts = []
    for _ in range(rng.randint(1, 4)):
        kind = rng.random()
        target = rng.choice(vars_)
        if kind < 0.6 or depth == 0:
            stmts.append(ir.Assign(target=target, value=_rand_expr(rng, vars_, 2, lang), line=1))
        elif kind < 0.85:
            stmts.append(ir.If(cond=_rand_expr(rng, vars_, 2, lang),
                               then_block=_rand_block(rng, vars_, depth - 1, lang, counter),
                               else_block=_rand_block(rng, vars_, depth - 1, lang, counter) if rng.random() < 0.6 else None,
                               line=1))
        else:
            counter[0] += 1
            k = f"k{counter[0]}"
            body = _rand_block(rng, vars_, depth - 1, lang, counter)
            body.statements.append(ir.Assign(target=k, value=ir.BinOp(op="+", left=ir.Identifier(name=k, line=1),
                                                                      right=ir.Literal(value=1, type="int", line=1), line=1), line=1))
            stmts.append(ir.Assign(target=k, value=ir.Literal(value=0, type="int", line=1), line=1) if lang == "python"
                         else ir.VarDecl(name=k, var_type="int", init=ir.Literal(value=0, type="int", line=1), line=1))
            stmts.append(ir.While(cond=ir.BinOp(op="<", left=ir.Identifier(name=k, line=1),
                                               right=ir.Literal(value=rng.randint(0, 3), type="int", line=1), line=1),
                                  body=body, line=1))
    return ir.Block(statements=stmts, line=1)


def _random_program(seed, lang):
    rng = random.Random(seed)
    names = ["a", "b", "c"]
    body = []
    for v in names:
        init = ir.Literal(value=rng.choice([0, 1, 2, 5, 9]), type="int", line=1) if rng.random() < 0.7 \
            else ir.Identifier(name="n", line=1)
        body.append(ir.Assign(target=v, value=init, line=1) if lang == "python"
                    else ir.VarDecl(name=v, var_type="int", init=init, line=1))
    body.extend(_rand_block(rng, names + ["n"], 2, lang, [0]).statements)
    ret = ir.BinOp(op="+", left=ir.BinOp(op="+", left=ir.Identifier(name="a", line=1),
                                        right=ir.Identifier(name="b", line=1), line=1),
                   right=ir.Identifier(name="c", line=1), line=1)
    body.append(ir.Return(value=ret, line=1))
    func = ir.FuncDecl(name="f", params=[ir.Param(name="n", param_type="var" if lang == "python" else "int")],
                       return_type="int", body=ir.Block(statements=body, line=1), line=1)
    return ir.Program(source_language=lang, functions=[func])


@pytest.mark.parametrize("lang", LANGS)
def test_fuzz_optimizer_preserves_semantics(lang):
    args = [(n,) for n in (-9, -2, -1, 0, 1, 2, 3, 7, 50)]
    changed_programs = 0
    for seed in range(250):
        prog = _random_program(seed, lang)
        report = optimize_program(prog, passes=["constant_propagation", "constant_folding",
                                                "strength_reduction", "dead_code_elimination"])
        changed_programs += report.total_changes > 0
        try:
            assert_equivalent(report.original, report.optimized, "f", args)
        except AssertionError:
            print("\n--- seed", seed, "---\n", print_function(report.original.functions[0]),
                  "\n=>\n", print_function(report.optimized.functions[0]))
            raise
    assert changed_programs > 100          # the fuzzer really exercises the optimizer
