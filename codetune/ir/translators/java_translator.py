from .base import TranslatorBase
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

    def _translate_function(self, node) -> ir.FuncDecl:
        return_type_node = node.child_by_field_name("type")
        name_node = node.child_by_field_name("name")
        params_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")

        params = []
        for p in params_node.children:
            if p.type == "formal_parameter":
                p_type = p.child_by_field_name("type")
                p_name = p.child_by_field_name("name")
                params.append(ir.Param(
                    name=self.text(p_name),
                    param_type=self.text(p_type),
                    line=self.line(p),
                ))

        return ir.FuncDecl(
            name=self.text(name_node),
            params=params,
            return_type=self.text(return_type_node) if return_type_node else "void",
            body=self._translate_block(body_node),
            line=self.line(node),
        )

    # -- statements ----------------------------------------------------------

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
        if node.type == "local_variable_declaration":
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
        if node.type in ("comment", ";", "line_comment", "block_comment"):
            return None
        self.unsupported(node, context="statement")

    def _translate_declaration(self, node) -> ir.VarDecl:
        type_node = node.child_by_field_name("type")
        declarator = node.child_by_field_name("declarator")
        var_type = self.text(type_node) if type_node else "var"

        name_node = declarator.child_by_field_name("name")
        value_node = declarator.child_by_field_name("value")
        return ir.VarDecl(
            name=self.text(name_node),
            var_type=var_type,
            init=self._translate_expr(value_node) if value_node is not None else None,
            line=self.line(node),
        )

    def _translate_assignment(self, node) -> ir.Assign:
        target_node = node.child_by_field_name("left") or node.children[0]
        value_node = node.child_by_field_name("right") or node.children[-1]
        return ir.Assign(
            target=self.text(target_node),
            value=self._translate_expr(value_node),
            line=self.line(node),
        )

    def _condition_expr(self, node):
        inner = [c for c in node.children if c.type not in ("(", ")")]
        return self._translate_expr(inner[0])

    def _translate_block_single(self, stmt_node) -> ir.Block:
        translated = self._translate_stmt(stmt_node)
        return ir.Block(statements=[translated] if translated else [], line=self.line(stmt_node))

    def _translate_if(self, node) -> ir.If:
        cond_node = node.child_by_field_name("condition")
        then_node = node.child_by_field_name("consequence")
        else_node = node.child_by_field_name("alternative")

        then_block = self._translate_block(then_node) if then_node.type == "block" \
            else self._translate_block_single(then_node)
        else_block = None
        if else_node is not None:
            else_block = self._translate_block(else_node) if else_node.type == "block" \
                else self._translate_block_single(else_node)

        return ir.If(
            cond=self._condition_expr(cond_node),
            then_block=then_block,
            else_block=else_block,
            line=self.line(node),
        )

    def _translate_while(self, node) -> ir.While:
        cond_node = node.child_by_field_name("condition")
        body_node = node.child_by_field_name("body")
        body = self._translate_block(body_node) if body_node.type == "block" \
            else self._translate_block_single(body_node)
        return ir.While(cond=self._condition_expr(cond_node), body=body, line=self.line(node))

    # -- expressions -----------------------------------------------------------

    def _translate_expr(self, node):
        if node.type == "identifier":
            return ir.Identifier(name=self.text(node), line=self.line(node))
        if node.type in ("decimal_integer_literal", "hex_integer_literal"):
            return ir.Literal(value=int(self.text(node)), type="int", line=self.line(node))
        if node.type == "decimal_floating_point_literal":
            return ir.Literal(value=float(self.text(node).rstrip("fF")), type="float", line=self.line(node))
        if node.type == "true":
            return ir.Literal(value=True, type="bool", line=self.line(node))
        if node.type == "false":
            return ir.Literal(value=False, type="bool", line=self.line(node))
        if node.type == "string_literal":
            content = "".join(c.text.decode() for c in node.children if c.type == "string_fragment")
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
            operand = node.child_by_field_name("operand") or node.children[-1]
            return ir.UnaryOp(op=self.text(op_node), operand=self._translate_expr(operand), line=self.line(node))
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            args_node = node.child_by_field_name("arguments")
            args = [self._translate_expr(c) for c in args_node.children if c.type not in ("(", ")", ",")]
            return ir.Call(name=self.text(name_node), args=args, line=self.line(node))
        if node.type == "parenthesized_expression":
            inner = [c for c in node.children if c.type not in ("(", ")")][0]
            return self._translate_expr(inner)
        self.unsupported(node, context="expression")
