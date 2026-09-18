"""
Pretty-prints a Common IR Program back into readable pseudocode.

This is used for:
  - sanity-checking translators during development (this milestone)
  - later, showing the human "before / after optimization" code comparison
    that Phase 6 (Explainability & Reporting) needs, regardless of which
    source language the program originally came from.
"""

from . import ir_nodes as ir


INDENT = "    "


def print_program(program: "ir.Program") -> str:
    lines = [f"// source_language: {program.source_language}"]
    for func in program.functions:
        lines.append(_print_func(func))
    return "\n\n".join(lines)


def _print_func(func: "ir.FuncDecl") -> str:
    params = ", ".join(f"{p.param_type} {p.name}" for p in func.params)
    header = f"{func.return_type} {func.name}({params}) {{"
    body_lines = _print_block(func.body, depth=1)
    return "\n".join([header] + body_lines + ["}"])


def _print_block(block: "ir.Block", depth: int) -> list:
    lines = []
    for stmt in block.statements:
        lines.extend(_print_stmt(stmt, depth))
    return lines


def _print_stmt(node, depth: int) -> list:
    pad = INDENT * depth
    if isinstance(node, ir.VarDecl):
        init = f" = {_print_expr(node.init)}" if node.init is not None else ""
        return [f"{pad}{node.var_type} {node.name}{init};"]
    if isinstance(node, ir.Assign):
        return [f"{pad}{node.target} = {_print_expr(node.value)};"]
    if isinstance(node, ir.ExprStmt):
        return [f"{pad}{_print_expr(node.expr)};"]
    if isinstance(node, ir.Return):
        val = f" {_print_expr(node.value)}" if node.value is not None else ""
        return [f"{pad}return{val};"]
    if isinstance(node, ir.If):
        out = [f"{pad}if ({_print_expr(node.cond)}) {{"]
        out.extend(_print_block(node.then_block, depth + 1))
        if node.else_block is not None:
            out.append(f"{pad}}} else {{")
            out.extend(_print_block(node.else_block, depth + 1))
        out.append(f"{pad}}}")
        return out
    if isinstance(node, ir.While):
        out = [f"{pad}while ({_print_expr(node.cond)}) {{"]
        out.extend(_print_block(node.body, depth + 1))
        out.append(f"{pad}}}")
        return out
    return [f"{pad}<?unknown statement {type(node).__name__}?>"]


def _print_expr(node) -> str:
    if node is None:
        return ""
    if isinstance(node, ir.Literal):
        if node.type == "string":
            return f'"{node.value}"'
        return str(node.value)
    if isinstance(node, ir.Identifier):
        return node.name
    if isinstance(node, ir.BinOp):
        return f"({_print_expr(node.left)} {node.op} {_print_expr(node.right)})"
    if isinstance(node, ir.UnaryOp):
        return f"({node.op}{_print_expr(node.operand)})"
    if isinstance(node, ir.Call):
        args = ", ".join(_print_expr(a) for a in node.args)
        return f"{node.name}({args})"
    return f"<?unknown expr {type(node).__name__}?>"
