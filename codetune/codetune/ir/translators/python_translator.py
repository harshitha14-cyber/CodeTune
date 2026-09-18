from .base import TranslatorBase
from .. import ir_nodes as ir


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

        params = []
        for c in params_node.children:
            if c.type == "identifier":
                params.append(ir.Param(name=self.text(c), param_type="var", line=self.line(c)))

        return ir.FuncDecl(
            name=self.text(name_node),
            params=params,
            return_type="var",   # Python is untyped without annotations
            body=self._translate_block(body_node),
            line=self.line(node),
        )

    # -- statements ------------------------------------------------------

    def _translate_block(self, node) -> ir.Block:
        block = ir.Block(statements=[], line=self.line(node))
        for stmt in node.children:
            translated = self._translate_stmt(stmt)
            if translated is not None:
                block.statements.append(translated)
        return block

    def _translate_stmt(self, node):
        if node.type == "expression_statement":
            inner = node.children[0]
            if inner.type == "assignment":
                return self._translate_assignment(inner)
            return ir.ExprStmt(expr=self._translate_expr(inner), line=self.line(node))
        if node.type == "if_statement":
            return self._translate_if(node)
        if node.type == "while_statement":
            return self._translate_while(node)
        if node.type == "return_statement":
            value_node = node.child_by_field_name("value")
            # tree-sitter-python doesn't expose 'value' as a field name here;
            # fall back to the last non-'return' child if present.
            if value_node is None:
                candidates = [c for c in node.children if c.type not in ("return", ";")]
                value_node = candidates[0] if candidates else None
            value = self._translate_expr(value_node) if value_node is not None else None
            return ir.Return(value=value, line=self.line(node))
        if node.type in ("comment",):
            return None
        self.unsupported(node, context="statement")

    def _translate_assignment(self, node) -> ir.Node:
        target_node = node.children[0]
        value_node = node.children[-1]
        if target_node.type != "identifier":
            self.unsupported(target_node, context="assignment target")
        # First assignment to a name reads like a declaration in our IR;
        # CodeTune doesn't do full def-use analysis yet, so every assignment
        # is represented uniformly as Assign (VarDecl is reserved for
        # languages with explicit declarations, e.g. C/C++/Java `int x = ..`).
        return ir.Assign(
            target=self.text(target_node),
            value=self._translate_expr(value_node),
            line=self.line(node),
        )

    def _translate_if(self, node) -> ir.If:
        cond_node = node.child_by_field_name("condition")
        then_node = node.child_by_field_name("consequence")
        else_clause = node.child_by_field_name("alternative")

        else_block = None
        if else_clause is not None:
            # else_clause node wraps its own 'body' field
            inner_body = else_clause.child_by_field_name("body")
            else_block = self._translate_block(inner_body)

        return ir.If(
            cond=self._translate_expr(cond_node),
            then_block=self._translate_block(then_node),
            else_block=else_block,
            line=self.line(node),
        )

    def _translate_while(self, node) -> ir.While:
        cond_node = node.child_by_field_name("condition")
        body_node = node.child_by_field_name("body")
        return ir.While(
            cond=self._translate_expr(cond_node),
            body=self._translate_block(body_node),
            line=self.line(node),
        )

    # -- expressions -------------------------------------------------------

    def _translate_expr(self, node):
        if node.type == "identifier":
            return ir.Identifier(name=self.text(node), line=self.line(node))
        if node.type == "integer":
            return ir.Literal(value=int(self.text(node)), type="int", line=self.line(node))
        if node.type == "float":
            return ir.Literal(value=float(self.text(node)), type="float", line=self.line(node))
        if node.type == "true":
            return ir.Literal(value=True, type="bool", line=self.line(node))
        if node.type == "false":
            return ir.Literal(value=False, type="bool", line=self.line(node))
        if node.type == "string":
            content = "".join(
                self.text(c) for c in node.children if c.type == "string_content"
            )
            return ir.Literal(value=content, type="string", line=self.line(node))
        if node.type in ("binary_operator", "comparison_operator", "boolean_operator"):
            left = node.child_by_field_name("left") or node.children[0]
            right = node.child_by_field_name("right") or node.children[-1]
            op_node = node.child_by_field_name("operator")
            if op_node is None:
                op_node = [c for c in node.children if c not in (left, right)][0]
            return ir.BinOp(
                op=self.normalize_op(self.text(op_node)),
                left=self._translate_expr(left),
                right=self._translate_expr(right),
                line=self.line(node),
            )
        if node.type == "not_operator":
            operand = node.child_by_field_name("argument") or node.children[-1]
            return ir.UnaryOp(op="!", operand=self._translate_expr(operand), line=self.line(node))
        if node.type == "unary_operator":
            op_node = node.children[0]
            operand = node.child_by_field_name("argument") or node.children[-1]
            return ir.UnaryOp(
                op=self.text(op_node),
                operand=self._translate_expr(operand),
                line=self.line(node),
            )
        if node.type == "call":
            func_node = node.child_by_field_name("function")
            args_node = node.child_by_field_name("arguments")
            args = [
                self._translate_expr(c)
                for c in args_node.children
                if c.type not in ("(", ")", ",")
            ]
            return ir.Call(name=self.text(func_node), args=args, line=self.line(node))
        if node.type == "parenthesized_expression":
            inner = [c for c in node.children if c.type not in ("(", ")")][0]
            return self._translate_expr(inner)
        self.unsupported(node, context="expression")
