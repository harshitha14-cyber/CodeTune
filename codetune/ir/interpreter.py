"""
A small interpreter for the Common IR.

Why it exists in Milestone 2: it is the test oracle -- run the ORIGINAL and the
OPTIMIZED program on the same inputs and compare results. Milestone 3's
semantic validation (differential testing) is built directly on top of it, and
the Digital Twin (Milestone 4) reads its operation counters as a cost model.

Uses ir/semantics.py, so C/C++/Java integers wrap at 32 bits and `/`, `%`
follow each language's rules.
"""

from collections import Counter

from . import ir_nodes as ir
from . import semantics as sem
from .ir_utils import infer_var_types


class InterpreterError(Exception):
    pass


class StepLimitExceeded(InterpreterError):
    pass


class _Return(Exception):
    def __init__(self, value):
        self.value = value


_UNINIT = object()


class Interpreter:
    def __init__(self, program: "ir.Program", step_limit: int = 200_000):
        self.program = program
        self.lang = program.source_language
        self.funcs = {f.name: f for f in program.functions}
        self._type_cache = {f.name: infer_var_types(f, self.lang) for f in program.functions}
        self._types = {}
        self.step_limit = step_limit
        self.steps = 0
        self.stats = Counter()          # cost model: ops executed, by kind

    def call(self, name, args):
        if name not in self.funcs:
            raise InterpreterError(f"call to unknown function '{name}'")
        func = self.funcs[name]
        if len(args) != len(func.params):
            raise InterpreterError(f"{name} expects {len(func.params)} args, got {len(args)}")
        self.stats["call"] += 1
        saved_types, self._types = self._types, self._type_cache[name]
        env = {p.name: self._coerce(p.name, a) for p, a in zip(func.params, args)}
        try:
            self._block(func.body, env)
        except _Return as r:
            return r.value
        finally:
            self._types = saved_types
        return None

    def _coerce(self, name, value):
        """Apply the declared type of a variable on store (typed languages):
        `double d = 3` holds 3.0; C `int i = 3.7` holds 3."""
        t = self._types.get(name)
        if self.lang == "python" or t is None:
            return value
        if t == "float" and sem.is_int(value):
            return float(value)
        if t == "int" and isinstance(value, float) and self.lang in ("c", "cpp"):
            return int(value)
        return value

    # -- statements ---------------------------------------------------------------

    def _tick(self):
        self.steps += 1
        if self.steps > self.step_limit:
            raise StepLimitExceeded("step limit exceeded (possible infinite loop)")

    def _block(self, block, env):
        for s in block.statements:
            self._stmt(s, env)

    def _stmt(self, s, env):
        self._tick()
        if isinstance(s, ir.VarDecl):
            env[s.name] = self._coerce(s.name, self._expr(s.init, env)) if s.init is not None else _UNINIT
            self.stats["assign"] += s.init is not None
        elif isinstance(s, ir.Assign):
            env[s.target] = self._coerce(s.target, self._expr(s.value, env))
            self.stats["assign"] += 1
        elif isinstance(s, ir.ExprStmt):
            self._expr(s.expr, env)
        elif isinstance(s, ir.Return):
            raise _Return(self._expr(s.value, env) if s.value is not None else None)
        elif isinstance(s, ir.If):
            self.stats["branch"] += 1
            if self._truth(self._expr(s.cond, env)):
                self._block(s.then_block, env)
            elif s.else_block is not None:
                self._block(s.else_block, env)
        elif isinstance(s, ir.While):
            while True:
                self._tick()
                self.stats["branch"] += 1
                if not self._truth(self._expr(s.cond, env)):
                    break
                self.stats["loop_iter"] += 1
                self._block(s.body, env)
        else:
            raise InterpreterError(f"cannot execute {type(s).__name__}")

    # -- expressions -----------------------------------------------------------------

    def _truth(self, v):
        return bool(v)

    def _expr(self, e, env):
        if isinstance(e, ir.Literal):
            return e.value
        if isinstance(e, ir.Identifier):
            if e.name not in env:
                raise InterpreterError(f"read of unknown variable '{e.name}' (line {e.line})")
            if env[e.name] is _UNINIT:
                raise InterpreterError(f"read of uninitialised variable '{e.name}' (line {e.line})")
            return env[e.name]
        if isinstance(e, ir.UnaryOp):
            self.stats["op"] += 1
            return sem.unop(e.op, self._expr(e.operand, env), self.lang, wrap=True)
        if isinstance(e, ir.BinOp):
            if e.op in sem.LOGICAL:                                   # short-circuit
                a = self._expr(e.left, env)
                self.stats["op"] += 1
                if self.lang == "python" and not isinstance(a, bool):
                    return (a and self._expr(e.right, env)) if e.op == "&&" else (a or self._expr(e.right, env))
                if e.op == "&&":
                    return bool(a) and bool(self._expr(e.right, env))
                return bool(a) or bool(self._expr(e.right, env))
            a, b = self._expr(e.left, env), self._expr(e.right, env)
            self.stats["op"] += 1
            self.stats["shift_or_add" if e.op in ("<<", ">>") else "op_" + e.op] += 1
            try:
                return sem.binop(e.op, a, b, self.lang, wrap=True)
            except sem.Unfoldable as ex:
                raise InterpreterError(f"cannot evaluate {e.op!r} at line {e.line}: {ex}")
            except ZeroDivisionError:
                raise InterpreterError(f"division by zero at line {e.line}")
        if isinstance(e, ir.Call):
            return self.call(e.name, [self._expr(a, env) for a in e.args])
        raise InterpreterError(f"cannot evaluate {type(e).__name__}")


def run_function(program, name, args, **kw):
    """Convenience: returns (value, stats) or raises InterpreterError."""
    interp = Interpreter(program, **kw)
    return interp.call(name, list(args)), interp.stats
