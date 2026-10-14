"""
Runs the selected passes over a whole Program and records everything that
happened (Phase 4 driver + Phase 5 validation hook + raw data for Phase 6).

    report = optimize_program(program)                          # adaptive, no validation
    report = optimize_program(program, validate=True)           # every pass is checked
    report = optimize_program(program, passes=["constant_folding"])

Passes run in the canonical order and the sequence repeats until nothing
changes (fixpoint). With validate=True, after EVERY pass application the new
function is compared with the original by differential testing; if outputs
differ, that pass is rejected (rolled back, never applied again to this
function) and the reason is kept in the report.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..analysis.feature_extractor import FeatureExtractor, FunctionFeatures
from ..analysis.pass_selector import PassRecommendation, RuleBasedPassSelector
from ..ir import ir_nodes as ir
from ..ir.ir_printer import print_function
from ..validation.differential_tester import FunctionValidator, ValidationResult
from .base import Change
from .registry import PASS_ORDER, make_pass


@dataclass
class RejectedPass:
    pass_name: str
    reason: str
    mismatches: list = field(default_factory=list)


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
    validation: Optional[ValidationResult] = None          # Milestone 3
    rejected: List[RejectedPass] = field(default_factory=list)


@dataclass
class OptimizationReport:
    language: str
    original: "ir.Program"
    optimized: "ir.Program"
    functions: Dict[str, FunctionReport] = field(default_factory=dict)

    @property
    def total_changes(self) -> int:
        return sum(len(r.changes) for r in self.functions.values())

    @property
    def all_validated(self) -> bool:
        return all(r.validation is None or r.validation.passed for r in self.functions.values())

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
            if r.rejected:
                out.append("")
                out.append("REJECTED by semantic validation:")
                for rej in r.rejected:
                    out.append(f"  {rej.pass_name}: {rej.reason}")
                    out.extend(f"      {m}" for m in rej.mismatches[:2])
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
            if r.validation is not None:
                v = r.validation
                out.append(f"Validation: {v.summary()}")
                out.append(f"Dynamic cost: {v.original_cost} -> {v.optimized_cost} operations "
                           f"({v.cost_reduction_pct}% fewer)")
                out.extend(f"  warning: {w}" for w in v.warnings)
            out.append("")
        return "\n".join(out)


def optimize_function(func, language, selector=None, passes: Optional[List[str]] = None,
                      max_iterations: int = 10, validate: bool = False, program=None,
                      pass_overrides: Optional[dict] = None) -> FunctionReport:
    """`pass_overrides` ({name: OptimizationPass}) lets tests plug in extra or
    deliberately buggy passes to prove that validation rejects them."""
    overrides = pass_overrides or {}
    features_before = FeatureExtractor().extract(func)

    if passes is not None:
        recs = [PassRecommendation(n, 1.0, n in passes, "explicitly requested") for n in PASS_ORDER]
        order = [n for n in PASS_ORDER if n in passes] + [n for n in passes if n not in PASS_ORDER]
    else:
        recs = (selector or RuleBasedPassSelector()).select(func, language, features_before)
        order = [n for n in PASS_ORDER if n in [r.pass_name for r in recs if r.selected]]

    validator = None
    if validate:
        program = program or ir.Program(source_language=language, functions=[func])
        validator = FunctionValidator(program, func.name)

    current, changes, rejected, banned, iterations = func, [], [], set(), 0
    for _ in range(max_iterations):
        iterations += 1
        progressed = False
        for name in order:
            if name in banned:
                continue
            p = overrides[name] if name in overrides else make_pass(name)
            result = p.run(current, language)
            if not result.changed:
                continue
            if validator is not None:
                check = validator.check(result.func)
                if not check.passed:
                    banned.add(name)
                    rejected.append(RejectedPass(
                        name, f"{len(result.changes)} change(s) altered program behaviour -> rolled back",
                        check.mismatches))
                    continue
            progressed = True
            changes.extend(result.changes)
            current = result.func
        if not progressed:
            iterations -= 1
            break

    return FunctionReport(
        name=func.name, features_before=features_before,
        features_after=FeatureExtractor().extract(current),
        recommendations=recs, applied_passes=[n for n in order if n not in banned],
        iterations=iterations, changes=changes, original=func, optimized=current,
        validation=validator.check(current) if validator is not None else None,
        rejected=rejected)


def optimize_program(program, selector=None, passes=None, max_iterations=10,
                     validate: bool = False, pass_overrides=None) -> OptimizationReport:
    report = OptimizationReport(language=program.source_language, original=program,
                                optimized=ir.Program(source_language=program.source_language,
                                                     functions=[], line=program.line))
    for func in program.functions:
        fr = optimize_function(func, program.source_language, selector, passes, max_iterations,
                               validate=validate, program=program, pass_overrides=pass_overrides)
        report.functions[func.name] = fr
        report.optimized.functions.append(fr.optimized)
    return report