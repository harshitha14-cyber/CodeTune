"""
Small helpers shared by every optimization pass and analysis.

  clone()            deep copy (passes never mutate their input)
  expr_vars()        variables READ by an expression
  is_pure()          can this expression be deleted without changing behaviour?
  local_names()      names that are provably local to a function
  infer_var_types()  best-effort type of every local ("int", "float", ...)
  infer_expr_type()  type of one expression given those variable types
"""

import copy
from typing import Dict, Iterator, Set

from . import ir_nodes as ir
from .semantics import C_FAMILY, COMPARE, LOGICAL

UNKNOWN = "unknown"
_BOTTOM = "bottom"       # "no information yet" during Python type inference


def clone(node):
    return copy.deepcopy(node)


# ---------------------------------------------------------------------------
# Expression helpers
# ---------------------------------------------------------------------------

def walk_expr(e) -> Iterator:
    """Yield `e` and every sub-expression of it."""
    if e is None:
        return
    yield e
    if isinstance(e, ir.BinOp):
        yield from walk_expr(e.left)
        yield from walk_expr(e.right)
    elif isinstance(e, ir.UnaryOp):
        yield from walk_expr(e.operand)
    elif isinstance(e, ir.Call):
        for a in e.args:
            yield from walk_expr(a)


def expr_vars(e) -> Set[str]:
    return {n.name for n in walk_expr(e) if isinstance(n, ir.Identifier)}


def has_call(e) -> bool:
    return any(isinstance(n, ir.Call) for n in walk_expr(e))


def is_pure(e) -> bool:
    """True if evaluating `e` can have no observable effect, so a dead use
    of it may be deleted. Calls may have side effects. Division / modulo by
    anything other than a non-zero literal may trap, so they are not pure."""
    for n in walk_expr(e):
        if isinstance(n, ir.Call):
            return False
        if isinstance(n, ir.BinOp) and n.op in ("/", "//", "%"):
            r = n.right
            if not (isinstance(r, ir.Literal) and isinstance(r.value, (int, float))
                    and not isinstance(r.value, bool) and r.value != 0):
                return False
    return True


# ---------------------------------------------------------------------------
# Statement walking
# ---------------------------------------------------------------------------

def walk_stmts(block) -> Iterator:
    """Yield every statement in a block, recursing into if/while bodies."""
    for s in block.statements:
        yield s
        if isinstance(s, ir.If):
            yield from walk_stmts(s.then_block)
            if s.else_block is not None:
                yield from walk_stmts(s.else_block)
        elif isinstance(s, ir.While):
            yield from walk_stmts(s.body)


def defined_names(block) -> Set[str]:
    """Names (re)defined anywhere inside `block` (VarDecl or Assign)."""
    out = set()
    for s in walk_stmts(block):
        if isinstance(s, ir.VarDecl):
            out.add(s.name)
        elif isinstance(s, ir.Assign):
            out.add(s.target)
    return out


def definitely_returns(block) -> bool:
    """True if control can never fall off the end of `block`."""
    for s in block.statements:
        if isinstance(s, ir.Return):
            return True
        if isinstance(s, ir.If) and s.else_block is not None \
                and definitely_returns(s.then_block) and definitely_returns(s.else_block):
            return True
    return False


# ---------------------------------------------------------------------------
# Locals
# ---------------------------------------------------------------------------

def local_names(func, language) -> Set[str]:
    """Names that are provably local to `func`.

    A C/C++/Java function can also assign to a global or a field (`count = 1`)
    without declaring it, and a call may change it -- such names must never be
    propagated or deleted. In Python any assigned name is local (no `global`
    statements are supported by the front-end)."""
    names = {p.name for p in func.params}
    for s in walk_stmts(func.body):
        if isinstance(s, ir.VarDecl):
            names.add(s.name)
        elif isinstance(s, ir.Assign) and language == "python":
            names.add(s.target)
    return {n for n in names if n.isidentifier()}


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

_INT_NAMES = {"int", "long", "long long", "long int", "long long int", "integer", "long"}
_FLOAT_NAMES = {"double"}
_BOOL_NAMES = {"bool", "boolean", "_bool"}


def normalize_type(t: str) -> str:
    """Map a declared type name to a coarse type CodeTune can reason about.
    Narrow / unsigned / 32-bit-float types return UNKNOWN on purpose: their
    wrap-around and rounding rules differ, so we stay conservative."""
    t = (t or "").replace("const", "").replace("final", "").replace("static", "").strip().lower()
    if t in _INT_NAMES:
        return "int"
    if t in _FLOAT_NAMES:
        return "float"
    if t in _BOOL_NAMES:
        return "bool"
    if t == "string":
        return "string"
    return UNKNOWN


def infer_expr_type(e, var_types: Dict[str, str], language: str = "python") -> str:
    if isinstance(e, ir.Literal):
        return e.type
    if isinstance(e, ir.Identifier):
        return var_types.get(e.name, UNKNOWN)
    if isinstance(e, ir.UnaryOp):
        t = infer_expr_type(e.operand, var_types, language)
        if e.op == "!":
            return "bool"
        return t if t in ("int", "float", _BOTTOM) else UNKNOWN
    if isinstance(e, ir.BinOp):
        if e.op in COMPARE or (e.op in LOGICAL and language in C_FAMILY):
            return "bool"
        lt = infer_expr_type(e.left, var_types, language)
        rt = infer_expr_type(e.right, var_types, language)
        if _BOTTOM in (lt, rt):
            return _BOTTOM
        if lt == "int" and rt == "int":
            if e.op == "/":
                return "float" if language == "python" else "int"
            return "int"
        if {lt, rt} <= {"int", "float"} and "float" in (lt, rt):
            if e.op in ("+", "-", "*", "/"):
                return "float"
        return UNKNOWN
    return UNKNOWN          # calls and anything else


def infer_var_types(func, language) -> Dict[str, str]:
    """Type of each local variable of `func`.

    Typed languages: taken from the declarations (params + VarDecl).
    Python: inferred. A variable is "int" only if EVERY assignment to it is
    provably int, and parameters are always unknown (no annotations are
    captured), so Python gets fewer type-dependent optimizations -- by
    design, because guessing wrong would change program behaviour."""
    if language != "python":
        types = {p.name: normalize_type(p.param_type) for p in func.params}
        for s in walk_stmts(func.body):
            if isinstance(s, ir.VarDecl):
                types[s.name] = normalize_type(s.var_type)
        return types

    types = {p.name: UNKNOWN for p in func.params}
    assigns = [(s.target, s.value) for s in walk_stmts(func.body) if isinstance(s, ir.Assign)]
    for name, _ in assigns:
        types.setdefault(name, _BOTTOM)
    for _ in range(6):                                  # fixpoint over the lattice
        changed = False
        for name, value in assigns:
            if types[name] == UNKNOWN:
                continue
            t = infer_expr_type(value, types, language)
            new = t if types[name] in (_BOTTOM, t) else UNKNOWN
            if t == _BOTTOM:
                new = types[name]
            if new != types[name]:
                types[name], changed = new, True
        if not changed:
            break
    return {k: (UNKNOWN if v == _BOTTOM else v) for k, v in types.items()}
