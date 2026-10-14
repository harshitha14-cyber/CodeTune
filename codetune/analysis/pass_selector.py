"""
Phase 3 -- Optimization-pass selection (rule-based baseline + confidence).

For every function CodeTune decides WHICH passes are worth running, instead of
a fixed -O2-style sequence. Each decision is explainable:

    pass                  confidence  selected  reason
    constant_propagation  0.85        yes       3 constant assignments; dry run found 4 replaceable uses

How a confidence is produced (all rules are human-readable on purpose):
  1. GATE      cheap static features must show the pass COULD apply
               (e.g. strength reduction needs a * / % somewhere).
  2. VERIFY    a dry run of the pass on a copy counts concrete sites.
               Sites found      -> confidence rises with the number of sites.
               Nothing found    -> confidence drops below the threshold,
                                   unless an upstream pass will create work for it
                                   (propagation exposes constants for folding / DCE).
  3. THRESHOLD a pass is selected when confidence >= 0.5.

The ML extension (decision tree / random forest over the same feature vector)
only has to implement `select(func, language) -> List[PassRecommendation]`;
the pass manager does not care which selector it is given.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..optimizer.registry import PASS_ORDER, make_pass
from .feature_extractor import FeatureExtractor, FunctionFeatures


@dataclass
class PassRecommendation:
    pass_name: str
    confidence: float
    selected: bool
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)


class RuleBasedPassSelector:
    THRESHOLD = 0.5

    # -- gates: (applies?, base confidence, evidence text) ------------------------------

    @staticmethod
    def _gate(name: str, f: FunctionFeatures):
        ops = f.arithmetic_op_count + f.comparison_op_count + f.logical_op_count
        if name == "constant_propagation":
            n = f.constant_assignment_count
            return n >= 1, n, f"{n} assignment(s) of a constant value"
        if name == "constant_folding":
            return (f.constant_count >= 2 and ops >= 1), f.constant_count, \
                   f"{f.constant_count} literal(s) and {ops} operator(s)"
        if name == "strength_reduction":
            n = f.mul_div_op_count
            ok = n >= 1 or (f.constant_count >= 1 and f.arithmetic_op_count >= 1)
            return ok, n + f.constant_count, f"{n} multiply/divide/modulo operator(s)"
        if name == "dead_code_elimination":
            ok = f.variable_count >= 2 or f.branch_count >= 1
            return ok, f.variable_count + f.branch_count, \
                   f"{f.variable_count} variable(s) and {f.branch_count} branch(es) that may be unused or constant"
        return False, 0, ""

    # -- main entry point --------------------------------------------------------------------

    def select(self, func, language: str, features: FunctionFeatures = None) -> List[PassRecommendation]:
        f = features or FeatureExtractor().extract(func)

        sites = {name: len(make_pass(name).run(func, language).changes) for name in PASS_ORDER}
        prop_exposes_work = sites["constant_propagation"] > 0

        recs = []
        for name in PASS_ORDER:
            applies, evidence_n, gate_text = self._gate(name, f)
            enabled_upstream = prop_exposes_work and name in ("constant_folding", "dead_code_elimination")
            base = 0.5 + 0.05 * min(evidence_n, 6) if applies else 0.0
            n = sites[name]

            if n > 0:
                conf = min(0.99, base + 0.10 + 0.05 * min(n, 6))
                why = f"{gate_text}; dry run found {n} concrete site(s)"
            elif enabled_upstream:
                conf = max(base, 0.6)
                why = "constant propagation will expose new constants for this pass"
            elif applies:
                conf = round(base * 0.4, 2)
                why = f"{gate_text}, but a dry run found nothing to change"
            else:
                conf = 0.05
                why = "no matching code pattern"

            conf = round(conf, 2)
            recs.append(PassRecommendation(
                pass_name=name, confidence=conf, selected=conf >= self.THRESHOLD, reason=why,
                evidence={"features_gate": applies, "dry_run_sites": n,
                          "enabled_by_propagation": enabled_upstream}))
        return recs
