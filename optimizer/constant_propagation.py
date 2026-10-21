"""
Constant propagation: replace a variable read by its known constant value.

    a = 4;  b = a * 2;   ->   a = 4;  b = 4 * 2;     (folding then gives 8)

A forward data-flow analysis over structured code. `env` maps each local
variable to the literal it is certain to hold at the current point:

  * straight-line code  : assignments update env
  * if / else           : analyse both arms from a copy of env, then keep only
                          facts that agree afterwards (an arm that always
                          returns doesn't take part in the merge)
  * while               : any variable assigned inside the loop is forgotten
                          BEFORE the loop (its value changes each iteration)

Only provably-local variables are tracked (a C global or Java field could be
changed by any call), and a constant is recorded only if it already has the
variable's declared type -- e.g. `double d = 3;` records 3.0, so a later
`d / 2` stays a float division.
"""

from ..ir import ir_nodes as ir
from ..ir.ir_printer import print_expr
from ..ir.ir_utils import (clone, defined_names, definitely_returns,
                           infer_var_types, local_names)
from .base import Change, OptimizationPass, PassResult


class ConstantPropagation(OptimizationPass):
    name = "constant_propagation"
    description = "Replace variables known to hold a constant with that constant."

    def run(self, func, language) -> PassResult:
        new = clone(func)
        self._lang = language
        self._changes = []
        self._locals = local_names(new, language)
        self._types = infer_var_types(new, language)
        self._block(new.body, {})
        return PassResult(new, self._changes)

    # -- tracking ---------------------------------------------------------------

    def _record(self, env, name, value):
        """Remember `name == value` if that is safe; otherwise forget it."""
        env.pop(name, None)
        if name not in self._locals or not isinstance(value, ir.Literal):
            return
        if self._lang == "python":
            env[name] = value
            return
        declared = self._types.get(name, "unknown")
        if declared == "unknown":
            return
        if value.type == declared:
            env[name] = value
        elif declared == "float" and value.type == "int":
            env[name] = ir.Literal(value=float(value.value), type="float", line=value.line)

    def _subst(self, e, env):
        if isinstance(e, ir.Identifier) and e.name in env:
            lit = clone(env[e.name])
            lit.line = e.line
            self._changes.append(Change(self.name, e.line,
                                        f"replaced {e.name} with constant {print_expr(lit)}"))
            return lit
        if isinstance(e, ir.BinOp):
            e.left, e.right = self._subst(e.left, env), self._subst(e.right, env)
        elif isinstance(e, ir.UnaryOp):
            e.operand = self._subst(e.operand, env)
        elif isinstance(e, ir.Call):
            e.args = [self._subst(a, env) for a in e.args]
        return e

    # -- statements ---------------------------------------------------------------

    def _block(self, block, env):
        for s in block.statements:
            self._stmt(s, env)

    def _stmt(self, s, env):
        if isinstance(s, ir.VarDecl):
            if s.init is not None:
                s.init = self._subst(s.init, env)
                self._record(env, s.name, s.init)
            else:
                env.pop(s.name, None)

        elif isinstance(s, ir.Assign):
            s.value = self._subst(s.value, env)
            self._record(env, s.target, s.value)

        elif isinstance(s, ir.ExprStmt):
            s.expr = self._subst(s.expr, env)

        elif isinstance(s, ir.Return):
            if s.value is not None:
                s.value = self._subst(s.value, env)

        elif isinstance(s, ir.If):
            s.cond = self._subst(s.cond, env)
            env_then, env_else = dict(env), dict(env)
            self._block(s.then_block, env_then)
            if s.else_block is not None:
                self._block(s.else_block, env_else)
            then_ret = definitely_returns(s.then_block)
            else_ret = s.else_block is not None and definitely_returns(s.else_block)
            if then_ret and not else_ret:
                merged = env_else
            elif else_ret and not then_ret:
                merged = env_then
            else:
                merged = {k: v for k, v in env_then.items()
                          if k in env_else and env_else[k].value == v.value
                          and env_else[k].type == v.type}
            env.clear()
            env.update(merged)

        elif isinstance(s, ir.While):
            for name in defined_names(s.body):          # changes every iteration
                env.pop(name, None)
            s.cond = self._subst(s.cond, env)
            self._block(s.body, dict(env))
            # env already excludes everything the loop assigns -> valid after it
