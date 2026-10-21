"""
Strength reduction & algebraic simplification: swap an expensive operation
for a cheaper, equivalent one.

    n * 8   ->  n << 3        (n provably an integer)
    n * 2   ->  n + n         (n a plain variable of unknown type -- always valid)
    n * 1   ->  n             n + 0 -> n        n * 0 -> 0 (n int, side-effect free)

Deliberately NOT done (and why -- useful to explain in a viva):
  * n / 2^k -> n >> k  : for NEGATIVE signed n, `/` rounds toward zero but
                         `>>` rounds down, so the result differs.
  * n % 2^k -> n & mask: same sign problem.
  * anything on a float: shifts don't exist; x*0 can be NaN, x+0 can flip -0.0.
  * Python parameters: no type annotations are captured, so `p * 8` might be a
    float or a string; only the always-valid `p * 2 -> p + p` is applied.
"""

from ..ir import ir_nodes as ir
from ..ir.ir_printer import print_expr
from ..ir.ir_utils import (clone, infer_expr_type, infer_var_types, is_pure)
from .base import Change, OptimizationPass, PassResult, map_exprs_in_block


def _int_lit(e, value=None):
    ok = isinstance(e, ir.Literal) and e.type == "int" and not isinstance(e.value, bool)
    return ok and (value is None or e.value == value)


def _pow2_exp(e):
    """k if e is an int literal equal to 2**k (k >= 1), else None."""
    if _int_lit(e) and e.value >= 2 and (e.value & (e.value - 1)) == 0:
        return e.value.bit_length() - 1
    return None


class StrengthReduction(OptimizationPass):
    name = "strength_reduction"
    description = "Replace costly operations with cheaper equivalents."

    def run(self, func, language) -> PassResult:
        new = clone(func)
        types = infer_var_types(new, language)
        changes = []

        def ty(e):
            return infer_expr_type(e, types, language)

        def rewrite(e):
            if isinstance(e, ir.BinOp):
                e.left, e.right = rewrite(e.left), rewrite(e.right)
                out = self._reduce(e, ty, language)
            elif isinstance(e, ir.UnaryOp):
                e.operand = rewrite(e.operand)
                return e
            elif isinstance(e, ir.Call):
                e.args = [rewrite(a) for a in e.args]
                return e
            else:
                return e
            if out is None:
                return e
            changes.append(Change(self.name, e.line, f"{print_expr(e)} -> {print_expr(out)}"))
            return out

        map_exprs_in_block(new.body, rewrite)
        return PassResult(new, changes)

    def _reduce(self, e, ty, language):
        l, r, op, line = e.left, e.right, e.op, e.line
        if isinstance(l, ir.Literal) and isinstance(r, ir.Literal):
            return None                      # constant folding's job
        lt, rt = ty(l), ty(r)

        if op == "*":
            for x, lit, xt in ((l, r, lt), (r, l, rt)):
                k = _pow2_exp(lit)
                if k is not None:
                    if xt == "int":
                        return ir.BinOp(op="<<", left=x, right=ir.Literal(value=k, type="int", line=line), line=line)
                    if k == 1 and isinstance(x, ir.Identifier):
                        return ir.BinOp(op="+", left=x, right=ir.Identifier(name=x.name, line=line), line=line)
                if _int_lit(lit, 1) and xt in ("int", "float"):
                    return x
                if _int_lit(lit, 0) and xt == "int" and is_pure(x):
                    return ir.Literal(value=0, type="int", line=line)

        elif op == "+":
            if _int_lit(r, 0) and lt == "int":
                return l
            if _int_lit(l, 0) and rt == "int":
                return r

        elif op == "-":
            if _int_lit(r, 0) and lt in ("int", "float"):
                return l

        elif op == "/":
            # Python's `/` always yields a float, so int x / 1 -> x would change the type.
            if _int_lit(r, 1) and (lt == "float" or (lt == "int" and language != "python")):
                return l
        return None
