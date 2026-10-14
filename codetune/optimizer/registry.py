"""Single place that lists the available passes and the order they run in."""

from .constant_folding import ConstantFolding
from .constant_propagation import ConstantPropagation
from .dead_code_elimination import DeadCodeElimination
from .strength_reduction import StrengthReduction

PASS_CLASSES = {
    cls.name: cls
    for cls in (ConstantPropagation, ConstantFolding, StrengthReduction, DeadCodeElimination)
}

# Propagation exposes constants -> folding evaluates them -> strength reduction
# simplifies what is left -> DCE sweeps up the stores that became useless.
PASS_ORDER = [
    "constant_propagation",
    "constant_folding",
    "strength_reduction",
    "dead_code_elimination",
]


def make_pass(name: str):
    if name not in PASS_CLASSES:
        raise ValueError(f"Unknown pass '{name}'. Available: {sorted(PASS_CLASSES)}")
    return PASS_CLASSES[name]()
