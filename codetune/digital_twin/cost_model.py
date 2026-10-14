"""
Performance model of the Digital Twin (report 3.2: "Performance Predictor").

Three kinds of numbers are produced for any version of a function:

  PREDICTED cost   a STATIC estimate -- nothing is executed. Straight-line code
                   is exact; constant-bound loops get exact trip counts;
                   conditions that depend on unknown inputs are weighted
                   50/50; unknown loop bounds assume DEFAULT_LOOP_TRIPS.
  MEASURED cost    the same weights applied to what the IR interpreter really
                   executed (average over the generated test inputs). This is
                   the "actual performance" the prediction is judged against.
  CODE SIZE /      node count of the IR, and a static estimate of the stack
  MEMORY           bytes needed by local variables.

One cost unit ~ one CPU cycle in this model (an assumption, not a measurement
of real hardware); `estimated_time_ns` converts at CLOCK_GHZ.
"""

from typing import Dict, Optional

from ..ir import ir_nodes as ir
from ..ir import semantics as sem
from ..ir.ir_utils import defined_names, infer_var_types, walk_expr, walk_stmts

COST_WEIGHTS: Dict[str, int] = {
    "+": 1, "-": 1, "*": 3, "/": 10, "//": 10, "%": 10, "**": 8,
    "<<": 1, ">>": 1, "&": 1, "|": 1, "^": 1,
    "<": 1, ">": 1, "<=": 1, ">=": 1, "==": 1, "!=": 1, "&&": 1, "||": 1,
}
UNARY_COST = 1
ASSIGN_COST = 1
BRANCH_COST = 1
CALL_COST = 5
UNKNOWN_CALL_COST = 20
DEFAULT_LOOP_TRIPS = 10
CLOCK_GHZ = 3.0


# ---------------------------------------------------------------------------
# MEASURED: weight what the interpreter counted
# ---------------------------------------------------------------------------

def weighted_dynamic_cost(stats) -> float:
    total, counted = 0.0, 0
    for key, n in stats.items():
        if key.startswith("op_"):
            total += COST_WEIGHTS.get(key[3:], 1) * n
            counted += n
    shifts = stats.get("shift_or_add", 0)
    total += COST_WEIGHTS["<<"] * shifts
    counted += shifts
    total += UNARY_COST * max(0, stats.get("op", 0) - counted)        # logical / unary operators
    total += ASSIGN_COST * stats.get("assign", 0) + BRANCH_COST * stats.get("branch", 0)
    total += CALL_COST * stats.get("call", 0)
    return total


# ---------------------------------------------------------------------------
# PREDICTED: static estimate
# ---------------------------------------------------------------------------

class _Unknown(Exception):
    pass


class StaticCostEstimator:
    def __init__(self, program: "ir.Program"):
        self.program = program
        self.lang = program.source_language
        self.funcs = {f.name: f for f in program.functions}
        self._stack = []

    # -- public ----------------------------------------------------------------

    def function_cost(self, func: "ir.FuncDecl") -> float:
        """Expected cost of one call: entry call + body."""
        cost, _ = self._block(func.body.statements, {})
        return CALL_COST + cost

    # -- constant evaluation (symbolic-execution-lite) -------------------------------

    def _eval(self, e, env):
        if isinstance(e, ir.Literal):
            return e.value
        if isinstance(e, ir.Identifier):
            if e.name in env:
                return env[e.name]
            raise _Unknown()
        try:
            if isinstance(e, ir.UnaryOp):
                return sem.unop(e.op, self._eval(e.operand, env), self.lang, wrap=True)
            if isinstance(e, ir.BinOp):
                return sem.binop(e.op, self._eval(e.left, env), self._eval(e.right, env), self.lang, wrap=True)
        except (sem.Unfoldable, ZeroDivisionError, TypeError):
            raise _Unknown()
        raise _Unknown()

    # -- expression cost ----------------------------------------------------------------

    def _expr(self, e) -> float:
        if isinstance(e, (ir.Literal, ir.Identifier)) or e is None:
            return 0.0
        if isinstance(e, ir.UnaryOp):
            return UNARY_COST + self._expr(e.operand)
        if isinstance(e, ir.BinOp):
            return COST_WEIGHTS.get(e.op, 1) + self._expr(e.left) + self._expr(e.right)
        if isinstance(e, ir.Call):
            args = sum(self._expr(a) for a in e.args)
            callee = self.funcs.get(e.name)
            if callee is None or e.name in self._stack:
                return CALL_COST + UNKNOWN_CALL_COST + args
            self._stack.append(e.name)
            try:
                body, _ = self._block(callee.body.statements, {})
            finally:
                self._stack.pop()
            return CALL_COST + args + body
        return 0.0

    # -- statements -------------------------------------------------------------------------

    def _block(self, stmts, env):
        """Returns (expected cost, probability of falling off the end)."""
        cost, p = 0.0, 1.0
        for s in stmts:
            c, pf = self._stmt(s, env)
            cost += p * c
            p *= pf
        return cost, p

    def _assign_env(self, env, name, value_expr):
        try:
            env[name] = self._eval(value_expr, env)
        except _Unknown:
            env.pop(name, None)

    def _stmt(self, s, env):
        if isinstance(s, ir.VarDecl):
            if s.init is None:
                env.pop(s.name, None)
                return 0.0, 1.0
            c = self._expr(s.init) + ASSIGN_COST
            self._assign_env(env, s.name, s.init)
            return c, 1.0
        if isinstance(s, ir.Assign):
            c = self._expr(s.value) + ASSIGN_COST
            self._assign_env(env, s.target, s.value)
            return c, 1.0
        if isinstance(s, ir.ExprStmt):
            return self._expr(s.expr), 1.0
        if isinstance(s, ir.Return):
            return self._expr(s.value), 0.0
        if isinstance(s, ir.If):
            return self._if(s, env)
        if isinstance(s, ir.While):
            return self._while(s, env)
        return 0.0, 1.0

    def _if(self, s, env):
        head = BRANCH_COST + self._expr(s.cond)
        try:
            truth = bool(self._eval(s.cond, env))
            chosen = s.then_block if truth else s.else_block
            if chosen is None:
                return head, 1.0
            c, pf = self._block(chosen.statements, env)       # env flows through the taken branch
            return head + c, pf
        except _Unknown:
            pass
        env_t, env_e = dict(env), dict(env)
        ct, pt = self._block(s.then_block.statements, env_t)
        if s.else_block is not None:
            ce, pe = self._block(s.else_block.statements, env_e)
        else:
            ce, pe = 0.0, 1.0
        env.clear()
        env.update({k: v for k, v in env_t.items() if k in env_e and env_e[k] == v and type(env_e[k]) is type(v)})
        return head + 0.5 * ct + 0.5 * ce, 0.5 * pt + 0.5 * pe

    # -- loops ---------------------------------------------------------------------------------

    def _while(self, s, env):
        before = dict(env)
        assigned = defined_names(s.body)
        for n in assigned:
            env.pop(n, None)
        trips = self._trip_count(s, before, env, assigned)
        head = BRANCH_COST + self._expr(s.cond)
        body_cost, _ = self._block(s.body.statements, dict(env))
        return trips * (head + body_cost) + head, 1.0

    def _trip_count(self, s, before, invariant_env, assigned) -> float:
        cond = s.cond
        if isinstance(cond, ir.BinOp) and cond.op in ("<", "<=", ">", ">="):
            flip = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}
            left, right, op = cond.left, cond.right, cond.op
            if isinstance(right, ir.Identifier) and right.name in assigned and not isinstance(left, ir.Identifier):
                left, right, op = right, left, flip[op]
            if isinstance(left, ir.Identifier) and left.name in assigned and left.name in before:
                try:
                    bound = self._eval(right, invariant_env)
                    init = before[left.name]
                except _Unknown:
                    return DEFAULT_LOOP_TRIPS
                step = self._step(s.body, left.name)
                if step is not None and sem.is_int(init) and sem.is_int(bound):
                    return self._count(op, init, bound, step)
        return DEFAULT_LOOP_TRIPS

    @staticmethod
    def _step(body, var) -> Optional[int]:
        """The constant added to `var` once per iteration, if the body has exactly
        one unconditional `var = var +/- c` and no other definition of it."""
        defs = [x for x in walk_stmts(body) if isinstance(x, (ir.Assign, ir.VarDecl))
                and (x.target if isinstance(x, ir.Assign) else x.name) == var]
        if len(defs) != 1 or defs[0] not in body.statements or not isinstance(defs[0], ir.Assign):
            return None
        v = defs[0].value
        if isinstance(v, ir.BinOp) and v.op in ("+", "-"):
            if isinstance(v.left, ir.Identifier) and v.left.name == var and isinstance(v.right, ir.Literal) \
                    and sem.is_int(v.right.value):
                return v.right.value if v.op == "+" else -v.right.value
            if v.op == "+" and isinstance(v.right, ir.Identifier) and v.right.name == var \
                    and isinstance(v.left, ir.Literal) and sem.is_int(v.left.value):
                return v.left.value
        return None

    @staticmethod
    def _count(op, init, bound, step) -> float:
        if step == 0:
            return DEFAULT_LOOP_TRIPS
        # closed forms, exact for integer steps
        if op in ("<", "<=") and step > 0:
            lim = bound if op == "<=" else bound - 1
            return max(0, (lim - init) // step + 1) if lim >= init else 0
        if op in (">", ">=") and step < 0:
            lim = bound if op == ">=" else bound + 1
            return max(0, (init - lim) // (-step) + 1) if init >= lim else 0
        return DEFAULT_LOOP_TRIPS            # loop that never terminates or never runs: don't guess


# ---------------------------------------------------------------------------
# Size / memory
# ---------------------------------------------------------------------------

def code_size(func) -> int:
    """Number of IR nodes (statements + expression nodes): a proxy for instruction count."""
    n = 0
    for s in walk_stmts(func.body):
        n += 1
        for e in _stmt_exprs(s):
            n += sum(1 for _ in walk_expr(e))
    return n


def _stmt_exprs(s):
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


def estimated_stack_bytes(func, language) -> int:
    """Stack bytes for locals that are actually used: 4 per int-like variable,
    8 per double/string/unknown-wide one. (Estimate -- no real ABI is modelled.)"""
    used = {p.name for p in func.params}
    for s in walk_stmts(func.body):
        if isinstance(s, ir.VarDecl) and s.init is not None:
            used.add(s.name)
        if isinstance(s, ir.Assign):
            used.add(s.target)
        for e in _stmt_exprs(s):
            used |= {n.name for n in walk_expr(e) if isinstance(n, ir.Identifier)}
    types = infer_var_types(func, language)
    return sum(8 if types.get(n) in ("float", "string") else 4 for n in used)


def predicted_cost(func, program, language=None) -> float:
    """Static estimate for `func` inside `program` (callees are looked up there)."""
    return StaticCostEstimator(program).function_cost(func)


def estimated_time_ns(cost_units: float) -> float:
    return cost_units / CLOCK_GHZ