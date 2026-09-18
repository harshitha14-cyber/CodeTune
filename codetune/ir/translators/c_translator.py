from .base import TranslatorBase
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

    def _translate_function(self, node) -> ir.FuncDecl:
        return_type_node = node.child_by_field_name("type")
        declarator = node.child_by_field_name("declarator")
        body_node = node.child_by_field_name("body")

        name_node = declarator.child_by_field_name("declarator")
        params_node = declarator.child_by_field_name("parameters")

        params = []
        for p in params_node.children:
            if p.type == "parameter_declaration":
                p_type = p.child_by_field_name("type")
                p_name = p.child_by_field_name("declarator")
                params.append(ir.Param(
                    name=self.text(p_name) if p_name else "?",
                    param_type=self.text(p_type) if p_type else "var",
                    line=self.line(p),
                ))

        return ir.FuncDecl(
            name=self.text(name_node),
            params=params,
            return_type=self.text(return_type_node) if return_type_node else "var",
            body=self._translate_block(body_node),
            line=self.line(node),
        )

    # -- statements --------------------------------------------------------

    def _translate_block(self, node) -> ir.Block:
        block = ir.Block(statements=[], line=self.line(node))
        for stmt in node.children:
            if stmt.type in ("{", "}"):
                continue
            translated = self._translate_stmt(stmt)
            if translated is not None:
                block.statements.append(translated)
        return block

    def _translate_stmt(self, node):
        if node.type == "declaration":
            return self._translate_declaration(node)
        if node.type == "expression_statement":
            inner = node.children[0]
            if inner.type == "assignment_expression":
                return self._translate_assignment(inner)
            return ir.ExprStmt(expr=self._translate_expr(inner), line=self.line(node))
        if node.type == "if_statement":
            return self._translate_if(node)
        if node.type == "while_statement":
            return self._translate_while(node)
        if node.type == "return_statement":
            candidates = [c for c in node.children if c.type not in ("return", ";")]
            value = self._translate_expr(candidates[0]) if candidates else None
            return ir.Return(value=value, line=self.line(node))
        if node.type in ("comment", ";"):
            return None
        self.unsupported(node, context="statement")

    def _translate_declaration(self, node) -> ir.VarDecl:
        type_node = node.child_by_field_name("type")
        declarator = node.child_by_field_name("declarator")
        var_type = self.text(type_node) if type_node else "var"

        if declarator.type == "init_declarator":
            name_node = declarator.child_by_field_name("declarator")
            value_node = declarator.child_by_field_name("value")
            return ir.VarDecl(
                name=self.text(name_node),
                var_type=var_type,
                init=self._translate_expr(value_node),
                line=self.line(node),
            )
        # plain declaration with no initializer, e.g. `int y;`
        return ir.VarDecl(name=self.text(declarator), var_type=var_type, init=None, line=self.line(node))

    def _translate_assignment(self, node) -> ir.Assign:
        target_node = node.child_by_field_name("left") or node.children[0]
        value_node = node.child_by_field_name("right") or node.children[-1]
        return ir.Assign(
            target=self.text(target_node),
            value=self._translate_expr(value_node),
            line=self.line(node),
        )

    def _condition_expr(self, node):
        """`if (cond) {..}` -- cond is inside parenthesized_expression (C) or
        condition_clause (C++); pull the inner expression out either way."""
        inner = [c for c in node.children if c.type not in ("(", ")")]
        return self._translate_expr(inner[0])

    def _translate_if(self, node) -> ir.If:
        cond_node = node.child_by_field_name("condition")
        then_node = node.child_by_field_name("consequence")
        else_node = node.child_by_field_name("alternative")

        else_block = None
        if else_node is not None:
            # C/C++ wrap the alternative in an 'else_clause' node
            # (else_clause -> 'else' + the actual statement/block).
            if else_node.type == "else_clause":
                else_node = [c for c in else_node.children if c.type != "else"][0]
            else_block = self._translate_block(else_node) if else_node.type == "compound_statement" \
                else self._translate_block_single(else_node)

        then_block = self._translate_block(then_node) if then_node.type == "compound_statement" \
            else self._translate_block_single(then_node)

        return ir.If(
            cond=self._condition_expr(cond_node),
            then_block=then_block,
            else_block=else_block,
            line=self.line(node),
        )

    def _translate_block_single(self, stmt_node) -> ir.Block:
        """C/C++/Java allow a bare statement (no braces) as an if/while body;
        normalize it into a one-statement Block for the IR."""
        translated = self._translate_stmt(stmt_node)
        return ir.Block(statements=[translated] if translated else [], line=self.line(stmt_node))

    def _translate_while(self, node) -> ir.While:
        cond_node = node.child_by_field_name("condition")
        body_node = node.child_by_field_name("body")
        body = self._translate_block(body_node) if body_node.type == "compound_statement" \
            else self._translate_block_single(body_node)
        return ir.While(cond=self._condition_expr(cond_node), body=body, line=self.line(node))

    # -- expressions ---------------------------------------------------------

    def _translate_expr(self, node):
        if node.type == "identifier":
            return ir.Identifier(name=self.text(node), line=self.line(node))
        if node.type == "number_literal":
            text = self.text(node)
            if "." in text:
                return ir.Literal(value=float(text), type="float", line=self.line(node))
            return ir.Literal(value=int(text), type="int", line=self.line(node))
        if node.type == "true":
            return ir.Literal(value=True, type="bool", line=self.line(node))
        if node.type == "false":
            return ir.Literal(value=False, type="bool", line=self.line(node))
        if node.type == "string_literal":
            content = "".join(c.text.decode() for c in node.children if c.type == "string_content")
            return ir.Literal(value=content, type="string", line=self.line(node))
        if node.type == "binary_expression":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            op_node = node.child_by_field_name("operator")
            return ir.BinOp(
                op=self.normalize_op(self.text(op_node)) if op_node else "?",
                left=self._translate_expr(left),
                right=self._translate_expr(right),
                line=self.line(node),
            )
        if node.type == "unary_expression":
            op_node = node.children[0]
            operand = node.child_by_field_name("argument") or node.children[-1]
            return ir.UnaryOp(op=self.text(op_node), operand=self._translate_expr(operand), line=self.line(node))
        if node.type in ("call_expression",):
            func_node = node.child_by_field_name("function")
            args_node = node.child_by_field_name("arguments")
            args = [self._translate_expr(c) for c in args_node.children if c.type not in ("(", ")", ",")]
            return ir.Call(name=self.text(func_node), args=args, line=self.line(node))
        if node.type == "parenthesized_expression":
            inner = [c for c in node.children if c.type not in ("(", ")")][0]
            return self._translate_expr(inner)
        self.unsupported(node, context="expression")
