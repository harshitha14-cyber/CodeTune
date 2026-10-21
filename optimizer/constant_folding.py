"""
Constant folding: evaluate expressions whose operands are all literals.

    2 * 3 + 1      ->  7
    !(4 > 9)       ->  true
    false && f(x)  ->  false        (short-circuit: f is never called)

Safety rules (this is where "optimizing" can silently change a program):
  * Uses the language's OWN arithmetic (ir/semantics.py): C/Java integer
    division truncates, Python's `/` is true division, `%` differs, ...
  * Never folds when the answer is uncertain: division by zero, 32-bit
    overflow in C-family languages, string comparison in C, etc.
"""

from ..ir import ir_nodes as ir
from ..ir import semantics as sem
from ..ir.ir_printer import print_expr
from ..ir.ir_utils import clone
from .base import Change, OptimizationPass, PassResult, map_exprs_in_block


class ConstantFolding(OptimizationPass):
    name = "constant_folding"
    description = "Evaluate constant expressions at compile time."

    def run(self, func, language) -> PassResult:
        new = clone(func)
        changes = []

        def fold(e):
            if isinstance(e, ir.BinOp):
                e.left, e.right = fold(e.left), fold(e.right)
                result = self._fold_binop(e, language)
            elif isinstance(e, ir.UnaryOp):
                e.operand = fold(e.operand)
                result = self._fold_unop(e, language)
            elif isinstance(e, ir.Call):
                e.args = [fold(a) for a in e.args]
                return e
            else:
                return e
            if result is None:
                return e
            changes.append(Change(self.name, e.line,
                                  f"folded {print_expr(e)} -> {print_expr(result)}"))
            return result

        map_exprs_in_block(new.body, fold)
        return PassResult(new, changes)

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _lit(value, line):
        return ir.Literal(value=value, type=sem.literal_type(value), line=line)

    def _fold_binop(self, e, language):
        l, r = e.left, e.right
        # short-circuit with a known left operand (right side may be anything)
        if e.op in sem.LOGICAL and isinstance(l, ir.Literal):
            try:
                t = sem.truthy(l.value, language)
            except sem.Unfoldable:
                return None
            if language == "python" and not isinstance(l.value, bool):
                return None                       # Python `and`/`or` return operands
            if e.op == "&&" and not t:
                return self._lit(False, e.line)
            if e.op == "||" and t:
                return self._lit(True, e.line)
            return None
        if not (isinstance(l, ir.Literal) and isinstance(r, ir.Literal)):
            return None
        try:
            return self._lit(sem.binop(e.op, l.value, r.value, language), e.line)
        except (sem.Unfoldable, ZeroDivisionError):
            return None

    def _fold_unop(self, e, language):
        if not isinstance(e.operand, ir.Literal):
            return None
        try:
            return self._lit(sem.unop(e.op, e.operand.value, language), e.line)
        except sem.Unfoldable:
            return None
