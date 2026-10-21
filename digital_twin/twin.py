"""
CodeTune Digital Twin (Milestone 4).

A virtual replica of ONE function's compilation, kept next to the real code:

  Virtual Execution Environment  IR interpreter + weighted cost model (cost_model.py)
  Optimization Sandbox           every strategy runs on its own copy (sandbox.py)
  Performance Predictor          static cost / code size / stack-memory estimate
  What-If Analysis               what_if(), what_if_order(), marginal_gain()
  Real-Time Synchronization      sync() re-reads the source file when it changes
  Versioning and rollback        commit(), rollback(), history()

Safety: every simulated result is differentially tested against the ORIGINAL
function (Milestone 3). A strategy that changes behaviour is marked invalid
and is never recommended.
"""

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..frontend.parser import parse_file, parse_source
from ..ir import ir_nodes as ir
from ..ir.interpreter import Interpreter
from ..ir.ir_printer import print_function
from ..ir.ir_utils import clone
from ..ir.translators import get_translator
from ..validation.differential_tester import FunctionValidator
from .cost_model import (code_size, estimated_stack_bytes, predicted_cost, weighted_dynamic_cost)
from .sandbox import Experiment, Sandbox, TwinMetrics
from .strategy import (SHORT, Strategy, default_strategies, normalize, permutation_strategies,
                       run_strategy, sequence_strategy)


@dataclass
class Version:
    id: int
    parent: Optional[int]
    label: str
    func: object
    metrics: TwinMetrics
    valid: bool = True


@dataclass
class WhatIf:
    question: str
    experiment: Experiment
    vs_original_pct: float
    vs_head_pct: float
    answer: str


@dataclass
class Recommendation:
    experiment: Experiment
    saving_pct: float
    reason: str


@dataclass
class AccuracyReport:
    rows: List[dict]
    mean_error_pct: float
    within_15_pct: float               # fraction of strategies predicted within +-15% of measured
    rank_agreement: float              # fraction of strategy pairs the twin orders like reality
    winner_matches: bool


class DigitalTwin:
    def __init__(self, program: "ir.Program", func_name: Optional[str] = None,
                 pass_overrides: Optional[dict] = None, max_cases: int = 100, seed: int = 0,
                 source_path: Optional[str] = None):
        self.pass_overrides = pass_overrides or {}
        self.max_cases, self.seed = max_cases, seed
        self.source_path = source_path
        self.revision = 0
        self.last_error: Optional[str] = None
        self._hash: Optional[str] = self._file_hash() if source_path else None
        self._init_state(program, func_name)

    # ------------------------------------------------------------------ construction

    @classmethod
    def from_source(cls, code: str, language: str, func_name=None, **kw) -> "DigitalTwin":
        tree, src = parse_source(code, language)
        return cls(get_translator(language, src).translate_program(tree.root_node), func_name, **kw)

    @classmethod
    def from_file(cls, path: str, func_name=None, **kw) -> "DigitalTwin":
        tree, src, lang = parse_file(path)
        program = get_translator(lang, src).translate_program(tree.root_node)
        return cls(program, func_name, source_path=path, **kw)

    def _init_state(self, program, func_name):
        self.program = program
        self.language = program.source_language
        self.func_name = func_name or program.functions[0].name
        self.original = clone(next(f for f in program.functions if f.name == self.func_name))
        self.validator = FunctionValidator(program, self.func_name, max_cases=self.max_cases, seed=self.seed)
        base = self._metrics(self.original)
        self.versions: List[Version] = [Version(0, None, "original", self.original, base)]
        self.head = 0
        self.sandbox = Sandbox(self.simulate)

    # ------------------------------------------------------------------ metrics

    def _program_with(self, func) -> "ir.Program":
        return ir.Program(source_language=self.language, line=self.program.line,
                          functions=[func if f.name == self.func_name else f for f in self.program.functions])

    def _measure(self, func) -> Optional[float]:
        prog = self._program_with(func)
        costs = []
        for args, base in zip(self.validator.inputs, self.validator.baseline):
            if base[0] != "ok":
                continue
            interp = Interpreter(prog, step_limit=self.validator.step_limit)
            try:
                interp.call(self.func_name, list(args))
            except Exception:
                return None
            costs.append(weighted_dynamic_cost(interp.stats))
        return sum(costs) / len(costs) if costs else None

    def _metrics(self, func) -> TwinMetrics:
        prog = self._program_with(func)
        return TwinMetrics(
            predicted_cost=predicted_cost(func, prog), measured_cost=self._measure(func),
            code_size=code_size(func), lines=len(print_function(func).splitlines()),
            memory_bytes=estimated_stack_bytes(func, self.language))

    @property
    def baseline(self) -> TwinMetrics:
        return self.versions[0].metrics

    @property
    def head_version(self) -> Version:
        return self.versions[self.head]

    # ------------------------------------------------------------------ simulation

    def simulate(self, strategy: Strategy, from_head: bool = False) -> Experiment:
        """Run `strategy` in the sandbox (private copy). Never changes twin state."""
        start = clone(self.head_version.func if from_head else self.original)
        t0 = time.perf_counter()
        try:
            new_func, changes = run_strategy(start, self.language, strategy, self.pass_overrides)
        except Exception as e:                                  # a faulty pass must not crash the twin
            return Experiment(strategy, start, [], None, valid=False, error=f"{type(e).__name__}: {e}")
        ms = (time.perf_counter() - t0) * 1000.0

        validation = self.validator.check(new_func)
        metrics = self._metrics(new_func)
        exp = Experiment(strategy, new_func, changes, metrics, valid=validation.passed,
                         validation=validation, opt_time_ms=round(ms, 2))
        b = self.baseline
        if b.predicted_cost > 0:
            exp.saving_pct = round(100.0 * (b.predicted_cost - metrics.predicted_cost) / b.predicted_cost, 1)
        if b.measured_cost and metrics.measured_cost is not None:
            exp.measured_saving_pct = round(100.0 * (b.measured_cost - metrics.measured_cost) / b.measured_cost, 1)
        return exp

    def explore(self, strategies: Optional[List[Strategy]] = None, permutations: bool = False,
                parallel: bool = False) -> List[Experiment]:
        strategies = list(strategies) if strategies is not None else default_strategies()
        if permutations:
            strategies += permutation_strategies()
        return self.sandbox.run(strategies, parallel=parallel)

    @staticmethod
    def ranking(experiments: List[Experiment]) -> List[Experiment]:
        """Valid experiments, best (lowest predicted cost) first. Ties prefer fewer passes,
        then smaller code, then name -- so the order is deterministic."""
        ok = [e for e in experiments if e.valid and e.metrics is not None]
        return sorted(ok, key=lambda e: (round(e.metrics.predicted_cost, 6), len(e.strategy.passes),
                                         e.metrics.code_size, e.strategy.name))

    def recommend(self, experiments: Optional[List[Experiment]] = None) -> Recommendation:
        experiments = experiments if experiments is not None else self.explore()
        ranked = self.ranking(experiments)
        best = ranked[0]
        if best.saving_pct <= 0:
            return Recommendation(best, 0.0, "No strategy is predicted to beat the unoptimized code.")
        invalid = [e for e in experiments if not e.valid]
        reason = (f"'{best.strategy.name}' has the lowest predicted cost: {best.saving_pct}% below the original "
                  f"({best.metrics.predicted_cost:.0f} vs {self.baseline.predicted_cost:.0f} cost units)")
        if invalid:
            reason += f"; {len(invalid)} strategy(ies) were rejected because they changed behaviour"
        return Recommendation(best, best.saving_pct, reason + ".")

    # ------------------------------------------------------------------ what-if analysis

    def what_if(self, passes: Sequence[str], rounds: int = 1, from_head: bool = False) -> WhatIf:
        strat = sequence_strategy(passes, rounds)
        exp = self.simulate(strat, from_head)
        head_pred = self.head_version.metrics.predicted_cost
        vs_head = 0.0
        if exp.metrics and head_pred > 0:
            vs_head = round(100.0 * (head_pred - exp.metrics.predicted_cost) / head_pred, 1)
        q = f"What if I apply {strat.describe()}?"
        if not exp.valid:
            ans = "Not safe: the result changes program behaviour." if exp.error is None else f"Failed: {exp.error}"
        else:
            ans = (f"Predicted cost {exp.metrics.predicted_cost:.0f} (original {self.baseline.predicted_cost:.0f}): "
                   f"{exp.saving_pct}% cheaper than the original, code size {self.baseline.code_size} -> "
                   f"{exp.metrics.code_size}, stack {self.baseline.memory_bytes} -> {exp.metrics.memory_bytes} bytes.")
        return WhatIf(q, exp, exp.saving_pct, vs_head, ans)

    def what_if_order(self, first: str, second: str, rounds: int = 1) -> dict:
        """'What if I apply X before Y?' -- simulates both orders (single sweep by default)."""
        a, b = normalize(first), normalize(second)
        ab, ba = self.simulate(sequence_strategy([a, b], rounds)), self.simulate(sequence_strategy([b, a], rounds))
        ka = (round(ab.metrics.predicted_cost, 6), ab.metrics.code_size)
        kb = (round(ba.metrics.predicted_cost, 6), ba.metrics.code_size)
        same_code = print_function(ab.func) == print_function(ba.func)
        sa, sb = SHORT.get(a, a), SHORT.get(b, b)
        if same_code:
            verdict = f"The order of {sa} and {sb} does not matter here (identical result)."
        elif ka == kb:
            verdict = (f"{sa} > {sb} and {sb} > {sa} have the same predicted cost and size; "
                       f"the resulting code differs but is equally good by this model.")
        else:
            first_better = ka < kb
            better, worse = (sa, sb) if first_better else (sb, sa)
            ca, cb = ab.metrics.predicted_cost, ba.metrics.predicted_cost
            if abs(ca - cb) > 1e-9:
                gain = round(100.0 * abs(ca - cb) / max(ca, cb), 1)
                verdict = f"Apply {better} before {worse}: predicted {gain}% cheaper than the other order."
            else:
                verdict = f"Apply {better} before {worse}: same predicted cost but smaller code."
        return {"a_then_b": ab, "b_then_a": ba, "verdict": verdict}

    def marginal_gain(self, pass_name: str) -> WhatIf:
        """What would ONE more pass add on top of the current version?"""
        return self.what_if([pass_name], rounds=1, from_head=True)

    # ------------------------------------------------------------------ versioning

    def commit(self, experiment: Experiment, label: Optional[str] = None) -> Version:
        if not experiment.valid or experiment.metrics is None:
            raise ValueError("refusing to commit an experiment that failed validation")
        v = Version(len(self.versions), self.head, label or experiment.strategy.name,
                    clone(experiment.func), experiment.metrics)
        self.versions.append(v)
        self.head = v.id
        return v

    def rollback(self, to: Optional[int] = None) -> Version:
        """Move head back to version `to` (default: its parent). Versions are kept."""
        target = self.head_version.parent if to is None else to
        if target is None or not (0 <= target < len(self.versions)):
            raise ValueError("nothing to roll back to")
        self.head = target
        return self.head_version

    def history(self) -> List[dict]:
        return [{"id": v.id, "parent": v.parent, "label": v.label, "head": v.id == self.head,
                 "predicted_cost": round(v.metrics.predicted_cost, 1), "code_size": v.metrics.code_size}
                for v in self.versions]

    # ------------------------------------------------------------------ real-time synchronisation

    def _file_hash(self) -> Optional[str]:
        try:
            with open(self.source_path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            return None

    def sync(self) -> bool:
        """Re-read the source file. If it changed, rebuild the replica (all
        experiments and versions of the old code are discarded) and return True.
        If the new code can't be parsed/translated the twin keeps its last good
        state, records `last_error` and returns False."""
        if not self.source_path:
            return False
        h = self._file_hash()
        if h is None or h == self._hash:
            return False
        try:
            tree, src, lang = parse_file(self.source_path)
            if tree.root_node.has_error:
                raise ValueError("syntax error in the edited file")
            program = get_translator(lang, src).translate_program(tree.root_node)
            names = [f.name for f in program.functions]
            self._init_state(program, self.func_name if self.func_name in names else None)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            self._hash = h                      # don't re-report the same broken revision
            return False
        self._hash, self.last_error = h, None
        self.revision += 1
        return True

    def watch(self, on_change, interval: float = 1.0, max_polls: int = 30):
        """Poll the file; call on_change(twin) after every successful re-sync."""
        for _ in range(max_polls):
            if self.sync():
                on_change(self)
            time.sleep(interval)

    # ------------------------------------------------------------------ prediction accuracy

    def accuracy(self, experiments: List[Experiment]) -> AccuracyReport:
        """How well did the STATIC prediction match what the interpreter measured?
        (report target: prediction within +-15% of actual performance)."""
        rows = []
        for e in experiments:
            if e.metrics is None or not e.valid or not e.metrics.measured_cost:
                continue
            rows.append({"strategy": e.strategy.name, "predicted": round(e.metrics.predicted_cost, 1),
                         "measured": round(e.metrics.measured_cost, 1), "error_pct": e.metrics.prediction_error_pct})
        if not rows:
            return AccuracyReport([], 0.0, 0.0, 1.0, True)
        mean_err = round(sum(r["error_pct"] for r in rows) / len(rows), 1)
        within = sum(1 for r in rows if r["error_pct"] <= 15.0) / len(rows)

        agree = total = 0
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                dp = rows[i]["predicted"] - rows[j]["predicted"]
                dm = rows[i]["measured"] - rows[j]["measured"]
                total += 1
                agree += (dp == 0 and dm == 0) or (dp * dm > 0) or (abs(dp) < 0.05 * max(rows[i]["predicted"], 1) and abs(dm) < 0.05 * max(rows[i]["measured"], 1))
        best_pred = min(rows, key=lambda r: r["predicted"])["strategy"]
        best_meas = min(r["measured"] for r in rows)
        winner_ok = next(r for r in rows if r["strategy"] == best_pred)["measured"] <= best_meas * 1.05
        return AccuracyReport(rows, mean_err, round(within, 3), round(agree / total, 3) if total else 1.0, winner_ok)