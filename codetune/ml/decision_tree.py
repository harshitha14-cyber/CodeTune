"""
Decision tree and random forest in plain Python (no scikit-learn needed).

Written from scratch on purpose: the report asks for an EXPLAINABLE selector, and
a hand-made CART tree can print its own rules and the exact path a prediction
took. Binary classification only (label 0 / 1); `predict_proba` returns P(1).

  DecisionTree  CART with Gini impurity, depth / leaf-size limits
  RandomForest  bagging + random feature subsets; probability = mean of trees
"""

import math
import random
from typing import Dict, List, Optional, Sequence


def _gini(pos: int, n: int) -> float:
    if n == 0:
        return 0.0
    p = pos / n
    return 2.0 * p * (1.0 - p)


class DecisionTree:
    def __init__(self, max_depth: int = 6, min_samples_split: int = 4, min_samples_leaf: int = 2,
                 max_features: Optional[int] = None, seed: int = 0):
        self.max_depth, self.min_samples_split = max_depth, min_samples_split
        self.min_samples_leaf, self.max_features = min_samples_leaf, max_features
        self.rng = random.Random(seed)
        self.feature_names: List[str] = []
        self.root: Dict = {"leaf": True, "p": 0.0, "n": 0}

    # ------------------------------------------------------------------ training

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int], feature_names: Sequence[str]) -> "DecisionTree":
        self.feature_names = list(feature_names)
        self.root = self._grow(list(range(len(X))), X, y, depth=0)
        return self

    def _leaf(self, idx, y):
        pos = sum(y[i] for i in idx)
        return {"leaf": True, "p": (pos / len(idx)) if idx else 0.0, "n": len(idx)}

    def _grow(self, idx, X, y, depth):
        pos = sum(y[i] for i in idx)
        if depth >= self.max_depth or len(idx) < self.min_samples_split or pos in (0, len(idx)):
            return self._leaf(idx, y)
        split = self._best_split(idx, X, y)
        if split is None:
            return self._leaf(idx, y)
        f, thr = split
        left = [i for i in idx if X[i][f] <= thr]
        right = [i for i in idx if X[i][f] > thr]
        return {"leaf": False, "f": f, "t": thr, "n": len(idx), "p": pos / len(idx),
                "l": self._grow(left, X, y, depth + 1), "r": self._grow(right, X, y, depth + 1)}

    def _best_split(self, idx, X, y):
        n_feat = len(X[0])
        feats = list(range(n_feat))
        if self.max_features and self.max_features < n_feat:
            feats = self.rng.sample(feats, self.max_features)
        n, total_pos = len(idx), sum(y[i] for i in idx)
        parent = _gini(total_pos, n)
        best_gain, best = 1e-9, None
        for f in feats:
            order = sorted(idx, key=lambda i: X[i][f])
            left_pos = 0
            for k in range(1, n):
                left_pos += y[order[k - 1]]
                a, b = X[order[k - 1]][f], X[order[k]][f]
                if a == b or k < self.min_samples_leaf or n - k < self.min_samples_leaf:
                    continue
                gain = parent - (k / n) * _gini(left_pos, k) - ((n - k) / n) * _gini(total_pos - left_pos, n - k)
                if gain > best_gain:
                    best_gain, best = gain, (f, (a + b) / 2.0)
        return best

    # ------------------------------------------------------------------ prediction

    def predict_proba(self, x: Sequence[float]) -> float:
        node = self.root
        while not node["leaf"]:
            node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
        return node["p"]

    def predict(self, x) -> int:
        return 1 if self.predict_proba(x) >= 0.5 else 0

    def decision_path(self, x: Sequence[float]) -> List[str]:
        """Human-readable conditions that led to this prediction."""
        node, path = self.root, []
        while not node["leaf"]:
            name = self.feature_names[node["f"]]
            if x[node["f"]] <= node["t"]:
                path.append(f"{name} <= {node['t']:.3g}")
                node = node["l"]
            else:
                path.append(f"{name} > {node['t']:.3g}")
                node = node["r"]
        return path

    def to_rules(self) -> str:
        lines: List[str] = []

        def walk(node, depth):
            pad = "  " * depth
            if node["leaf"]:
                lines.append(f"{pad}-> P(useful) = {node['p']:.2f}   ({node['n']} training programs)")
                return
            name = self.feature_names[node["f"]]
            lines.append(f"{pad}if {name} <= {node['t']:.3g}:")
            walk(node["l"], depth + 1)
            lines.append(f"{pad}else:   # {name} > {node['t']:.3g}")
            walk(node["r"], depth + 1)
        walk(self.root, 0)
        return "\n".join(lines)

    # ------------------------------------------------------------------ persistence

    def to_dict(self) -> Dict:
        return {"feature_names": self.feature_names, "root": self.root}

    @classmethod
    def from_dict(cls, d: Dict) -> "DecisionTree":
        t = cls()
        t.feature_names, t.root = d["feature_names"], d["root"]
        return t


class RandomForest:
    def __init__(self, n_trees: int = 15, max_depth: int = 6, seed: int = 0):
        self.n_trees, self.max_depth, self.seed = n_trees, max_depth, seed
        self.trees: List[DecisionTree] = []

    def fit(self, X, y, feature_names) -> "RandomForest":
        rng = random.Random(self.seed)
        mf = max(1, int(math.sqrt(len(feature_names))) + 1)
        self.trees = []
        for k in range(self.n_trees):
            sample = [rng.randrange(len(X)) for _ in range(len(X))]
            t = DecisionTree(max_depth=self.max_depth, max_features=mf, seed=self.seed * 1000 + k)
            t.fit([X[i] for i in sample], [y[i] for i in sample], feature_names)
            self.trees.append(t)
        return self

    def predict_proba(self, x) -> float:
        return sum(t.predict_proba(x) for t in self.trees) / len(self.trees)

    def predict(self, x) -> int:
        return 1 if self.predict_proba(x) >= 0.5 else 0

    def to_dict(self) -> Dict:
        return {"trees": [t.to_dict() for t in self.trees]}

    @classmethod
    def from_dict(cls, d: Dict) -> "RandomForest":
        f = cls(n_trees=len(d["trees"]))
        f.trees = [DecisionTree.from_dict(t) for t in d["trees"]]
        return f