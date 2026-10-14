"""
Runs the selected passes over a whole Program and records everything that
happened (Phase 4 driver + the raw data for Phase 6 reporting).

    report = optimize_program(program)                        # adaptive: selector decides
    report = optimize_program(program, passes=["constant_folding"])   # fixed choice
    print(report.to_text())

Passes run in the canonical order and the whole sequence repeats until nothing
changes (fixpoint), because one pass often creates work for another:
propagation -> folding -> DCE.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..analysis.feature_extractor import FeatureExtractor, FunctionFeatures
from ..analysis.pass_selector import PassRecommendation, RuleBasedPassSelector
from ..ir import ir_nodes as ir
from ..ir.ir_printer import print_function
from .base import Change
from .registry import PASS_ORDER, make_pass


@dataclass
class FunctionReport:
    name: str
    features_before: FunctionFeatures
    features_after: FunctionFeatures
    recommendations: List[PassRecommendation]
    applied_passes: List[str]
    iterations: int
    changes: List[Change]
    original: "ir.FuncDecl"
    optimized: "ir.FuncDecl"


@dataclass
class OptimizationReport:
    language: str
    original: "ir.Program"
    optimized: "ir.Program"
    functions: Dict[str, FunctionReport] = field(default_factory=dict)

    @property
    def total_changes(self) -> int:
        return sum(len(r.changes) for r in self.functions.values())

    def to_text(self) -> str:
        out = []
        for r in self.functions.values():
            out.append("=" * 70)
            out.append(f"function {r.name}   ({self.language})")
            out.append("=" * 70)
            out.append("Pass selection:")
            for rec in r.recommendations:
                mark = "RUN " if rec.selected else "skip"
                out.append(f"  [{mark}] {rec.pass_name:<24} confidence {rec.confidence:.2f}  - {rec.reason}")
            out.append("")
            out.append(f"Transformations ({len(r.changes)}, {r.iterations} iteration(s)):")
            out.extend(f"  {c}" for c in r.changes) if r.changes else out.append("  (none)")
            out.append("")
            out.append("Before:")
            out.append(print_function(r.original))
            out.append("")
            out.append("After:")
            out.append(print_function(r.optimized))
            fb, fa = r.features_before, r.features_after
            out.append("")
            out.append(f"Features  constants {fb.constant_count}->{fa.constant_count}, "
                       f"variables {fb.variable_count}->{fa.variable_count}, "
                       f"branches {fb.branch_count}->{fa.branch_count}, "
                       f"mul/div {fb.mul_div_op_count}->{fa.mul_div_op_count}")
            out.append("")
        return "\n".join(out)


def optimize_function(func, language, selector=None, passes: Optional[List[str]] = None,
                      max_iterations: int = 10) -> FunctionReport:
    features_before = FeatureExtractor().extract(func)

    if passes is not None:
        recs = [PassRecommendation(n, 1.0, n in passes, "explicitly requested") for n in PASS_ORDER]
    else:
        recs = (selector or RuleBasedPassSelector()).select(func, language, features_before)
    chosen = [r.pass_name for r in recs if r.selected]
    order = [n for n in PASS_ORDER if n in chosen]

    current, changes, iterations = func, [], 0
    for _ in range(max_iterations):
        iterations += 1
        progressed = False
        for name in order:
            result = make_pass(name).run(current, language)
            if result.changed:
                progressed = True
                changes.extend(result.changes)
                current = result.func
        if not progressed:
            iterations -= 1
            break

    return FunctionReport(
        name=func.name, features_before=features_before,
        features_after=FeatureExtractor().extract(current),
        recommendations=recs, applied_passes=order, iterations=iterations,
        changes=changes, original=func, optimized=current)


def optimize_program(program, selector=None, passes=None, max_iterations=10) -> OptimizationReport:
    report = OptimizationReport(language=program.source_language, original=program,
                                optimized=ir.Program(source_language=program.source_language,
                                                     functions=[], line=program.line))
    for func in program.functions:
        fr = optimize_function(func, program.source_language, selector, passes, max_iterations)
        report.functions[func.name] = fr
        report.optimized.functions.append(fr.optimized)
    return report
