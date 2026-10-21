"""
Language-aware operator semantics for the Common IR.
====================================================
ONE place that defines what `a + b`, `a / b`, `a % b`, `!a`, ... mean for
each source language. It is shared by:

  * the constant-folding pass   (folds only when the answer is certain)
  * the IR interpreter          (executes programs; used by tests now and by
                                 semantic validation / the Digital Twin later)

Why it matters: the same IR text `7 / 2` means 3 in C/C++/Java (integer
division, truncated toward zero) but 3.5 in Python 3. `-7 % 3` is -1 in
C-family languages and 2 in Python. An optimizer that ignores this would
"optimize" programs into different programs.

`wrap=False` (folding mode): anything uncertain raises `Unfoldable`
(32-bit overflow, division by zero, strings in C, ...), so the optimizer
simply leaves that expression alone.
`wrap=True` (execution mode): C-family ints wrap to 32 bits like real
hardware; division by zero raises ZeroDivisionError.
"""

import math

C_FAMILY = ("c", "cpp", "java")
INT_MIN, INT_MAX = -(2 ** 31), 2 ** 31 - 1

ARITH = {"+", "-", "*", "/", "//", "%", "**", "<<", ">>", "&", "|", "^"}
COMPARE = {"<", ">", "<=", ">=", "==", "!="}
LOGICAL = {"&&", "||"}


class Unfoldable(Exception):
    """The result is not statically certain -- leave the expression alone."""


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float))          # bool counts as int


def _wrap32(v):
    v &= 0xFFFFFFFF
    return v - 2 ** 32 if v >= 2 ** 31 else v


def _fit(v, lang, wrap):
    """Range-check / wrap an int result for C-family languages."""
    if lang in C_FAMILY and is_int(v) and not (INT_MIN <= v <= INT_MAX):
        if wrap:
            return _wrap32(v)
        raise Unfoldable("32-bit integer overflow")
    return v


def _trunc_div(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def literal_type(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return "string"


def truthy(v, lang):
    if isinstance(v, str) and lang in C_FAMILY:
        raise Unfoldable("string truthiness is not defined here")
    return bool(v)


def binop(op, a, b, lang, wrap=False):
    cfam = lang in C_FAMILY

    if op in LOGICAL:
        if lang == "python" and not (isinstance(a, bool) and isinstance(b, bool)):
            return (a and b) if op == "&&" else (a or b)   # Python returns an operand
        ta, tb = truthy(a, lang), truthy(b, lang)
        return (ta and tb) if op == "&&" else (ta or tb)

    if op in COMPARE:
        if isinstance(a, str) or isinstance(b, str):
            if not (lang == "python" and isinstance(a, str) and isinstance(b, str)):
                raise Unfoldable("string comparison")
        elif not (is_num(a) and is_num(b)):
            raise Unfoldable("non-numeric comparison")
        return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b,
                "==": a == b, "!=": a != b}[op]

    if op == "+" and isinstance(a, str) and isinstance(b, str):
        if lang in ("python", "java"):
            return a + b
        raise Unfoldable("string concatenation")
    if wrap and lang == "python" and op == "*" and \
            ((isinstance(a, str) and is_int(b)) or (is_int(a) and isinstance(b, str))):
        return a * b                                  # execution mode only: "ab" * 2
    if isinstance(a, str) or isinstance(b, str):
        raise Unfoldable("string arithmetic")
    if not (is_num(a) and is_num(b)):
        raise Unfoldable("non-numeric operands")

    a = int(a) if isinstance(a, bool) else a
    b = int(b) if isinstance(b, bool) else b
    both_int = is_int(a) and is_int(b)

    if op == "+":
        return _fit(a + b, lang, wrap)
    if op == "-":
        return _fit(a - b, lang, wrap)
    if op == "*":
        return _fit(a * b, lang, wrap)

    if op == "/":
        if b == 0:
            raise ZeroDivisionError("division by zero")
        if both_int and cfam:
            return _fit(_trunc_div(a, b), lang, wrap)
        r = a / b
        if math.isinf(r) or math.isnan(r):
            raise Unfoldable("non-finite float result")
        return r

    if op == "//":
        if lang != "python" or not (both_int or wrap):
            raise Unfoldable("floor division")
        if b == 0:
            raise ZeroDivisionError("division by zero")
        return a // b

    if op == "%":
        if not both_int:
            if wrap and lang == "python":            # execution mode: Python allows float %
                if b == 0:
                    raise ZeroDivisionError("modulo by zero")
                return a % b
            raise Unfoldable("float modulo")
        if b == 0:
            raise ZeroDivisionError("modulo by zero")
        return _fit(a - b * _trunc_div(a, b), lang, wrap) if cfam else a % b

    if op == "**":
        if lang != "python" or not both_int or not (0 <= b <= 64):
            raise Unfoldable("power")
        return a ** b

    if op in ("<<", ">>", "&", "|", "^"):
        if not both_int:
            raise Unfoldable("bitwise on non-int")
        if op in ("<<", ">>"):
            if not (0 <= b <= (31 if cfam else 64)):
                raise Unfoldable("shift amount out of range")
            return _fit(a << b, lang, wrap) if op == "<<" else a >> b
        return {"&": a & b, "|": a | b, "^": a ^ b}[op]

    raise Unfoldable(f"unknown operator {op!r}")


def unop(op, a, lang, wrap=False):
    if op == "!":
        if isinstance(a, str) and lang in C_FAMILY:
            raise Unfoldable("string truthiness")
        return not a
    if isinstance(a, str) or not is_num(a):
        raise Unfoldable("unary on non-numeric")
    a = int(a) if isinstance(a, bool) else a
    if op == "-":
        return _fit(-a, lang, wrap)
    if op == "~" and is_int(a):
        return ~a
    raise Unfoldable(f"unknown unary operator {op!r}")
