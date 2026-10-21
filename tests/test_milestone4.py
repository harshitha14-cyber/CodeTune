"""
Milestone 4 tests: the Digital Twin (cost prediction, sandbox, what-if,
versioning/rollback, synchronisation, reports).
"""

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from codetune.digital_twin import (DigitalTwin, Strategy, default_strategies, permutation_strategies,
                                   sequence_strategy)
from codetune.digital_twin.cost_model import StaticCostEstimator, code_size
from codetune.digital_twin.twin_report import build_twin_data, to_html, to_json, to_markdown, write_twin_report
from codetune.ir import ir_nodes as ir
from codetune.ir.ir_printer import print_function
from codetune.ir.ir_utils import clone
from codetune.optimizer.base import Change, OptimizationPass, PassResult, map_exprs_in_block

HERE = os.path.dirname(__file__)
SAMPLES = os.path.join(os.path.dirname(__file__), "data")
SAMPLES = os.path.join(HERE, "data")
CLI = os.path.join(HERE, "..", "twin_demo.py")
SAMPLE_FILES = ["twin_demo.py", "twin_demo.c", "twin_demo.cpp", "twin_demo.java",
                "optimize_demo.py", "optimize_demo.c", "optimize_demo.cpp", "optimize_demo.java"]


def twin_for(code, lang, **kw):
    return DigitalTwin.from_source(code, lang, **kw)


def sample_twin(name, **kw):
    return DigitalTwin.from_file(os.path.join(SAMPLES, name), **kw)


class MulBecomesAdd(OptimizationPass):
    """WRONG on purpose: `a * b` -> `a + b`."""
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


class Exploding(OptimizationPass):
    name = "exploding"

    def run(self, func, language):
        raise RuntimeError("boom")


# ------------------------------------------------------------------ cost model

def test_loop_trip_count_formulas():
    c = StaticCostEstimator._count
    assert c("<", 0, 10, 1) == 10 and c("<=", 0, 10, 1) == 11 and c("<", 0, 10, 3) == 4
    assert c(">", 10, 0, -1) == 10 and c(">=", 10, 0, -2) == 6 and c("<", 5, 5, 1) == 0


def test_static_prediction_is_exact_without_input_dependent_branches():
    code = ("int f(int n) {\n    int i = 0;\n    int s = 0;\n    while (i < 5) {\n"
            "        s = s + i * 3;\n        i = i + 1;\n    }\n    return s + n;\n}\n")
    t = twin_for(code, "c")
    m = t.baseline
    assert m.predicted_cost == pytest.approx(m.measured_cost, rel=0.01)


def test_unknown_branch_is_weighted_half_half():
    code = "int f(int n) {\n    int r = 0;\n    if (n > 0) {\n        r = n * 2 * 3;\n    }\n    return r;\n}\n"
    t = twin_for(code, "c")
    # call 5 + `int r = 0` (assign 1) + if: branch 1 + cond 1 + 0.5 * (two muls 6 + assign 1) + return 0
    assert t.baseline.predicted_cost == pytest.approx(5 + 1 + 1 + 1 + 0.5 * 7)


def test_return_inside_branch_lowers_probability_of_reaching_later_code():
    code = ("int f(int n) {\n    if (n > 0) {\n        return 1;\n    }\n    int x = n * n * n;\n    return x;\n}\n")
    t = twin_for(code, "c")
    # call 5 + branch/cond 2 + 0.5*0 (return 1) + 0.5 * (x: 2 muls 6 + assign 1)
    assert t.baseline.predicted_cost == pytest.approx(5 + 2 + 0.5 * 7)


def test_known_condition_after_assignment_is_resolved_statically():
    code = "int f(int n) {\n    int flag = 0;\n    int r = 1;\n    if (flag) {\n        r = n * n * n;\n    }\n    return r;\n}\n"
    t = twin_for(code, "c")
    assert t.baseline.predicted_cost == pytest.approx(t.baseline.measured_cost, rel=0.01)


def test_memory_and_size_shrink_when_dead_code_is_removed():
    t = sample_twin("twin_demo.c")
    exps = {e.strategy.name: e for e in t.explore()}
    best = exps["canonical to fixpoint"]
    assert best.metrics.memory_bytes < t.baseline.memory_bytes
    assert best.metrics.code_size < t.baseline.code_size


# ------------------------------------------------------------------ prediction accuracy (report target +-15%)

@pytest.mark.parametrize("name", SAMPLE_FILES)
def test_prediction_within_15_percent_of_measured(name):
    t = sample_twin(name)
    exps = t.explore()
    acc = t.accuracy(exps)
    assert acc.rows and acc.mean_error_pct <= 15.0
    assert acc.within_15_pct == 1.0
    assert acc.winner_matches and acc.rank_agreement >= 0.9


# ------------------------------------------------------------------ strategies and what-if

def test_every_default_strategy_is_safe_and_the_recommendation_is_the_cheapest():
    t = sample_twin("twin_demo.c")
    exps = t.explore()
    assert all(e.valid for e in exps)
    rec = t.recommend(exps)
    cheapest = min(e.metrics.predicted_cost for e in exps)
    assert rec.experiment.metrics.predicted_cost == pytest.approx(cheapest)
    assert rec.saving_pct > 20


def test_pass_order_matters_and_what_if_order_says_so():
    t = sample_twin("optimize_demo.c")
    res = t.what_if_order("CP", "CF")
    assert res["a_then_b"].metrics.predicted_cost < res["b_then_a"].metrics.predicted_cost
    assert "Apply CP before CF" in res["verdict"]
    t2 = sample_twin("twin_demo.c")
    assert "Apply CP before SR" in t2.what_if_order("constant_propagation", "strength_reduction")["verdict"]


def test_what_if_reports_savings_for_an_exact_sequence():
    t = sample_twin("twin_demo.c")
    w = t.what_if(["CP", "CF", "SR", "DCE"])
    assert w.vs_original_pct > 20 and "cheaper" in w.answer


def test_adaptive_strategy_matches_best_fixed_strategy_after_selector_fix():
    for name in ("twin_demo.c", "optimize_demo.c", "twin_demo.py"):
        t = sample_twin(name)
        exps = {e.strategy.name: e for e in t.explore()}
        assert exps["adaptive (selector)"].metrics.predicted_cost <= exps["canonical to fixpoint"].metrics.predicted_cost + 1e-9


def test_permutations_cover_all_24_orders_and_expose_a_best_order():
    t = sample_twin("optimize_demo.c")
    exps = t.explore(strategies=[], permutations=True)
    assert len(exps) == 24 and all(e.valid for e in exps)
    costs = {round(e.metrics.predicted_cost, 3) for e in exps}
    assert len(costs) > 1                                  # order changes the outcome


# ------------------------------------------------------------------ safety

def test_unsafe_strategy_is_flagged_never_recommended_and_cannot_be_committed():
    t = sample_twin("twin_demo.c", pass_overrides={"mul_becomes_add": MulBecomesAdd()})
    bad = Strategy("bad idea", ("mul_becomes_add",), 1)
    exps = t.explore(default_strategies() + [bad])
    bad_exp = next(e for e in exps if e.strategy.name == "bad idea")
    assert not bad_exp.valid and bad_exp.validation.mismatches
    assert bad_exp not in t.ranking(exps)
    assert t.recommend(exps).experiment.strategy.name != "bad idea"
    with pytest.raises(ValueError):
        t.commit(bad_exp)
    assert "Not safe" in t.what_if(["mul_becomes_add"]).answer


def test_a_crashing_pass_is_contained():
    t = sample_twin("twin_demo.c", pass_overrides={"exploding": Exploding()})
    exp = t.simulate(Strategy("boom", ("exploding",), 1))
    assert not exp.valid and "boom" in exp.error and exp.metrics is None
    assert t.recommend(t.explore(default_strategies() + [Strategy("boom", ("exploding",), 1)])).experiment.valid


# ------------------------------------------------------------------ sandbox

def test_sandbox_never_touches_the_original_and_experiments_are_independent():
    t = sample_twin("twin_demo.c")
    before = print_function(t.original)
    exps = t.explore(permutations=True)
    assert print_function(t.original) == before
    assert print_function(t.program.functions[0]) == before
    ids = {id(e.func) for e in exps}
    assert len(ids) == len(exps)
    exps[5].func.body.statements.clear()                    # damaging one experiment...
    assert print_function(exps[6].func) != ""               # ...does not affect another
    assert print_function(t.original) == before


def test_parallel_and_sequential_exploration_agree():
    t = sample_twin("optimize_demo.c")
    seq = [(e.strategy.name, round(e.metrics.predicted_cost, 3)) for e in t.explore()]
    par = [(e.strategy.name, round(e.metrics.predicted_cost, 3)) for e in t.explore(parallel=True)]
    assert seq == par


# ------------------------------------------------------------------ versioning

def test_commit_rollback_history_and_marginal_gain():
    t = sample_twin("twin_demo.c")
    rec = t.recommend()
    v1 = t.commit(rec.experiment)
    assert t.head == 1 and v1.parent == 0 and len(t.history()) == 2
    # everything useful is already applied -> one more pass adds nothing on top of head
    assert t.marginal_gain("dead_code_elimination").vs_head_pct == 0.0
    back = t.rollback()
    assert back.id == 0 and t.head == 0 and len(t.versions) == 2        # versions are kept
    # from the original, DCE alone does help
    assert t.marginal_gain("DCE").vs_head_pct > 0
    t.rollback(1)
    assert t.head == 1
    with pytest.raises(ValueError):
        t.rollback(99)


# ------------------------------------------------------------------ real-time synchronisation

def test_sync_rebuilds_the_twin_when_the_file_changes(tmp_path):
    path = tmp_path / "work.c"
    shutil.copy(os.path.join(SAMPLES, "twin_demo.c"), path)
    t = DigitalTwin.from_file(str(path))
    old_cost = t.baseline.predicted_cost
    assert t.sync() is False and t.revision == 0           # nothing changed

    text = path.read_text().replace("while (i < 10)", "while (i < 20)")
    path.write_text(text)
    assert t.sync() is True and t.revision == 1
    assert t.baseline.predicted_cost > old_cost            # the loop got longer
    assert len(t.versions) == 1                            # old experiments are discarded


def test_sync_keeps_last_good_state_when_edit_is_unusable(tmp_path):
    path = tmp_path / "work.c"
    shutil.copy(os.path.join(SAMPLES, "twin_demo.c"), path)
    t = DigitalTwin.from_file(str(path))
    cost = t.baseline.predicted_cost
    path.write_text(path.read_text().replace("int waste = total * 100;",
                                              "total = total > 0 ? 1 : 2;"))
    assert t.sync() is False and t.last_error
    assert t.revision == 0 and t.baseline.predicted_cost == cost
    assert t.sync() is False                               # same broken revision is not re-reported


# ------------------------------------------------------------------ languages / reports / CLI

@pytest.mark.parametrize("name", ["twin_demo.py", "twin_demo.c", "twin_demo.cpp", "twin_demo.java"])
def test_all_languages_get_a_safe_positive_recommendation(name):
    t = sample_twin(name)
    exps = t.explore()
    rec = t.recommend(exps)
    assert rec.experiment.valid and rec.saving_pct > 15
    measured = rec.experiment.measured_saving_pct
    assert measured is not None and abs(measured - rec.saving_pct) < 5     # prediction ~ reality


def test_report_data_markdown_html_and_files(tmp_path):
    t = sample_twin("twin_demo.c")
    exps = t.explore()
    rec, acc = t.recommend(exps), t.accuracy(exps)
    w = t.what_if(["CP", "CF"])
    data = build_twin_data(t, exps, rec, acc, [w])
    json.loads(to_json(data))
    md, html_text = to_markdown(data), to_html(data)
    for needle in ("Recommendation", "Strategy comparison", "Prediction accuracy", "Version history", "What-if"):
        assert needle in md
    assert "canonical to fixpoint" in html_text and "<script" not in html_text
    paths = write_twin_report(data, str(tmp_path))
    assert set(paths) == {"md", "html", "json"} and all(os.path.getsize(p) > 200 for p in paths.values())


def test_cli_end_to_end(tmp_path):
    out = subprocess.run([sys.executable, CLI, os.path.join(SAMPLES, "twin_demo.c"), "--order", "CP,SR",
                          "--report", str(tmp_path)], capture_output=True, text=True, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert "Recommendation:" in out.stdout and "Apply CP before SR" in out.stdout
    assert (tmp_path / "twin_work.html").exists()