"""
Test-input generation for semantic validation (report Phase 5:
"generate random or boundary test inputs").

For every parameter we build a list of candidate values:
  * BOUNDARY values  (0, 1, -1, INT_MAX, INT_MIN, ...)  -- where optimizers
    most often go wrong (overflow, sign, zero)
  * RANDOM values    from a seeded generator, so runs are reproducible

Typed languages use the declared type. Python parameters have no declared
type, so they get ints AND floats: a rewrite that is only valid for ints
(e.g. `n*8 -> n<<3`) is then caught.
"""

import itertools
import random
from typing import List, Tuple

from ..ir.ir_utils import normalize_type
from ..ir.semantics import INT_MAX, INT_MIN

INT_BOUNDARY = [0, 1, -1, 2, -2, 3, 7, 8, 10, -10, 100, 255, 1024, INT_MAX, INT_MIN, INT_MAX - 1, INT_MIN + 1]
FLOAT_BOUNDARY = [0.0, 1.0, -1.0, 0.5, -0.5, 2.5, 1e6]
SMALL_NONNEG = [0, 1, 2, 3, 10, 100, 255]          # safe for unsigned / char / short / float32


def candidate_values(param, language: str, rng: random.Random, n_random: int) -> list:
    t = "unknown" if language == "python" else normalize_type(param.param_type)
    if t == "int":
        return INT_BOUNDARY + [rng.randint(-1000, 1000) for _ in range(n_random)]
    if t == "float":
        return FLOAT_BOUNDARY + [round(rng.uniform(-100, 100), 3) for _ in range(n_random // 2)]
    if t == "bool":
        return [True, False]
    if t == "string":
        return ["", "a", "hello"]
    if language == "python":
        return (INT_BOUNDARY[:13] + [rng.randint(-1000, 1000) for _ in range(n_random)]
                + FLOAT_BOUNDARY[:5])
    return SMALL_NONNEG + [rng.randint(0, 1000) for _ in range(n_random // 2)]


def generate_inputs(func, language: str, max_cases: int = 150, n_random: int = 30,
                    seed: int = 0) -> List[Tuple]:
    """Deterministic list of argument tuples for `func` (at most `max_cases`)."""
    rng = random.Random(seed)
    pools = [candidate_values(p, language, rng, n_random) for p in func.params]
    if not pools:
        return [()]

    total = 1
    for p in pools:
        total *= len(p)
    if total <= max_cases:
        return list(itertools.product(*pools))

    cases, seen = [], set()

    def add(c):
        key = tuple((type(v).__name__, v) for v in c)
        if key not in seen:
            seen.add(key)
            cases.append(c)

    longest = max(len(p) for p in pools)
    for i in range(longest):                         # walk every pool's values at least once
        add(tuple(p[i % len(p)] for p in pools))
    while len(cases) < max_cases:                    # then random combinations
        add(tuple(rng.choice(p) for p in pools))
    return cases[:max_cases]