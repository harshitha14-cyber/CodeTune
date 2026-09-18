"""
CodeTune Common IR
==================
A small, language-agnostic intermediate representation (IR).

Every supported source language (Python, C, C++, Java) is translated into
this SAME set of node types. Every later CodeTune module -- feature
extraction, optimization passes, the ML pass-selector, the Digital Twin and
the Copilot -- only ever has to understand THIS IR, not four different
grammars. That is what makes multi-language support tractable.

Only a deliberately small subset of each language is supported for now:
  - functions with typed/untyped parameters
  - variable declarations and assignment
  - arithmetic / comparison / logical binary expressions
  - unary expressions (-x, !x)
  - literals (int, float, bool, string) and identifiers
  - if / else
  - while loops
  - return statements
  - function calls used as statements or inside expressions

This is intentionally the same subset across languages so that a program's
"shape" is comparable no matter which language it was written in.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Union


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """Base class for every IR node. `line` is 1-indexed source line number,
    used later for Copilot explanations and error/optimization reporting."""
    line: int = 0


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

@dataclass
class Literal(Node):
    value: Union[int, float, bool, str] = None
    type: str = "int"          # "int" | "float" | "bool" | "string"


@dataclass
class Identifier(Node):
    name: str = ""


@dataclass
class BinOp(Node):
    op: str = ""               # "+", "-", "*", "/", "<", ">", "==", "&&", ...
    left: Node = None
    right: Node = None


@dataclass
class UnaryOp(Node):
    op: str = ""               # "-", "!"
    operand: Node = None


@dataclass
class Call(Node):
    name: str = ""
    args: List[Node] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

@dataclass
class VarDecl(Node):
    name: str = ""
    var_type: str = "var"      # best-effort; "var" if the language is untyped
    init: Optional[Node] = None


@dataclass
class Assign(Node):
    target: str = ""
    value: Node = None


@dataclass
class ExprStmt(Node):
    expr: Node = None


@dataclass
class Return(Node):
    value: Optional[Node] = None


@dataclass
class Block(Node):
    statements: List[Node] = field(default_factory=list)


@dataclass
class If(Node):
    cond: Node = None
    then_block: Block = None
    else_block: Optional[Block] = None


@dataclass
class While(Node):
    cond: Node = None
    body: Block = None


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------

@dataclass
class Param(Node):
    name: str = ""
    param_type: str = "var"


@dataclass
class FuncDecl(Node):
    name: str = ""
    params: List[Param] = field(default_factory=list)
    return_type: str = "var"
    body: Block = None


@dataclass
class Program(Node):
    source_language: str = ""
    functions: List[FuncDecl] = field(default_factory=list)
