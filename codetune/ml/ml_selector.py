"""
ML pass selector (report 3.1 Phase 3: "decision tree or random forest trained on
labeled program samples" + "confidence scoring").

One binary model PER PASS, trained on STATIC FEATURES ONLY (the same vector the
rule-based selector gates on, plus the language). Unlike the rule-based
selector it never dry-runs the passes, so it is cheap -- and it can be wrong,
which is why every pass it selects is still validated by differential testing.

Each pass gets
  * a random forest   -> the confidence (mean probability of 15 trees)
  * a small decision tree (depth 4) trained on the same data -> readable rules
    and the exact decision path quoted in every recommendation (explainability)

Drop-in replacement: `optimize_program(program, selector=MLPassSelector.load_or_train())`.
"""

import json
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..analysis.feature_extractor import FeatureExtractor, FunctionFeatures
from ..analysis.pass_selector import PassRecommendation
from ..optimizer.registry import PASS_ORDER
from .corpus import LANGUAGES, generate_corpus
from .decision_tree import DecisionTree, RandomForest

NUMERIC_FEATURES = ["loop_count", "max_loop_nesting_depth", "branch_count", "max_branch_nesting_depth",
                    "arithmetic_op_count", "comparison_op_count", "logical_op_count", "constant_count",
                    "function_call_count", "variable_count", "max_expression_depth", "mul_div_op_count",
                    "constant_assignment_count"]
FEATURE_NAMES = NUMERIC_FEATURES + ["is_python"]
DEFAULT_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selector_model.json")


def featurize(features: FunctionFeatures, language: str) -> List[float]:
    d = features.to_dict()
    return [float(d[k]) for k in NUMERIC_FEATURES] + [1.0 if language == "python" else 0.0]


@dataclass
class EvalReport:
    per_pass: Dict[str, Dict[str, float]]
    overall_accuracy: float
    baseline_accuracy: float            # always predicting the majority class
    n_train: int
    n_test: int

    @property
    def meets_target(self) -> bool:     # report: "optimization selection accuracy target > 75%"
        return self.overall_accuracy > 0.75

    def to_text(self) -> str:
        lines = [f"{'pass':<24}{'accuracy':>9}{'precision':>10}{'recall':>8}{'majority baseline':>19}"]
        for p, m in self.per_pass.items():
            lines.append(f"{p:<24}{m['accuracy']:>9.2f}{m['precision']:>10.2f}{m['recall']:>8.2f}{m['baseline']:>19.2f}")
        lines.append(f"\noverall held-out accuracy {self.overall_accuracy:.3f} "
                     f"(majority-class baseline {self.baseline_accuracy:.3f}; target > 0.75: "
                     f"{'MET' if self.meets_target else 'NOT met'})  [{self.n_train} train / {self.n_test} test programs]")
        return "\n".join(lines)


@dataclass
class PassModel:
    forest: RandomForest
    tree: DecisionTree


class MLPassSelector:
    THRESHOLD = 0.5

    def __init__(self, models: Dict[str, PassModel], eval_report: Optional[EvalReport] = None):
        self.models = models
        self.eval_report = eval_report

    # ------------------------------------------------------------------ training

    @classmethod
    def train(cls, n_programs: int = 1200, seed: int = 0, test_fraction: float = 0.2,
              n_trees: int = 15, max_depth: int = 6) -> "MLPassSelector":
        corpus = generate_corpus(n_programs, seed)
        rows = []
        for func, lang, labels in corpus:
            rows.append((featurize(FeatureExtractor().extract(func), lang), labels))
        rng = random.Random(seed + 1)
        rng.shuffle(rows)
        cut = int(len(rows) * (1 - test_fraction))
        train, test = rows[:cut], rows[cut:]

        models, per_pass = {}, {}
        for p in PASS_ORDER:
            X, y = [r[0] for r in train], [r[1][p] for r in train]
            forest = RandomForest(n_trees, max_depth, seed).fit(X, y, FEATURE_NAMES)
            tree = DecisionTree(max_depth=4, seed=seed).fit(X, y, FEATURE_NAMES)
            models[p] = PassModel(forest, tree)

            yt = [r[1][p] for r in test]
            pred = [forest.predict(r[0]) for r in test]
            tp = sum(1 for a, b in zip(pred, yt) if a == 1 and b == 1)
            fp = sum(1 for a, b in zip(pred, yt) if a == 1 and b == 0)
            fn = sum(1 for a, b in zip(pred, yt) if a == 0 and b == 1)
            majority = max(sum(yt), len(yt) - sum(yt)) / max(1, len(yt))
            per_pass[p] = {"accuracy": sum(1 for a, b in zip(pred, yt) if a == b) / max(1, len(yt)),
                           "precision": tp / (tp + fp) if tp + fp else 1.0,
                           "recall": tp / (tp + fn) if tp + fn else 1.0, "baseline": majority}
        overall = sum(m["accuracy"] for m in per_pass.values()) / len(per_pass)
        base = sum(m["baseline"] for m in per_pass.values()) / len(per_pass)
        return cls(models, EvalReport(per_pass, overall, base, len(train), len(test)))

    # ------------------------------------------------------------------ selection

    def select(self, func, language: str, features: FunctionFeatures = None) -> List[PassRecommendation]:
        f = features or FeatureExtractor().extract(func)
        x = featurize(f, language)
        recs = []
        for p in PASS_ORDER:
            m = self.models[p]
            conf = round(m.forest.predict_proba(x), 2)
            path = m.tree.decision_path(x)
            why = (f"ML forest: P(useful) = {conf:.2f}; typical reasoning: "
                   + (" and ".join(path) if path else "same outcome for every training program"))
            recs.append(PassRecommendation(p, conf, conf >= self.THRESHOLD, why,
                                           evidence={"model": "random_forest", "decision_path": path}))
        return recs

    def explain(self, pass_name: str) -> str:
        """The readable rule tree for one pass."""
        return self.models[pass_name].tree.to_rules()

    # ------------------------------------------------------------------ persistence

    def save(self, path: str = DEFAULT_MODEL_PATH):
        blob = {"features": FEATURE_NAMES,
                "models": {p: {"forest": m.forest.to_dict(), "tree": m.tree.to_dict()} for p, m in self.models.items()},
                "eval": None if self.eval_report is None else {
                    "per_pass": self.eval_report.per_pass, "overall": self.eval_report.overall_accuracy,
                    "baseline": self.eval_report.baseline_accuracy, "n_train": self.eval_report.n_train,
                    "n_test": self.eval_report.n_test}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(blob, fh)

    @classmethod
    def load(cls, path: str = DEFAULT_MODEL_PATH) -> "MLPassSelector":
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        if blob["features"] != FEATURE_NAMES:
            raise ValueError("model was trained with a different feature set - retrain it")
        models = {p: PassModel(RandomForest.from_dict(m["forest"]), DecisionTree.from_dict(m["tree"]))
                  for p, m in blob["models"].items()}
        ev = blob.get("eval")
        report = None if not ev else EvalReport(ev["per_pass"], ev["overall"], ev["baseline"], ev["n_train"], ev["n_test"])
        return cls(models, report)

    @classmethod
    def load_or_train(cls, path: str = DEFAULT_MODEL_PATH, **train_kw) -> "MLPassSelector":
        try:
            return cls.load(path)
        except (OSError, ValueError, KeyError):
            sel = cls.train(**train_kw)
            try:
                sel.save(path)
            except OSError:
                pass
            return sel