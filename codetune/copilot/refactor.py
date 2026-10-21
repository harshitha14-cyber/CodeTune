"""
Interactive refactoring for the Copilot (report 3.3: "suggests code modifications
that enable better optimization opportunities").

  find_suggestions()       analysers that spot patterns a compiler cannot fix
                           by itself (loop-invariant work, repeated expressions,
                           unused variables, unknown loop bounds, ...)
  hoist_loop_invariants()  one real, automatic refactoring: computations inside a
                           while-loop that do not change between iterations are
                           moved in front of the loop into a temporary.

A refactoring is only ever OFFERED as "verified" after the Digital Twin's
validator ran the original and the refactored function side by side.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..digital_twin.cost_model import COST_WEIGHTS
from ..ir import ir_nodes as ir
from ..ir.ir_printer import print_expr
from ..ir.ir_utils import (clone, defined_names, expr_vars, infer_expr_type, infer_var_types, is_pure,
                           local_names, walk_expr, walk_stmts)
from ..optimizer.base import Change

HEAVY_OPS = {"*", "/", "//", "%", "**"}


@dataclass
class Suggestion:
    kind: str                    # hoist | cse | unused | loop_bound | heavy_op_in_loop | untyped | unknown_call
    line: int
    severity: str                # tip | warning | info
    message: str
    fix: str = ""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _stmt_exprs(s) -> list:
    if isinstance(s, ir.VarDecl):
        return [s.init] if s.init is not None else []
    if isinstance(s, ir.Assign):
        return [s.value]
    if isinstance(s, ir.ExprStmt):
        return [s.expr]
    if isinstance(s, ir.Return):
        return [s.value] if s.value is not None else []
    if isinstance(s, (ir.If, ir.While)):
        return [s.cond]
    return []


def _worth_hoisting(e) -> bool:
    nodes = [n for n in walk_expr(e) if isinstance(n, ir.BinOp)]
    return any(n.op in HEAVY_OPS for n in nodes) or len(nodes) >= 2


def _invariant_candidates(e, assigned) -> list:
    """Maximal sub-expressions of `e` that cannot change between iterations."""
    if not isinstance(e, ir.BinOp):
        if isinstance(e, ir.UnaryOp):
            return _invariant_candidates(e.operand, assigned)
        if isinstance(e, ir.Call):
            return [c for a in e.args for c in _invariant_candidates(a, assigned)]
        return []
    names = expr_vars(e)
    if names and not (names & assigned) and is_pure(e) and _worth_hoisting(e):
        return [e]
    return _invariant_candidates(e.left, assigned) + _invariant_candidates(e.right, assigned)


def _raw_types(func) -> Dict[str, str]:
    t = {p.name: p.param_type for p in func.params}
    for s in walk_stmts(func.body):
        if isinstance(s, ir.VarDecl):
            t[s.name] = s.var_type
    return t


# ---------------------------------------------------------------------------
# refactoring: hoist loop-invariant computations
# ---------------------------------------------------------------------------

def hoist_loop_invariants(func, language) -> Tuple["ir.FuncDecl", List[Change]]:
    new = clone(func)
    raw, changes = _raw_types(new), []
    types = infer_var_types(new, language)
    taken = set(raw) | {s.target for s in walk_stmts(new.body) if isinstance(s, ir.Assign)}
    counter = [0]

    def temp_type(e) -> Optional[str]:
        if language == "python":
            return "var"
        names = expr_vars(e)
        kinds = {raw.get(n) for n in names}
        if kinds <= {"int"} and infer_expr_type(e, types, language) == "int":
            return "int"
        if kinds <= {"int", "double"} and "double" in kinds and infer_expr_type(e, types, language) == "float":
            return "double"
        return None

    def process(block):
        out = []
        for s in block.statements:
            if isinstance(s, ir.If):
                process(s.then_block)
                if s.else_block is not None:
                    process(s.else_block)
            if isinstance(s, ir.While):
                process(s.body)
                assigned = defined_names(s.body)
                shared: Dict[str, str] = {}
                hoisted = []

                def rewrite(e):
                    if e is None:
                        return e
                    if isinstance(e, ir.BinOp):
                        names = expr_vars(e)
                        if names and not (names & assigned) and is_pure(e) and _worth_hoisting(e):
                            ty = temp_type(e)
                            if ty is not None:
                                key = print_expr(e)
                                if key not in shared:
                                    counter[0] += 1
                                    nm = f"_hoisted{counter[0]}"
                                    while nm in taken:
                                        counter[0] += 1
                                        nm = f"_hoisted{counter[0]}"
                                    taken.add(nm)
                                    shared[key] = nm
                                    init = clone(e)
                                    hoisted.append(ir.Assign(target=nm, value=init, line=e.line) if language == "python"
                                                   else ir.VarDecl(name=nm, var_type=ty, init=init, line=e.line))
                                    changes.append(Change("loop_invariant_hoisting", e.line,
                                                          f"moved {key} out of the loop into {nm}"))
                                return ir.Identifier(name=shared[key], line=e.line)
                        e.left, e.right = rewrite(e.left), rewrite(e.right)
                    elif isinstance(e, ir.UnaryOp):
                        e.operand = rewrite(e.operand)
                    elif isinstance(e, ir.Call):
                        e.args = [rewrite(a) for a in e.args]
                    return e

                for inner in walk_stmts(s.body):
                    if isinstance(inner, ir.VarDecl) and inner.init is not None:
                        inner.init = rewrite(inner.init)
                    elif isinstance(inner, ir.Assign):
                        inner.value = rewrite(inner.value)
                    elif isinstance(inner, ir.ExprStmt):
                        inner.expr = rewrite(inner.expr)
                    elif isinstance(inner, ir.Return) and inner.value is not None:
                        inner.value = rewrite(inner.value)
                    elif isinstance(inner, ir.If):
                        inner.cond = rewrite(inner.cond)
                    elif isinstance(inner, ir.While):
                        inner.cond = rewrite(inner.cond)
                out.extend(hoisted)
            out.append(s)
        block.statements = out

    process(new.body)
    return new, changes


# ---------------------------------------------------------------------------
# suggestion analysers
# ---------------------------------------------------------------------------

def _loops(block, depth=0):
    for s in block.statements:
        if isinstance(s, ir.While):
            yield s, depth
            yield from _loops(s.body, depth + 1)
        elif isinstance(s, ir.If):
            yield from _loops(s.then_block, depth)
            if s.else_block is not None:
                yield from _loops(s.else_block, depth)


def find_suggestions(func, program, language) -> List[Suggestion]:
    out: List[Suggestion] = []

    # 1. loop-invariant computations
    for loop, _ in _loops(func.body):
        assigned = defined_names(loop.body)
        seen = set()
        for inner in walk_stmts(loop.body):
            for e in _stmt_exprs(inner):
                for cand in _invariant_candidates(e, assigned):
                    key = print_expr(cand)
                    if key not in seen:
                        seen.add(key)
                        out.append(Suggestion(
                            "hoist", cand.line, "tip",
                            f"'{key}' is recomputed on every iteration but its inputs never change inside the loop.",
                            f"Compute it once before the loop: tmp = {key}; and use tmp inside."))

    # 2. repeated sub-expressions in straight-line code (common subexpression)
    counts: Dict[str, List[int]] = {}

    def forget(var):
        for k in [k for k in counts if var in k.replace("(", " ").replace(")", " ").split()]:
            counts.pop(k)

    for s in func.body.statements:
        if isinstance(s, (ir.If, ir.While)):
            counts.clear()
            continue
        for e in _stmt_exprs(s):
            for n in walk_expr(e):
                if isinstance(n, ir.BinOp) and _worth_hoisting(n) and is_pure(n):
                    counts.setdefault(print_expr(n), []).append(n.line)
        if isinstance(s, (ir.Assign, ir.VarDecl)):
            forget(s.target if isinstance(s, ir.Assign) else s.name)
    for key, lines in counts.items():
        if len(lines) >= 2:
            out.append(Suggestion("cse", lines[0], "tip",
                                  f"'{key}' is computed {len(lines)} times (lines {', '.join(map(str, lines))}).",
                                  f"Store it once: t = {key}; then reuse t."))

    # 3. variables written but never read
    reads, writes = set(), {}
    for s in walk_stmts(func.body):
        for e in _stmt_exprs(s):
            reads |= expr_vars(e)
        if isinstance(s, ir.Assign):
            writes.setdefault(s.target, s.line)
        elif isinstance(s, ir.VarDecl):
            writes.setdefault(s.name, s.line)
    for name in sorted(local_names(func, language)):
        if name in writes and name not in reads and name not in {p.name for p in func.params}:
            out.append(Suggestion("unused", writes[name], "warning",
                                  f"'{name}' is assigned but never read.", f"Delete '{name}' (dead code elimination would remove it anyway)."))

    # 4/5. loops: unknown bounds, heavy operators
    for loop, depth in _loops(func.body):
        c = loop.cond
        bounded = (isinstance(c, ir.BinOp) and c.op in ("<", "<=", ">", ">=")
                   and any(isinstance(x, ir.Literal) for x in (c.left, c.right)))
        if not bounded:
            out.append(Suggestion("loop_bound", loop.line, "info",
                                  "The loop bound is not a constant, so the Digital Twin assumes 10 iterations.",
                                  "If you know the typical trip count, a constant bound makes predictions exact."))
        for inner in walk_stmts(loop.body):
            for e in _stmt_exprs(inner):
                heavy = [n for n in walk_expr(e) if isinstance(n, ir.BinOp) and n.op in ("/", "//", "%")]
                if heavy:
                    out.append(Suggestion("heavy_op_in_loop", inner.line, "warning",
                                          f"'{print_expr(heavy[0])}' runs every iteration and costs {COST_WEIGHTS[heavy[0].op]}x an addition.",
                                          "For a power-of-two divisor and non-negative values a shift or mask is cheaper; "
                                          "otherwise consider hoisting or restructuring."))
                if any(isinstance(n, ir.Call) for n in walk_expr(e)):
                    out.append(Suggestion("unknown_call", inner.line, "info",
                                          "A function call inside a loop: its cost is added to every iteration.",
                                          "Move loop-independent calls out of the loop."))

    # 6. Python without type information
    if language == "python" and func.params:
        out.append(Suggestion("untyped", func.line, "info",
                              "Python parameters carry no type information in the IR, so type-dependent rewrites "
                              "such as x*8 -> x<<3 are not applied to them.",
                              "This is deliberate: the compiler only rewrites what it can prove is an integer."))

    # stable order: severity then line
    order = {"warning": 0, "tip": 1, "info": 2}
    out.sort(key=lambda s: (order[s.severity], s.line))
    return out