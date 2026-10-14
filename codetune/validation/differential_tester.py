"""
Phase 5 -- Semantic validation by DIFFERENTIAL TESTING.

Run the original function and the optimized function on the same generated
inputs with the IR interpreter and compare:
  * the return value (and its type: 3 vs 3.0 is a difference)
  * whether it raised an error, and which kind
  * whether it still terminates

Any difference is a mismatch and the optimization is rejected (the pass
manager rolls it back). Optimized and original runs also yield a dynamic cost
(operations executed), the "performance metric" used in the report.

Honest limits (shown as warnings, never hidden):
  * testing is evidence, not proof -- unlike formal translation validation
  * if the original raises an error on EVERY input (e.g. it calls a function
    that isn't defined) the comparison is vacuous and a warning is attached
"""

import math
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from ..ir import ir_nodes as ir
from ..ir.interpreter import Interpreter, InterpreterError, StepLimitExceeded
from .input_generator import generate_inputs


def dynamic_cost(stats) -> int:
    """Cost model: executed operations + assignments + branches + calls."""
    return stats["op"] + stats["assign"] + stats["branch"] + stats["call"]


@dataclass
class Mismatch:
    args: Tuple
    original: Any
    optimized: Any

    def __str__(self):
        return f"args={self.args}: original -> {self.original}, optimized -> {self.optimized}"


@dataclass
class ValidationResult:
    passed: bool
    tests_total: int
    tests_conclusive: int
    mismatches: List[Mismatch] = field(default_factory=list)
    original_cost: int = 0
    optimized_cost: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def cost_reduction_pct(self) -> float:
        if self.original_cost <= 0:
            return 0.0
        return round(100.0 * (self.original_cost - self.optimized_cost) / self.original_cost, 1)

    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        s = f"{status} ({self.tests_conclusive}/{self.tests_total} conclusive tests"
        s += f", {len(self.mismatches)} mismatch(es))" if self.mismatches else ", 0 mismatches)"
        return s


def _same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return type(a) is type(b) and a == b


class FunctionValidator:
    """Validates candidate versions of ONE function against the original.
    The original's outcomes are computed once and reused for every check()."""

    def __init__(self, program: "ir.Program", func_name: str, max_cases: int = 150,
                 n_random: int = 30, seed: int = 0, step_limit: int = 20_000):
        self.program = program
        self.func_name = func_name
        self.step_limit = step_limit
        func = next(f for f in program.functions if f.name == func_name)
        self.inputs = generate_inputs(func, program.source_language, max_cases, n_random, seed)
        self.baseline = [self._run(program, a) for a in self.inputs]

    def _run(self, program, args):
        interp = Interpreter(program, step_limit=self.step_limit)
        try:
            value = interp.call(self.func_name, list(args))
            return ("ok", value, dynamic_cost(interp.stats))
        except StepLimitExceeded:
            return ("limit", None, 0)
        except InterpreterError as e:
            return ("err", self._error_kind(str(e)), 0)
        except Exception as e:                        # interpreter bug should not crash validation
            return ("err", type(e).__name__, 0)

    @staticmethod
    def _error_kind(msg: str) -> str:
        for key in ("division by zero", "uninitialised", "unknown variable", "unknown function",
                    "cannot evaluate"):
            if key in msg:
                return key
        return "error"

    def check(self, candidate: "ir.FuncDecl") -> ValidationResult:
        prog = ir.Program(
            source_language=self.program.source_language, line=self.program.line,
            functions=[candidate if f.name == self.func_name else f for f in self.program.functions])

        result = ValidationResult(passed=True, tests_total=len(self.inputs), tests_conclusive=0)
        ok_runs = 0
        for args, base in zip(self.inputs, self.baseline):
            if base[0] == "limit":
                continue                              # original didn't finish: inconclusive
            cand = self._run(prog, args)
            result.tests_conclusive += 1
            if base[0] == "ok" and cand[0] == "ok" and _same(base[1], cand[1]):
                ok_runs += 1
                result.original_cost += base[2]
                result.optimized_cost += cand[2]
            elif base[0] == "err" and cand[0] == "err" and base[1] == cand[1]:
                continue
            else:
                result.passed = False
                if len(result.mismatches) < 5:
                    result.mismatches.append(Mismatch(args, self._show(base), self._show(cand)))
        if ok_runs == 0 and result.passed:
            result.warnings.append("no input ran to completion on the original: comparison is weak "
                                   "(does it call an undefined function?)")
        return result

    @staticmethod
    def _show(o):
        if o[0] == "ok":
            return f"{o[1]!r}"
        if o[0] == "limit":
            return "did not terminate (step limit)"
        return f"error: {o[1]}"