from .base import COMPOUND_ASSIGN, PYTHON_BINARY_OPS, TranslatorBase, parse_int_literal
from .. import ir_nodes as ir
from ..ir_utils import has_call, defined_names

COMPARE_OPS = {"<", ">", "<=", ">=", "==", "!="}


class PythonTranslator(TranslatorBase):
    source_language = "python"

    def translate_program(self, root_node) -> ir.Program:
        program = ir.Program(source_language=self.source_language, functions=[])
        for child in root_node.children:
            if child.type == "function_definition":
                program.functions.append(self._translate_function(child))
        return program

    # -- functions -----------------------------------------------------

    def _translate_function(self, node) -> ir.FuncDecl:
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        ret = node.child_by_field_name("return_type")

        params = []
        for c in params_node.children:
            if c.type == "identifier":
                params.append(ir.Param(name=self.text(c), param_type="var", line=self.line(c)))
            elif c.type == "typed_parameter":
                ident = next(x for x in c.children if x.type == "identifier")
                ann = c.child_by_field_name("type")
                params.append(ir.Param(name=self.text(ident), param_type=self.text(ann) if ann else "var",
                                       line=self.line(c)))
            elif c.type in ("default_parameter", "typed_default_parameter"):
                self.unsupported(c, context="parameter (default values are not supported yet)")
            elif c.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                self.unsupported(c, context="parameter (*args / **kwargs)")

        self._reset_function_state()
        self._reserved = self.collect_identifiers(node)
        self._fn_node = node
        return ir.FuncDecl(
            name=self.text(name_node), params=params,
            return_type=self.text(ret) if ret is not None else "var",
            body=self._translate_block(body_node), line=self.line(node))

    # -- statements ------------------------------------------------------

    def _translate_block(self, node) -> ir.Block:
        block = ir.Block(statements=[], line=self.line(node))
        for stmt in node.children:
            block.statements.extend(self.stmt_list(self._translate_stmt(stmt)))
        return block

    def _translate_stmt(self, node):
        t = node.type
        if t == "expression_statement":
            inner = node.children[0]
            if inner.type == "assignment":
                return self._translate_assignment(inner)
            if inner.type == "augmented_assignment":
                return self._translate_augmented(inner)
            return ir.ExprStmt(expr=self._translate_expr(inner), line=self.line(node))
        if t == "if_statement":
            return self._translate_if(node)
        if t == "while_statement":
            if node.child_by_field_name("alternative") is not None:
                self.unsupported(node, context="while ... else")
            return self._translate_while(node)
        if t == "for_statement":
            return self._translate_for(node)
        if t == "return_statement":
            candidates = [c for c in node.children if c.type not in ("return", ";", "comment")]
            value = self._translate_expr(candidates[0]) if candidates else None
            return ir.Return(value=value, line=self.line(node))
        if t in ("comment", "pass_statement"):
            return None
        self.unsupported(node, context="statement")

    def _translate_assignment(self, node):
        target_node = node.child_by_field_name("left") or node.children[0]
        value_node = node.child_by_field_name("right")
        if target_node.type != "identifier":
            self.unsupported(target_node, context="assignment target (tuple unpacking, attributes, subscripts)")
        if value_node is None:                              # bare annotation `x: int`
            return None
        return ir.Assign(target=self.text(target_node), value=self._translate_expr(value_node), line=self.line(node))

    def _translate_augmented(self, node):
        target = node.child_by_field_name("left")
        op = self.text(node.child_by_field_name("operator"))
        if target.type != "identifier" or op not in COMPOUND_ASSIGN:
            self.unsupported(node, context=f"augmented assignment {op}")
        name = self.text(target)
        line = self.line(node)
        return ir.Assign(target=name, line=line, value=ir.BinOp(
            op=COMPOUND_ASSIGN[op], left=ir.Identifier(name=name, line=line),
            right=self._translate_expr(node.child_by_field_name("right")), line=line))

    def _translate_if(self, node) -> ir.If:
        cond_node = node.child_by_field_name("condition")
        then_node = node.child_by_field_name("consequence")
        alternatives = node.children_by_field_name("alternative")

        else_block = None
        # build the elif / else chain from the end so each elif becomes a nested If in an else-block
        for alt in reversed(alternatives):
            if alt.type == "else_clause":
                else_block = self._translate_block(alt.child_by_field_name("body"))
            elif alt.type == "elif_clause":
                nested = ir.If(cond=self._translate_expr(alt.child_by_field_name("condition")),
                               then_block=self._translate_block(alt.child_by_field_name("consequence")),
                               else_block=else_block, line=self.line(alt))
                else_block = ir.Block(statements=[nested], line=self.line(alt))
        return ir.If(cond=self._translate_expr(cond_node), then_block=self._translate_block(then_node),
                     else_block=else_block, line=self.line(node))

    def _translate_while(self, node) -> ir.While:
        return ir.While(cond=self._translate_expr(node.child_by_field_name("condition")),
                        body=self._translate_block(node.child_by_field_name("body")), line=self.line(node))

    # -- for i in range(...) -----------------------------------------------------

    def _used_after(self, loop_node, name) -> bool:
        """Is `name` read after the loop (other than as the variable of a later for loop)?"""
        rebinding = []
        stack = [self._fn_node]
        hits = []
        while stack:
            n = stack.pop()
            if n.type == "for_statement" and n.start_byte >= loop_node.end_byte:
                left = n.child_by_field_name("left")
                if left is not None and left.type == "identifier" and self.text(left) == name:
                    rebinding.append((n.start_byte, n.end_byte))
            if n.type == "identifier" and n.start_byte >= loop_node.end_byte and self.text(n) == name:
                hits.append(n.start_byte)
            stack.extend(n.children)
        return any(not any(a <= h < b for a, b in rebinding) for h in hits)

    def _translate_for(self, node):
        left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
        if node.child_by_field_name("alternative") is not None:
            self.unsupported(node, context="for ... else")
        if left is None or left.type != "identifier":
            self.unsupported(node, context="for-loop target (only a single variable)")
        if right is None or right.type != "call" or self.text(right.child_by_field_name("function")) != "range":
            self.unsupported(node, context="for loop (only `for x in range(...)` is supported)")

        var = self.text(left)
        args = [c for c in right.child_by_field_name("arguments").children if c.type not in ("(", ")", ",", "comment")]
        if not 1 <= len(args) <= 3 or any(a.type == "keyword_argument" for a in args):
            self.unsupported(right, context="range() arguments")
        exprs = [self._translate_expr(a) for a in args]
        start = exprs[0] if len(exprs) >= 2 else ir.Literal(value=0, type="int", line=self.line(node))
        stop = exprs[1] if len(exprs) >= 2 else exprs[0]
        step = 1
        if len(exprs) == 3:
            s = exprs[2]
            if isinstance(s, ir.UnaryOp) and s.op == "-" and isinstance(s.operand, ir.Literal):
                s = ir.Literal(value=-s.operand.value, type="int")
            if not (isinstance(s, ir.Literal) and s.type == "int" and s.value != 0):
                self.unsupported(args[2], context="range() step (must be a non-zero integer literal)")
            step = s.value
        if has_call(start) or has_call(stop):
            self.unsupported(right, context="range() bounds that call functions (they are evaluated once in Python)")

        body = self._translate_block(node.child_by_field_name("body"))
        if var in defined_names(body):
            self.unsupported(node, context=f"for loop whose body assigns the loop variable '{var}'")
        if self._used_after(node, var):
            self.unsupported(node, context=f"for loop whose variable '{var}' is used after the loop "
                                           f"(its final value differs between Python's range loop and a while loop)")

        line = self.line(node)
        out = []
        if isinstance(stop, ir.Literal):
            bound = stop
        else:
            tmp = self.fresh_name("_stop")                  # range() evaluates its bound ONCE
            out.append(ir.Assign(target=tmp, value=stop, line=line))
            bound = ir.Identifier(name=tmp, line=line)
        out.append(ir.Assign(target=var, value=start, line=line))
        body.statements.append(ir.Assign(target=var, line=line, value=ir.BinOp(
            op="+", left=ir.Identifier(name=var, line=line), right=ir.Literal(value=step, type="int", line=line), line=line)))
        out.append(ir.While(cond=ir.BinOp(op="<" if step > 0 else ">", left=ir.Identifier(name=var, line=line),
                                          right=bound, line=line), body=body, line=line))
        return out

    # -- expressions -------------------------------------------------------

    def _translate_string(self, node):
        kinds = {c.type for c in node.children}
        if not kinds <= {"string_start", "string_content", "string_end", "escape_sequence"}:
            self.unsupported(node, context="f-string / formatted string")
        start = next(c for c in node.children if c.type == "string_start")
        if self.text(start).lower().lstrip("'\"") not in ("",) and self.text(start)[0].lower() in "bf":
            self.unsupported(node, context="bytes / formatted string")
        raw = self.text(node)
        quote = 3 if raw.endswith(('"""', "'''")) and len(raw) >= 6 else 1
        prefix = len(self.text(start)) - quote
        return ir.Literal(value=raw[prefix + quote:-quote], type="string", line=self.line(node))

    def _translate_compare(self, node):
        operands = [c for c in node.children if c.is_named and c.type != "comment"]
        ops = [self.text(c) for c in node.children_by_field_name("operators")]
        if not ops or any(o not in COMPARE_OPS for o in ops):
            self.unsupported(node, context=f"comparison operator {ops} (in / is / not in are not supported)")
        exprs = [self._translate_expr(o) for o in operands]
        if len(ops) == 1:
            return ir.BinOp(op=ops[0], left=exprs[0], right=exprs[1], line=self.line(node))
        if any(has_call(e) for e in exprs[1:-1]):
            self.unsupported(node, context="chained comparison with a function call in the middle")
        parts = [ir.BinOp(op=o, left=exprs[i], right=exprs[i + 1], line=self.line(node)) for i, o in enumerate(ops)]
        result = parts[0]
        for p in parts[1:]:
            result = ir.BinOp(op="&&", left=result, right=p, line=self.line(node))
        return result

    def _translate_expr(self, node):
        t = node.type
        if t == "identifier":
            return ir.Identifier(name=self.text(node), line=self.line(node))
        if t == "integer":
            return ir.Literal(value=parse_int_literal(self.text(node), "python"), type="int", line=self.line(node))
        if t == "float":
            return ir.Literal(value=float(self.text(node).replace("_", "")), type="float", line=self.line(node))
        if t == "true":
            return ir.Literal(value=True, type="bool", line=self.line(node))
        if t == "false":
            return ir.Literal(value=False, type="bool", line=self.line(node))
        if t == "string":
            return self._translate_string(node)
        if t == "comparison_operator":
            return self._translate_compare(node)
        if t in ("binary_operator", "boolean_operator"):
            left = node.child_by_field_name("left") or node.children[0]
            right = node.child_by_field_name("right") or node.children[-1]
            op_node = node.child_by_field_name("operator") or [c for c in node.children if c not in (left, right)][0]
            op = self.normalize_op(self.text(op_node))
            if t == "binary_operator" and op not in PYTHON_BINARY_OPS:
                self.unsupported(node, context=f"operator {op}")
            return ir.BinOp(op=op, left=self._translate_expr(left), right=self._translate_expr(right),
                            line=self.line(node))
        if t == "not_operator":
            operand = node.child_by_field_name("argument") or node.children[-1]
            return ir.UnaryOp(op="!", operand=self._translate_expr(operand), line=self.line(node))
        if t == "unary_operator":
            op = self.text(node.children[0])
            if op not in ("-", "+", "~"):
                self.unsupported(node, context=f"unary operator {op}")
            operand = node.child_by_field_name("argument") or node.children[-1]
            return ir.UnaryOp(op=op, operand=self._translate_expr(operand), line=self.line(node))
        if t == "call":
            func_node = node.child_by_field_name("function")
            args_node = node.child_by_field_name("arguments")
            args = [self._translate_expr(c) for c in args_node.children if c.type not in ("(", ")", ",", "comment")]
            return ir.Call(name=self.text(func_node), args=args, line=self.line(node))
        if t == "parenthesized_expression":
            inner = [c for c in node.children if c.type not in ("(", ")")][0]
            return self._translate_expr(inner)
        self.unsupported(node, context="expression")