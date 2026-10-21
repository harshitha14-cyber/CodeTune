from .base import (C_FAMILY_BINARY_OPS, COMPOUND_ASSIGN, TranslatorBase, parse_int_literal)
from .. import ir_nodes as ir


class CTranslator(TranslatorBase):
    """Translator for C. Also the base for the C++ translator, since the two
    grammars overlap heavily for the subset CodeTune supports."""

    source_language = "c"

    def translate_program(self, root_node) -> ir.Program:
        program = ir.Program(source_language=self.source_language, functions=[])
        for child in root_node.children:
            if child.type == "function_definition":
                program.functions.append(self._translate_function(child))
        return program

    # -- functions -------------------------------------------------------

    def _prescan(self, func_node, params):
        self._reset_function_state()
        self._reserved = self.collect_identifiers(func_node)
        self._plain_decls = {p.name for p in params}
        stack = [func_node.child_by_field_name("body")]
        while stack:
            n = stack.pop()
            if n is None:
                continue
            if n.type == "declaration" and n.parent is not None and n.parent.type != "for_statement":
                for d in n.children_by_field_name("declarator"):
                    target = d.child_by_field_name("declarator") if d.type == "init_declarator" else d
                    if target is not None and target.type == "identifier":
                        self._plain_decls.add(self.text(target))
            stack.extend(n.children)

    def _translate_function(self, node) -> ir.FuncDecl:
        return_type_node = node.child_by_field_name("type")
        declarator = node.child_by_field_name("declarator")
        body_node = node.child_by_field_name("body")
        if declarator is None or declarator.type != "function_declarator":
            self.unsupported(declarator or node, context="function declarator (pointer/array return types)")

        name_node = declarator.child_by_field_name("declarator")
        params_node = declarator.child_by_field_name("parameters")
        params = []
        for p in params_node.children:
            if p.type == "parameter_declaration":
                p_type = p.child_by_field_name("type")
                p_name = p.child_by_field_name("declarator")
                if p_name is None:                       # `(void)`
                    continue
                if p_name.type != "identifier":
                    self.unsupported(p, context="parameter (pointer / array / reference parameters)")
                params.append(ir.Param(name=self.text(p_name),
                                       param_type=self.text(p_type) if p_type else "var", line=self.line(p)))
            elif p.type == "variadic_parameter":
                self.unsupported(p, context="parameter list")

        self._prescan(node, params)
        return ir.FuncDecl(
            name=self.text(name_node), params=params,
            return_type=self.text(return_type_node) if return_type_node else "var",
            body=self._translate_block(body_node), line=self.line(node))

    # -- statements --------------------------------------------------------

    def _translate_block(self, node) -> ir.Block:
        block = ir.Block(statements=[], line=self.line(node))
        for stmt in node.children:
            if stmt.type in ("{", "}"):
                continue
            block.statements.extend(self.stmt_list(self._translate_stmt(stmt)))
        return block

    def _translate_stmt(self, node):
        t = node.type
        if t == "declaration":
            return self._translate_declaration(node)
        if t == "expression_statement":
            return self._translate_expression_statement(node)
        if t == "if_statement":
            return self._translate_if(node)
        if t == "while_statement":
            return self._translate_while(node)
        if t == "for_statement":
            return self._translate_for(node)
        if t == "return_statement":
            candidates = [c for c in node.children if c.type not in ("return", ";", "comment")]
            value = self._translate_expr(candidates[0]) if candidates else None
            return ir.Return(value=value, line=self.line(node))
        if t in ("comment", ";"):
            return None
        self.unsupported(node, context="statement")

    def _translate_expression_statement(self, node):
        inner = [c for c in node.children if c.type not in (";", "comment")][0]
        stmts = self._translate_effect(inner)
        return stmts

    def _translate_effect(self, node):
        """An expression used only for its side effect: assignment, ++/--, call ..."""
        if node.type == "assignment_expression":
            return self._translate_assignment(node)
        if node.type == "update_expression":
            return self._translate_update(node)
        if node.type == "comma_expression":
            out = []
            for part in (node.child_by_field_name("left"), node.child_by_field_name("right")):
                out.extend(self.stmt_list(self._translate_effect(part)))
            return out
        return ir.ExprStmt(expr=self._translate_expr(node), line=self.line(node))

    def _declarators(self, node):
        return node.children_by_field_name("declarator")

    def _translate_declaration(self, node):
        type_node = node.child_by_field_name("type")
        var_type = self.text(type_node) if type_node else "var"
        out = []
        for d in self._declarators(node):
            if d.type == "init_declarator":
                name_node = d.child_by_field_name("declarator")
                value_node = d.child_by_field_name("value")
            else:
                name_node, value_node = d, None
            if name_node.type != "identifier":
                self.unsupported(d, context="declaration (arrays / pointers / references)")
            out.append(ir.VarDecl(
                name=self.rename(self.text(name_node)), var_type=var_type,
                init=self._translate_expr(value_node) if value_node is not None else None,
                line=self.line(node)))
        return out

    def _target_name(self, node) -> str:
        if node.type != "identifier":
            self.unsupported(node, context="assignment target (only plain variables)")
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

    def _update_parts(self, node):
        arg = node.child_by_field_name("argument")
        op = node.child_by_field_name("operator")
        if arg is None or op is None:                    # Java layout: identifier, operator as plain children
            kids = [c for c in node.children if c.type != "comment"]
            arg = next(c for c in kids if c.type not in ("++", "--"))
            op = next(c for c in kids if c.type in ("++", "--"))
        return arg, self.text(op)

    def _translate_update(self, node) -> ir.Assign:
        arg, op = self._update_parts(node)
        name = self._target_name(arg)
        line = self.line(node)
        return ir.Assign(target=name, line=line, value=ir.BinOp(
            op="+" if op == "++" else "-", left=ir.Identifier(name=name, line=line),
            right=ir.Literal(value=1, type="int", line=line), line=line))

    def _condition_expr(self, node):
        """`if (cond) {..}` -- cond is inside parenthesized_expression (C) or
        condition_clause (C++); pull the inner expression out either way."""
        inner = [c for c in node.children if c.type not in ("(", ")")]
        return self._translate_expr(inner[0])

    def _body(self, node) -> ir.Block:
        if node.type == "compound_statement":
            return self._translate_block(node)
        return self._translate_block_single(node)

    def _translate_if(self, node) -> ir.If:
        cond_node = node.child_by_field_name("condition")
        then_node = node.child_by_field_name("consequence")
        else_node = node.child_by_field_name("alternative")

        else_block = None
        if else_node is not None:
            if else_node.type == "else_clause":
                else_node = [c for c in else_node.children if c.type != "else"][0]
            else_block = self._body(else_node)

        return ir.If(cond=self._condition_expr(cond_node), then_block=self._body(then_node),
                     else_block=else_block, line=self.line(node))

    def _translate_block_single(self, stmt_node) -> ir.Block:
        """C/C++/Java allow a bare statement (no braces) as an if/while body."""
        return ir.Block(statements=self.stmt_list(self._translate_stmt(stmt_node)), line=self.line(stmt_node))

    def _translate_while(self, node) -> ir.While:
        cond_node = node.child_by_field_name("condition")
        body_node = node.child_by_field_name("body")
        return ir.While(cond=self._condition_expr(cond_node), body=self._body(body_node), line=self.line(node))

    # -- for loops ------------------------------------------------------------------------

    def _for_parts(self, node):
        init = node.child_by_field_name("initializer")
        return init, node.child_by_field_name("condition"), [node.child_by_field_name("update")], \
            node.child_by_field_name("body")

    def _for_init(self, init, renames):
        """Statements for the initializer; fills `renames` (already on the rename stack)
        for any declared loop variable."""
        if init is None:
            return []
        if init.type == "declaration":
            for d in self._declarators(init):
                target = d.child_by_field_name("declarator") if d.type == "init_declarator" else d
                if target is not None and target.type == "identifier":
                    old = self.text(target)
                    renames[old] = self.loop_var_name(old)
            return self._translate_declaration(init)
        return self.stmt_list(self._translate_effect(init))

    def _translate_for(self, node):
        init, cond, updates, body = self._for_parts(node)
        renames = {}
        self._renames.append(renames)          # the loop variable lives only inside the loop
        try:
            init_stmts = self._for_init(init, renames)
            cond_expr = self._translate_expr(cond) if cond is not None else ir.Literal(value=True, type="bool", line=self.line(node))
            body_block = self._body(body)
            for u in updates:
                if u is not None:
                    body_block.statements.extend(self.stmt_list(self._translate_effect(u)))
        finally:
            self._renames.pop()
        return init_stmts + [ir.While(cond=cond_expr, body=body_block, line=self.line(node))]

    # -- expressions ---------------------------------------------------------

    def _number(self, node):
        text = self.text(node)
        low = text.lower()
        is_hex = low.startswith("0x")
        if low.endswith("f") and not is_hex or low.rstrip("ul").endswith("l") and "." in low:
            self.unsupported(node, context="32-bit float / long double literal")
        if low.endswith(("ll", "l")) and not "." in low:
            self.unsupported(node, context="64-bit long literal (only 32-bit int arithmetic is modelled)")
        if "." in low or (not is_hex and "e" in low):
            return ir.Literal(value=float(low.replace("'", "")), type="float", line=self.line(node))
        return ir.Literal(value=parse_int_literal(text, self.source_language), type="int", line=self.line(node))

    def _translate_expr(self, node):
        t = node.type
        if t == "identifier":
            return ir.Identifier(name=self.rename(self.text(node)), line=self.line(node))
        if t == "number_literal":
            return self._number(node)
        if t == "true":
            return ir.Literal(value=True, type="bool", line=self.line(node))
        if t == "false":
            return ir.Literal(value=False, type="bool", line=self.line(node))
        if t == "string_literal":
            return ir.Literal(value=self.text(node)[1:-1], type="string", line=self.line(node))
        if t == "binary_expression":
            op_node = node.child_by_field_name("operator")
            op = self.text(op_node) if op_node else "?"
            if op not in C_FAMILY_BINARY_OPS:
                self.unsupported(node, context=f"operator {op}")
            return ir.BinOp(op=self.normalize_op(op), left=self._translate_expr(node.child_by_field_name("left")),
                            right=self._translate_expr(node.child_by_field_name("right")), line=self.line(node))
        if t == "unary_expression":
            op_node = node.children[0]
            op = self.text(op_node)
            if op not in ("-", "+", "!", "~"):
                self.unsupported(node, context=f"unary operator {op}")
            operand = node.child_by_field_name("argument") or node.children[-1]
            return ir.UnaryOp(op=op, operand=self._translate_expr(operand), line=self.line(node))
        if t == "call_expression":
            func_node = node.child_by_field_name("function")
            args_node = node.child_by_field_name("arguments")
            args = [self._translate_expr(c) for c in args_node.children if c.type not in ("(", ")", ",", "comment")]
            return ir.Call(name=self.text(func_node), args=args, line=self.line(node))
        if t == "parenthesized_expression":
            inner = [c for c in node.children if c.type not in ("(", ")")][0]
            return self._translate_expr(inner)
        self.unsupported(node, context="expression")