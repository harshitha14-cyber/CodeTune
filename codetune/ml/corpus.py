"""
Training corpus for the ML pass selector ("labeled program samples", report 3.1 Phase 3).

Programs are generated directly as Common IR in all four languages. Each one is
built from a random "profile" (how many constants, dead variables, constant
conditions, multiplications, loops ...), so some programs have lots to
optimise and some have nothing.

LABEL = ground truth from running the real optimizer: pass P is labelled
"useful" (1) if P makes at least one change while the four passes are run to a
fixpoint on that program. The ML model never sees the pass results -- only the
static feature vector -- so it learns to PREDICT usefulness without running
the passes.
"""

import random
from typing import Dict, List, Tuple

from ..ir import ir_nodes as ir
from ..optimizer.registry import PASS_ORDER, make_pass

LANGUAGES = ["python", "c", "cpp", "java"]


def _lit(v, line=1):
    return ir.Literal(value=v, type="int", line=line)


def _id(n, line=1):
    return ir.Identifier(name=n, line=line)


def _bin(op, a, b):
    return ir.BinOp(op=op, left=a, right=b, line=1)


class _Gen:
    def __init__(self, rng: random.Random, lang: str):
        self.r, self.lang = rng, lang
        # profile: probability of each construct (this is what makes programs differ)
        self.p_const = rng.choice([0.0, 0.15, 0.4, 0.7])
        self.p_dead = rng.choice([0.0, 0.1, 0.3, 0.5])
        self.p_pow2 = rng.choice([0.0, 0.1, 0.3, 0.6])
        self.p_loop = rng.choice([0.0, 0.2, 0.5])
        self.p_if = rng.choice([0.0, 0.2, 0.5])
        self.p_constif = rng.choice([0.0, 0.3, 0.8])
        self.p_arith_const = rng.choice([0.0, 0.2, 0.5])
        self.clean = rng.random() < 0.45          # "tidy" programs: every variable ends up used
        if self.clean:
            self.p_dead = 0.0
        self.vars: List[str] = ["n"]
        self.counter = 0
        self.stmts: List = []

    def fresh(self, base="v"):
        self.counter += 1
        return f"{base}{self.counter}"

    def declare(self, name, init):
        if self.lang == "python":
            return ir.Assign(target=name, value=init, line=1)
        return ir.VarDecl(name=name, var_type="int", init=init, line=1)

    def assign(self, name, value):
        return ir.Assign(target=name, value=value, line=1)

    def rand_var(self):
        return self._id(self.r.choice(self.vars))

    def _id(self, n):
        return _id(n)

    def expr(self, depth=2):
        r = self.r
        if depth == 0 or r.random() < 0.3:
            return self.rand_var() if r.random() < 0.65 else _lit(r.choice([0, 1, 2, 3, 5, 7, 10, 100]))
        if r.random() < self.p_arith_const:
            return _bin(r.choice(["+", "-", "*"]), _lit(r.choice([2, 3, 4, 5])), _lit(r.choice([1, 2, 6, 9])))
        if r.random() < self.p_pow2:
            return _bin("*", self.rand_var(), _lit(r.choice([2, 4, 8, 16, 32])))
        op = r.choice(["+", "-", "*", "+", "-", "/", "%"])
        right = self.expr(depth - 1)
        if op in ("/", "%"):
            right = _lit(r.choice([2, 3, 5, 7]))
        return _bin(op, self.expr(depth - 1), right)

    def cond(self):
        r = self.r
        if r.random() < self.p_constif and self.const_vars:
            return _bin(r.choice(["==", "!=", "<", ">"]), _id(r.choice(self.const_vars)), _lit(r.choice([0, 1, 5])))
        return _bin(r.choice(["<", ">", "==", "!="]), self.rand_var(), _lit(r.choice([0, 1, 10])))

    def store(self, depth=2):
        """An assignment. In tidy programs it is read-modify-write (v = v + e), so earlier stores stay live."""
        t = self.r.choice(self.writable)
        value = self.expr(depth)
        if self.clean:
            value = _bin("+", _id(t), value)
        return self.assign(t, value)

    def block(self, depth, n_stmts):
        out, r = [], self.r
        for _ in range(n_stmts):
            x = r.random()
            if x < self.p_loop * 0.5 and depth > 0:
                out.extend(self.loop(depth - 1))
            elif x < self.p_loop * 0.5 + self.p_if * 0.5 and depth > 0:
                els = ir.Block(statements=self.block(depth - 1, 1), line=1) if r.random() < 0.5 else None
                out.append(ir.If(cond=self.cond(), then_block=ir.Block(statements=self.block(depth - 1, 1), line=1),
                                 else_block=els, line=1))
            elif x < 0.75 and self.writable:
                out.append(self.store())
            else:
                out.append(self.store(1) if self.writable else ir.ExprStmt(expr=self.expr(1), line=1))
        return out

    def loop(self, depth):
        k = self.fresh("k")
        body = self.block(depth, self.r.randint(1, 2))
        body.append(self.assign(k, _bin("+", _id(k), _lit(1))))
        return [self.declare(k, _lit(0)),
                ir.While(cond=_bin("<", _id(k), _lit(self.r.randint(1, 4))), body=ir.Block(statements=body, line=1), line=1)]

    def build(self) -> ir.Program:
        r = self.r
        self.const_vars, self.writable = [], []
        for _ in range(r.randint(1, 4)):
            name = self.fresh("c")
            if r.random() < self.p_const:
                self.stmts.append(self.declare(name, _lit(r.choice([0, 1, 2, 3, 8, 10]))))
                self.const_vars.append(name)
            else:
                self.stmts.append(self.declare(name, _id("n") if r.random() < 0.6 else self.expr(1)))
            self.vars.append(name)
            self.writable.append(name)
        # only some variables may be reassigned; constants are rewritten rarely so propagation can fire
        self.writable = [v for v in self.writable if v not in self.const_vars or r.random() < 0.3] or self.writable
        self.stmts.extend(self.block(2, r.randint(2, 6)))
        for _ in range(r.randint(0, 3)):
            if r.random() < self.p_dead:
                self.stmts.append(self.declare(self.fresh("dead"), self.expr()))
        used = list(self.vars) if self.clean else r.sample(self.vars, k=min(len(self.vars), r.randint(1, 3)))
        ret = _id(used[0])
        for u in used[1:]:
            ret = _bin("+", ret, _id(u))
        self.stmts.append(ir.Return(value=ret, line=1))
        func = ir.FuncDecl(name="f", params=[ir.Param(name="n", param_type="var" if self.lang == "python" else "int")],
                           return_type="int", body=ir.Block(statements=self.stmts, line=1), line=1)
        return ir.Program(source_language=self.lang, functions=[func])


def oracle_labels(func, language, max_rounds: int = 10) -> Dict[str, int]:
    """Which passes make >= 1 change when all four run to a fixpoint?"""
    used = {n: 0 for n in PASS_ORDER}
    current = func
    for _ in range(max_rounds):
        progressed = False
        for name in PASS_ORDER:
            res = make_pass(name).run(current, language)
            if res.changed:
                used[name] += len(res.changes)
                current, progressed = res.func, True
        if not progressed:
            break
    return {n: int(c > 0) for n, c in used.items()}


def generate_corpus(n: int, seed: int = 0) -> List[Tuple["ir.FuncDecl", str, Dict[str, int]]]:
    """[(func, language, {pass: 0/1})] -- languages are cycled so all four are equally represented."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        lang = LANGUAGES[i % len(LANGUAGES)]
        prog = _Gen(random.Random(rng.randrange(10 ** 9)), lang).build()
        func = prog.functions[0]
        out.append((func, lang, oracle_labels(func, lang)))
    return out