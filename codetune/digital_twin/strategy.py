"""
Optimization STRATEGIES: an ordered list of passes plus how many times to
sweep over it. A strategy is what the Digital Twin simulates and compares.

  rounds = 1   run the list once, like a classic fixed pass pipeline
  rounds = N   repeat the list N times
  rounds = 0   repeat until nothing changes (fixpoint, capped at 10)

ORDER MATTERS when rounds is small: propagation before folding turns
`a = 4; b = a*2 + 3` into `b = 11`; folding before propagation leaves it
half done. That sensitivity is exactly what what-if analysis exposes.
"""

import itertools
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..analysis.pass_selector import RuleBasedPassSelector
from ..optimizer.registry import PASS_ORDER, make_pass

SHORT = {"constant_propagation": "CP", "constant_folding": "CF",
         "strength_reduction": "SR", "dead_code_elimination": "DCE"}
_LONG = {v: k for k, v in SHORT.items()}


@dataclass(frozen=True)
class Strategy:
    name: str
    passes: Tuple[str, ...] = ()
    rounds: int = 1
    adaptive: bool = False          # let the rule-based selector choose the passes

    def describe(self) -> str:
        if self.adaptive:
            return "selector-chosen passes, repeated until stable"
        seq = " > ".join(SHORT.get(p, p) for p in self.passes) or "(nothing)"
        reps = "until stable" if self.rounds == 0 else f"x{self.rounds}"
        return f"{seq} {reps}" if self.passes else seq


def normalize(name: str) -> str:
    """Accept CP / cp / constant_propagation."""
    n = name.strip()
    return _LONG.get(n.upper(), n)


def sequence_strategy(passes: Sequence[str], rounds: int = 1, name: Optional[str] = None) -> Strategy:
    passes = tuple(normalize(p) for p in passes)
    label = name or (" > ".join(SHORT.get(p, p) for p in passes) + ("" if rounds == 1 else
                                                                   (" (to fixpoint)" if rounds == 0 else f" x{rounds}")))
    return Strategy(label, passes, rounds)


def default_strategies() -> List[Strategy]:
    out = [Strategy("baseline (no optimization)", (), 1)]
    out += [Strategy(f"only {SHORT[p]}", (p,), 1) for p in PASS_ORDER]
    out += [
        Strategy("canonical order x1", tuple(PASS_ORDER), 1),
        Strategy("reverse order x1", tuple(reversed(PASS_ORDER)), 1),
        Strategy("canonical to fixpoint", tuple(PASS_ORDER), 0),
        Strategy("adaptive (selector)", (), 0, adaptive=True),
    ]
    return out


def permutation_strategies(passes: Sequence[str] = tuple(PASS_ORDER), rounds: int = 1) -> List[Strategy]:
    return [sequence_strategy(p, rounds) for p in itertools.permutations(passes)]


def run_strategy(func, language: str, strategy: Strategy, overrides: Optional[Dict] = None, selector=None):
    """Apply `strategy` to a COPY of `func` (passes never mutate their input).
    Returns (new_func, changes). Exceptions from a faulty pass propagate."""
    overrides = overrides or {}
    passes, rounds = list(strategy.passes), strategy.rounds
    if strategy.adaptive:
        recs = (selector or RuleBasedPassSelector()).select(func, language)
        chosen = {r.pass_name for r in recs if r.selected}
        passes = [p for p in PASS_ORDER if p in chosen]
        rounds = 0

    current, changes = func, []
    for _ in range(10 if rounds == 0 else rounds):
        progressed = False
        for name in passes:
            p = overrides[name] if name in overrides else make_pass(name)
            result = p.run(current, language)
            if result.changed:
                current, progressed = result.func, True
                changes.extend(result.changes)
        if rounds == 0 and not progressed:
            break
    return current, changes