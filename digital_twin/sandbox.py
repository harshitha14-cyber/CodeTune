"""
Optimization Sandbox (report 3.2 / 4.1: "separate optimization state spaces for
parallel experimentation").

Every strategy runs on its OWN deep copy of the function, so experiments can
never influence each other or the original program. They can be executed one
after another or on a thread pool. (CPython threads do not make CPU-bound work
faster; the pool demonstrates isolation and keeps the API ready for processes.)
Results always come back in the order the strategies were given.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..validation.differential_tester import ValidationResult
from .strategy import Strategy


@dataclass
class TwinMetrics:
    predicted_cost: float                 # static estimate (nothing executed)
    measured_cost: Optional[float]        # interpreter-measured average, same weights
    code_size: int
    lines: int
    memory_bytes: int

    @property
    def prediction_error_pct(self) -> Optional[float]:
        if not self.measured_cost:
            return None
        return round(100.0 * abs(self.predicted_cost - self.measured_cost) / self.measured_cost, 1)


@dataclass
class Experiment:
    strategy: Strategy
    func: object                          # the optimized FuncDecl (a private copy)
    changes: list
    metrics: Optional[TwinMetrics]
    valid: bool
    validation: Optional[ValidationResult] = None
    error: Optional[str] = None           # a faulty pass raised
    opt_time_ms: float = 0.0
    saving_pct: float = 0.0               # predicted, vs the ORIGINAL function
    measured_saving_pct: Optional[float] = None


class Sandbox:
    def __init__(self, simulate: Callable[[Strategy], Experiment]):
        self._simulate = simulate

    def run(self, strategies: List[Strategy], parallel: bool = False, workers: int = 4) -> List[Experiment]:
        if not parallel:
            return [self._simulate(s) for s in strategies]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._simulate, strategies))