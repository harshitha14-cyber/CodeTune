"""
Dead-code elimination (DCE).

Three independent clean-ups:

  1. Constant branches   `if (0) {A} else {B}` -> B ;  `while (0) {..}` -> removed
  2. Unreachable code    statements after a `return`
  3. Dead stores         assignments whose value is never read afterwards,
                         found with a backward LIVENESS analysis
                         (if/else merge live sets; loops iterate to a fixpoint)

Safety rules:
  * A dead store whose right-hand side is impure (a call, a possible
    divide-by-zero) is not deleted -- only the useless assignment is dropped,
    the expression is kept as a statement so its effects still happen.
  * Only provably-local variables are removed (see ir_utils.local_names): a
    store to a C global / Java field is a visible side effect.
  * Loops are never deleted just for having an empty body (termination).
  * A branch is inlined only if it declares no variables, so inlining can't
    cause a name clash in typed languages.
"""

from ..ir import ir_nodes as ir
from ..ir.ir_printer import print_expr
from ..ir.ir_utils import clone, expr_vars, is_pure, local_names, walk_stmts
from .base import Change, OptimizationPass, PassResult


def _const_truth(e):
    """Truth value of a numeric/bool literal condition, else None."""
    if isinstance(e, ir.Literal) and e.type in ("bool", "int", "float"):
        return bool(e.value)
    return None


class DeadCodeElimination(OptimizationPass):
    name = "dead_code_elimination"
    description = "Remove unreachable code, constant branches and dead stores."

    def run(self, func, language) -> PassResult:
        new = clone(func)
        self._changes = []
        self._locals = local_names(new, language)

        new.body.statements = self._simplify(new.body.statements)           # 1 + 2
        stmts, _ = self._live_block(new.body.statements, set())             # 3
        new.body.statements = stmts
        self._drop_unused_decls(new)
        return PassResult(new, self._changes)

    def _log(self, line, text):
        self._changes.append(Change(self.name, line, text))

    # -- 1 + 2: structural clean-up -------------------------------------------------

    def _simplify(self, stmts):
        out = []
        for i, s in enumerate(stmts):
            if isinstance(s, ir.If):
                s.then_block.statements = self._simplify(s.then_block.statements)
                if s.else_block is not None:
                    s.else_block.statements = self._simplify(s.else_block.statements)
                truth = _const_truth(s.cond)
                if truth is not None:
                    chosen = s.then_block if truth else s.else_block
                    chosen_stmts = chosen.statements if chosen is not None else []
                    if not any(isinstance(x, ir.VarDecl) for x in chosen_stmts):
                        self._log(s.line, f"condition {print_expr(s.cond)} is constant -> "
                                          f"kept only the {'then' if truth else 'else'} branch")
                        out.extend(chosen_stmts)
                        if any(isinstance(x, ir.Return) for x in chosen_stmts):
                            self._log_unreachable(stmts[i + 1:])
                            break
                        continue
            elif isinstance(s, ir.While):
                s.body.statements = self._simplify(s.body.statements)
                if _const_truth(s.cond) is False:
                    self._log(s.line, f"loop condition {print_expr(s.cond)} is always false -> loop removed")
                    continue
            out.append(s)
            if isinstance(s, ir.Return):
                self._log_unreachable(stmts[i + 1:])
                break
        return out

    def _log_unreachable(self, dead_stmts):
        for dead in dead_stmts:
            self._log(dead.line, "unreachable code after return removed")

    # -- 3: liveness-based dead stores ---------------------------------------------------

    def _live_block(self, stmts, live_out):
        live, out = set(live_out), []
        for s in reversed(stmts):
            produced, live = self._live_stmt(s, live)
            out[:0] = produced
        return out, live

    def _removable(self, name):
        return name in self._locals and name.isidentifier()

    def _live_stmt(self, s, live):
        """Returns ([replacement statements], live_before)."""
        if isinstance(s, (ir.VarDecl, ir.Assign)):
            name = s.name if isinstance(s, ir.VarDecl) else s.target
            value = s.init if isinstance(s, ir.VarDecl) else s.value
            if value is None:                                  # `int z;`
                return [s], live
            if self._removable(name) and name not in live:
                if is_pure(value):
                    self._log(s.line, f"dead store to '{name}' removed (value never used)")
                    replacement = [ir.VarDecl(name=name, var_type=s.var_type, init=None, line=s.line)] \
                        if isinstance(s, ir.VarDecl) else []
                    return replacement, live
                self._log(s.line, f"store to '{name}' is dead; kept the expression for its side effects")
                keep = [ir.ExprStmt(expr=value, line=s.line)]
                if isinstance(s, ir.VarDecl):
                    keep.insert(0, ir.VarDecl(name=name, var_type=s.var_type, init=None, line=s.line))
                return keep, live | expr_vars(value)
            return [s], (live - {name}) | expr_vars(value)

        if isinstance(s, ir.ExprStmt):
            if is_pure(s.expr):
                self._log(s.line, f"statement '{print_expr(s.expr)}' has no effect -> removed")
                return [], live
            return [s], live | expr_vars(s.expr)

        if isinstance(s, ir.Return):
            return [s], (expr_vars(s.value) if s.value is not None else set())

        if isinstance(s, ir.If):
            then_stmts, live_then = self._live_block(s.then_block.statements, live)
            if s.else_block is not None:
                else_stmts, live_else = self._live_block(s.else_block.statements, live)
            else:
                else_stmts, live_else = None, set(live)
            if not then_stmts and not else_stmts and is_pure(s.cond):
                self._log(s.line, "if-statement with empty branches removed")
                return [], live
            s.then_block.statements = then_stmts
            if else_stmts is not None:
                if else_stmts:
                    s.else_block.statements = else_stmts
                else:
                    s.else_block = None
            return [s], live_then | live_else | expr_vars(s.cond)

        if isinstance(s, ir.While):
            head = set(live) | expr_vars(s.cond)
            while True:                                         # fixpoint, no logging
                saved = self._changes
                self._changes = []
                _, body_live = self._live_block(clone(s.body).statements, head)
                self._changes = saved
                if body_live <= head:
                    break
                head |= body_live
            s.body.statements, _ = self._live_block(s.body.statements, head)
            return [s], head

        return [s], live

    # -- cleanup: declarations nobody refers to any more -----------------------------------

    def _drop_unused_decls(self, func):
        referenced = set()
        for s in walk_stmts(func.body):
            if isinstance(s, ir.VarDecl) and s.init is not None:
                referenced |= expr_vars(s.init)
            elif isinstance(s, ir.Assign):
                referenced.add(s.target)
                referenced |= expr_vars(s.value)
            elif isinstance(s, ir.ExprStmt):
                referenced |= expr_vars(s.expr)
            elif isinstance(s, ir.Return) and s.value is not None:
                referenced |= expr_vars(s.value)
            elif isinstance(s, (ir.If, ir.While)):
                referenced |= expr_vars(s.cond)
        # a declaration WITH an initializer is kept (liveness already judged it)

        def prune(block):
            kept = []
            for s in block.statements:
                if isinstance(s, ir.VarDecl) and s.init is None and s.name not in referenced:
                    self._log(s.line, f"unused declaration of '{s.name}' removed")
                    continue
                if isinstance(s, ir.If):
                    prune(s.then_block)
                    if s.else_block is not None:
                        prune(s.else_block)
                elif isinstance(s, ir.While):
                    prune(s.body)
                kept.append(s)
            block.statements = kept
        prune(func.body)
