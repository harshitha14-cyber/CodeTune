"""
Optimization-pass framework.

Every pass:
  * takes a FuncDecl and the source language,
  * returns a NEW FuncDecl (the input is never mutated),
  * returns a log of Change records -- one per transformation, with the source
    line and a human-readable before -> after. Those logs are the raw material
    for Phase 6 (explainable reports) and, later, the Copilot's answers to
    "what did you change and why?".
"""

from dataclasses import dataclass, field
from typing import List

from ..ir import ir_nodes as ir


@dataclass
class Change:
    pass_name: str
    line: int
    description: str

    def __str__(self):
        return f"[{self.pass_name}] line {self.line}: {self.description}"


@dataclass
class PassResult:
    func: "ir.FuncDecl"
    changes: List[Change] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


class OptimizationPass:
    name = "base"
    description = ""

    def run(self, func: "ir.FuncDecl", language: str) -> PassResult:
        raise NotImplementedError


def map_exprs_in_block(block: "ir.Block", fn):
    """Apply `fn(expr) -> expr` to every top-level expression slot in `block`
    (recursing into if/while bodies). `fn` is responsible for recursing
    inside the expression itself. Mutates `block` in place -- only call it on
    a clone."""
    for s in block.statements:
        if isinstance(s, ir.VarDecl) and s.init is not None:
            s.init = fn(s.init)
        elif isinstance(s, ir.Assign):
            s.value = fn(s.value)
        elif isinstance(s, ir.ExprStmt):
            s.expr = fn(s.expr)
        elif isinstance(s, ir.Return) and s.value is not None:
            s.value = fn(s.value)
        elif isinstance(s, ir.If):
            s.cond = fn(s.cond)
            map_exprs_in_block(s.then_block, fn)
            if s.else_block is not None:
                map_exprs_in_block(s.else_block, fn)
        elif isinstance(s, ir.While):
            s.cond = fn(s.cond)
            map_exprs_in_block(s.body, fn)
