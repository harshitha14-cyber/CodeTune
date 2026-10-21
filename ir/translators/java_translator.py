from .base import (C_FAMILY_BINARY_OPS, COMPOUND_ASSIGN, TranslatorBase, parse_int_literal)
from .. import ir_nodes as ir


class JavaTranslator(TranslatorBase):
    source_language = "java"

    def translate_program(self, root_node) -> ir.Program:
        program = ir.Program(source_language=self.source_language, functions=[])
        for child in root_node.children:
            if child.type == "class_declaration":
                body = child.child_by_field_name("body")
                for member in body.children:
                    if member.type == "method_declaration":
                        program.functions.append(self._translate_function(member))
        return program

    # -- functions ---------------------------------------------------------

    def _prescan(self, func_node, params):
        self._reset_function_state()
        self._reserved = self.collect_identifiers(func_node)
        self._plain_decls = {p.name for p in params}
        stack = [func_node.child_by_field_name("body")]
        while stack:
            n = stack.pop()
            if n is None:
                continue
            if n.type == "local_variable_declaration" and n.parent is not None and n.parent.type != "for_statement":
                for d in n.children_by_field_name("declarator"):
                    name = d.child_by_field_name("name")
                    if name is not None:
                        self._plain_decls.add(self.text(name))
            stack.extend(n.children)

    def _translate_function(self, node) -> ir.FuncDecl:
        return_type_node = node.child_by_field_name("type")
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        if body_node is None:
            self.unsupported(node, context="abstract / interface method")

        params = []
        for p in params_node.children:
            if p.type == "formal_parameter":
                p_type = p.child_by_field_name("type")
                p_name = p.child_by_field_name("name")
                if p_type.type == "array_type" or p.child_by_field_name("dimensions") is not None:
                    self.unsupported(p, context="array parameter")
                params.append(ir.Param(name=self.text(p_name), param_type=self.text(p_type), line=self.line(p)))
            elif p.type == "spread_parameter":
                self.unsupported(p, context="varargs parameter")

        self._prescan(node, params)
        return ir.FuncDecl(
            name=self.text(name_node), params=params,
            return_type=self.text(return_type_node) if return_type_node else "void",
            body=self._translate_block(body_node), line=self.line(node))

    # -- statements ----------------------------------------------------------

    def _translate_block(self, node) -> ir.Block:
        block = ir.Block(statements=[], line=self.line(node))
        for stmt in node.children:
            if stmt.type in ("{", "}"):
                continue
            block.statements.extend(self.stmt_list(self._translate_stmt(stmt)))
        return block

    def _translate_stmt(self, node):
        t = node.type
        if t == "local_variable_declaration":
            return self._translate_declaration(node)
        if t == "expression_statement":
            inner = [c for c in node.children if c.type not in (";", "line_comment", "block_comment")][0]
            return self._translate_effect(inner)
        if t == "if_statement":
            return self._translate_if(node)
        if t == "while_statement":
            return self._translate_while(node)
        if t == "for_statement":
            return self._translate_for(node)
        if t == "return_statement":
            candidates = [c for c in node.children if c.type not in ("return", ";", "line_comment", "block_comment")]
            value = self._translate_expr(candidates[0]) if candidates else None
            return ir.Return(value=value, line=self.line(node))
        if t in ("comment", ";", "line_comment", "block_comment"):
            return None
        self.unsupported(node, context="statement")

    def _translate_effect(self, node):
        if node.type == "assignment_expression":
            return self._translate_assignment(node)
        if node.type == "update_expression":
            return self._translate_update(node)
        return ir.ExprStmt(expr=self._translate_expr(node), line=self.line(node))

    def _translate_declaration(self, node):
        type_node = node.child_by_field_name("type")
        if type_node is not None and type_node.type == "array_type":
            self.unsupported(node, context="array declaration")
        var_type = self.text(type_node) if type_node else "var"
        out = []
        for d in node.children_by_field_name("declarator"):
            name_node = d.child_by_field_name("name")
            value_node = d.child_by_field_name("value")
            if d.child_by_field_name("dimensions") is not None:
                self.unsupported(d, context="array declaration")
            out.append(ir.VarDecl(
                name=self.rename(self.text(name_node)), var_type=var_type,
                init=self._translate_expr(value_node) if value_node is not None else None,
                line=self.line(node)))
        return out

    def _target_name(self, node) -> str:
        if node.type != "identifier":
            self.unsupported(node, context="assignment target (only plain local variables)")
        return self.rename(self.text(node))

    def _translate_assignment(self, node) -> ir.Assign:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        op_node = node.child_by_field_name("operator")
        op = self.text(op_node) if op_node is not None else "="
        name = self._target_name(left)
        value = self._translate_expr(right)
        if op != "=":
            if op not in COMPOUND_ASSIGN:
                self.unsupported(node, context=f"assignment operator {op}")
            value = ir.BinOp(op=COMPOUND_ASSIGN[op], left=ir.Identifier(name=name, line=self.line(left)),
                             right=value, line=self.line(node))
        return ir.Assign(target=name, value=value, line=self.line(node))

    def _translate_update(self, node) -> ir.Assign:
        kids = [c for c in node.children if c.type not in ("line_comment", "block_comment")]
        op = next(self.text(c) for c in kids if c.type in ("++", "--"))
        arg = next(c for c in kids if c.type not in ("++", "--"))
        name = self._target_name(arg)
        line = self.line(node)
        return ir.Assign(target=name, line=line, value=ir.BinOp(
            op="+" if op == "++" else "-", left=ir.Identifier(name=name, line=line),
            right=ir.Literal(value=1, type="int", line=line), line=line))

    def _condition_expr(self, node):
        inner = [c for c in node.children if c.type not in ("(", ")")]
        return self._translate_expr(inner[0])

    def _body(self, node) -> ir.Block:
        if node.type == "block":
            return self._translate_block(node)
        return self._translate_block_single(node)

    def _translate_block_single(self, stmt_node) -> ir.Block:
        return ir.Block(statements=self.stmt_list(self._translate_stmt(stmt_node)), line=self.line(stmt_node))

    def _translate_if(self, node) -> ir.If:
        cond_node = node.child_by_field_name("condition")
        then_node = node.child_by_field_name("consequence")
        else_node = node.child_by_field_name("alternative")
        return ir.If(cond=self._condition_expr(cond_node), then_block=self._body(then_node),
                     else_block=self._body(else_node) if else_node is not None else None, line=self.line(node))

    def _translate_while(self, node) -> ir.While:
        cond_node = node.child_by_field_name("condition")
        body_node = node.child_by_field_name("body")
        return ir.While(cond=self._condition_expr(cond_node), body=self._body(body_node), line=self.line(node))

    def _translate_for(self, node):
        init = node.child_by_field_name("init")
        cond = node.child_by_field_name("condition")
        updates = node.children_by_field_name("update")
        body = node.child_by_field_name("body")
        renames = {}
        self._renames.append(renames)
        try:
            init_stmts = []
            if init is not None and init.type == "local_variable_declaration":
                for d in init.children_by_field_name("declarator"):
                    old = self.text(d.child_by_field_name("name"))
                    renames[old] = self.loop_var_name(old)
                init_stmts = self._translate_declaration(init)
            else:
                for e in node.children_by_field_name("init"):
                    init_stmts.extend(self.stmt_list(self._translate_effect(e)))
            cond_expr = self._translate_expr(cond) if cond is not None else ir.Literal(value=True, type="bool", line=self.line(node))
            body_block = self._body(body)
            for u in updates:
                body_block.statements.extend(self.stmt_list(self._translate_effect(u)))
        finally:
            self._renames.pop()
        return init_stmts + [ir.While(cond=cond_expr, body=body_block, line=self.line(node))]

    # -- expressions -----------------------------------------------------------

    def _translate_expr(self, node):
        t = node.type
        if t == "identifier":
            return ir.Identifier(name=self.rename(self.text(node)), line=self.line(node))
        if t in ("decimal_integer_literal", "hex_integer_literal", "octal_integer_literal", "binary_integer_literal"):
            text = self.text(node)
            if text.lower().endswith("l"):
                self.unsupported(node, context="64-bit long literal (only 32-bit int arithmetic is modelled)")
            return ir.Literal(value=parse_int_literal(text, "java"), type="int", line=self.line(node))
        if t == "decimal_floating_point_literal":
            text = self.text(node).replace("_", "")
            if text.lower().endswith("f"):
                self.unsupported(node, context="32-bit float literal")
            return ir.Literal(value=float(text.rstrip("dD")), type="float", line=self.line(node))
        if t == "true":
            return ir.Literal(value=True, type="bool", line=self.line(node))
        if t == "false":
            return ir.Literal(value=False, type="bool", line=self.line(node))
        if t == "string_literal":
            raw = self.text(node)
            if raw.startswith('"""'):
                self.unsupported(node, context="text block")
            return ir.Literal(value=raw[1:-1], type="string", line=self.line(node))
        if t == "binary_expression":
            op_node = node.child_by_field_name("operator")
            op = self.text(op_node) if op_node else "?"
            if op not in C_FAMILY_BINARY_OPS:
                self.unsupported(node, context=f"operator {op}")
            return ir.BinOp(op=self.normalize_op(op), left=self._translate_expr(node.child_by_field_name("left")),
                            right=self._translate_expr(node.child_by_field_name("right")), line=self.line(node))
        if t == "unary_expression":
            op = self.text(node.children[0])
            if op not in ("-", "+", "!", "~"):
                self.unsupported(node, context=f"unary operator {op}")
            operand = node.child_by_field_name("operand") or node.children[-1]
            return ir.UnaryOp(op=op, operand=self._translate_expr(operand), line=self.line(node))
        if t == "method_invocation":
            name_node = node.child_by_field_name("name")
            obj = node.child_by_field_name("object")
            args_node = node.child_by_field_name("arguments")
            args = [self._translate_expr(c) for c in args_node.children if c.type not in ("(", ")", ",", "line_comment", "block_comment")]
            name = self.text(name_node)
            if obj is not None and self.text(obj) != "this":
                name = f"{self.text(obj)}.{name}"          # Math.max, System.out.println ... never collide with user methods
            return ir.Call(name=name, args=args, line=self.line(node))
        if t == "parenthesized_expression":
            inner = [c for c in node.children if c.type not in ("(", ")")][0]
            return self._translate_expr(inner)
        self.unsupported(node, context="expression")