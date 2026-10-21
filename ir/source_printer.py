"""
Common IR -> real source code in the ORIGINAL language (Python, C, C++ or Java).

The optimizer works on IR, but a person wants their optimized FUNCTION back in the
language they wrote it in. Output uses minimal parentheses driven by each
language's operator precedence, so `(a + b) * c` stays parenthesised and
`a + (b * c)` does not. Correctness is checked in the test-suite by a round trip:
print -> parse -> translate again must give the identical IR.

Notes:
  * Java methods are printed inside a small wrapper class.
  * Names introduced by the compiler (`_hoisted1`, `i_1`, `_stop_1`) are ordinary
    identifiers in the output.
  * Python for-range loops come back as the equivalent while loops.
"""

from . import ir_nodes as ir

INDENT = "    "

_C_PREC = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6, "<": 7, ">": 7, "<=": 7, ">=": 7,
           "<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}
_PY_PREC = {"||": 1, "&&": 2, "|": 5, "^": 6, "&": 7, "==": 4, "!=": 4, "<": 4, ">": 4, "<=": 4, ">=": 4,
            "<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "//": 10, "%": 10, "**": 12}
_PY_NAMES = {"&&": "and", "||": "or"}
_UNARY_PREC = 11


class _Printer:
    def __init__(self, language: str):
        self.lang = language
        self.py = language == "python"
        self.prec = _PY_PREC if self.py else _C_PREC

    # -- expressions ---------------------------------------------------------

    def literal(self, e: ir.Literal) -> str:
        v = e.value
        if isinstance(v, bool):
            return ("True" if v else "False") if self.py else ("true" if v else "false")
        if e.type == "string":
            return '"' + str(v) + '"'
        if isinstance(v, float):
            r = repr(v)
            return r if any(c in r for c in ".en") else r + ".0"
        return str(v)

    def expr(self, e, min_prec: int = 0) -> str:
        text, prec = self._expr(e)
        return f"({text})" if prec < min_prec else text

    def _expr(self, e):
        if isinstance(e, ir.Literal):
            text = self.literal(e)
            neg = text.startswith("-")
            return text, (_UNARY_PREC if neg else 99)
        if isinstance(e, ir.Identifier):
            return e.name, 99
        if isinstance(e, ir.Call):
            return f"{e.name}({', '.join(self.expr(a) for a in e.args)})", 99
        if isinstance(e, ir.UnaryOp):
            if e.op == "!" and self.py:
                return "not " + self.expr(e.operand, 3), 3
            inner = self.expr(e.operand, _UNARY_PREC)
            if inner[:1] in ("-", "+") and e.op in ("-", "+"):
                inner = f"({inner})"                       # never print `--x`
            return f"{e.op}{inner}", _UNARY_PREC
        if isinstance(e, ir.BinOp):
            p = self.prec.get(e.op, 1)
            if self.py and e.op == "**":
                left, right = self.expr(e.left, p + 1), self.expr(e.right, p)
            elif self.py and e.op in ("==", "!=", "<", ">", "<=", ">="):
                left, right = self.expr(e.left, p + 1), self.expr(e.right, p + 1)   # no implicit chaining
            else:
                left, right = self.expr(e.left, p), self.expr(e.right, p + 1)
            op = _PY_NAMES.get(e.op, e.op) if self.py else e.op
            return f"{left} {op} {right}", p
        return "?", 99

    # -- statements ------------------------------------------------------------

    def block(self, block: ir.Block, depth: int):
        lines = []
        for s in block.statements:
            lines.extend(self.stmt(s, depth))
        if not lines and self.py:
            lines.append(INDENT * depth + "pass")
        return lines

    def stmt(self, s, depth: int):
        pad = INDENT * depth
        end = "" if self.py else ";"
        if isinstance(s, ir.VarDecl):
            if self.py:
                return [f"{pad}{s.name} = {self.expr(s.init)}"] if s.init is not None else [f"{pad}# {s.var_type} {s.name}"]
            init = f" = {self.expr(s.init)}" if s.init is not None else ""
            return [f"{pad}{s.var_type} {s.name}{init};"]
        if isinstance(s, ir.Assign):
            return [f"{pad}{s.target} = {self.expr(s.value)}{end}"]
        if isinstance(s, ir.ExprStmt):
            return [f"{pad}{self.expr(s.expr)}{end}"]
        if isinstance(s, ir.Return):
            return [f"{pad}return{(' ' + self.expr(s.value)) if s.value is not None else ''}{end}"]
        if isinstance(s, ir.If):
            return self.if_stmt(s, depth)
        if isinstance(s, ir.While):
            cond = self.expr(s.cond)
            if self.py:
                return [f"{pad}while {cond}:"] + self.block(s.body, depth + 1)
            return [f"{pad}while ({cond}) {{"] + self.block(s.body, depth + 1) + [f"{pad}}}"]
        return [f"{pad}# <unsupported statement {type(s).__name__}>"]

    def if_stmt(self, s: ir.If, depth: int):
        pad = INDENT * depth
        cond = self.expr(s.cond)
        if self.py:
            out = [f"{pad}if {cond}:"] + self.block(s.then_block, depth + 1)
            if s.else_block is not None:
                out += [f"{pad}else:"] + self.block(s.else_block, depth + 1)
            return out
        out = [f"{pad}if ({cond}) {{"] + self.block(s.then_block, depth + 1)
        if s.else_block is not None:
            out += [f"{pad}}} else {{"] + self.block(s.else_block, depth + 1)
        return out + [f"{pad}}}"]

    # -- functions ---------------------------------------------------------------

    def function(self, f: ir.FuncDecl, depth: int = 0):
        pad = INDENT * depth
        if self.py:
            params = ", ".join(p.name if p.param_type == "var" else f"{p.name}: {p.param_type}" for p in f.params)
            ret = "" if f.return_type in ("var", "void") else f" -> {f.return_type}"
            return [f"{pad}def {f.name}({params}){ret}:"] + self.block(f.body, depth + 1)
        params = ", ".join(f"{p.param_type} {p.name}" for p in f.params)
        return [f"{pad}{f.return_type} {f.name}({params}) {{"] + self.block(f.body, depth + 1) + [f"{pad}}}"]


def function_to_source(func: ir.FuncDecl, language: str, class_name: str = "Optimized") -> str:
    p = _Printer(language)
    if language == "java":
        return "\n".join([f"class {class_name} {{"] + p.function(func, 1) + ["}"]) + "\n"
    return "\n".join(p.function(func)) + "\n"


def program_to_source(program: ir.Program, class_name: str = "Optimized") -> str:
    p = _Printer(program.source_language)
    if program.source_language == "java":
        body = []
        for f in program.functions:
            body += p.function(f, 1) + [""]
        return "\n".join([f"class {class_name} {{"] + body[:-1] + ["}"]) + "\n"
    out = []
    for f in program.functions:
        out += p.function(f) + [""]
    return "\n".join(out)