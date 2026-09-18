"""
Static feature extraction over the Common IR.

This corresponds to Phase 2 / Section 3.1 of the project report ("Static
Feature Extraction"): loop count/depth, branch count/depth, operation
counts, constant count, call count, variable count, and expression
nesting depth (a proxy for "variable-dependency depth").

Because this operates on the Common IR from Milestone 1 rather than on
each language's own AST, it is written ONCE and works for Python, C, C++,
and Java automatically -- this is the payoff of building the shared IR
first.
"""

from dataclasses import dataclass, asdict
from typing import Dict

from ..ir import ir_nodes as ir

ARITHMETIC_OPS = {"+", "-", "*", "/", "%"}
COMPARISON_OPS = {"<", ">", "<=", ">=", "==", "!="}
LOGICAL_OPS = {"&&", "||", "!"}


@dataclass
class FunctionFeatures:
    function_name: str
    loop_count: int = 0
    max_loop_nesting_depth: int = 0
    branch_count: int = 0
    max_branch_nesting_depth: int = 0
    arithmetic_op_count: int = 0
    comparison_op_count: int = 0
    logical_op_count: int = 0
    constant_count: int = 0
    function_call_count: int = 0
    variable_count: int = 0
    max_expression_depth: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


class FeatureExtractor:
    """Walks one FuncDecl's Common IR and accumulates structural features."""

    def extract(self, func: "ir.FuncDecl") -> FunctionFeatures:
        self.features = FunctionFeatures(function_name=func.name)
        self._variable_names = {p.name for p in func.params}
        self._loop_depth = 0
        self._branch_depth = 0
        self._visit_block(func.body)
        self.features.variable_count = len(self._variable_names)
        return self.features

    # -- statements ----------------------------------------------------------

    def _visit_block(self, block: "ir.Block"):
        for stmt in block.statements:
            self._visit_stmt(stmt)

    def _visit_stmt(self, node):
        if isinstance(node, ir.VarDecl):
            self._variable_names.add(node.name)
            if node.init is not None:
                self._visit_expr(node.init)

        elif isinstance(node, ir.Assign):
            self._variable_names.add(node.target)
            self._visit_expr(node.value)

        elif isinstance(node, ir.ExprStmt):
            self._visit_expr(node.expr)

        elif isinstance(node, ir.Return):
            if node.value is not None:
                self._visit_expr(node.value)

        elif isinstance(node, ir.If):
            self.features.branch_count += 1
            self._branch_depth += 1
            self.features.max_branch_nesting_depth = max(
                self.features.max_branch_nesting_depth, self._branch_depth
            )
            self._visit_expr(node.cond)
            self._visit_block(node.then_block)
            if node.else_block is not None:
                self._visit_block(node.else_block)
            self._branch_depth -= 1

        elif isinstance(node, ir.While):
            self.features.loop_count += 1
            self._loop_depth += 1
            self.features.max_loop_nesting_depth = max(
                self.features.max_loop_nesting_depth, self._loop_depth
            )
            self._visit_expr(node.cond)
            self._visit_block(node.body)
            self._loop_depth -= 1

    # -- expressions -----------------------------------------------------------

    def _visit_expr(self, node, depth: int = 1):
        self.features.max_expression_depth = max(self.features.max_expression_depth, depth)

        if isinstance(node, ir.Literal):
            self.features.constant_count += 1

        elif isinstance(node, ir.Identifier):
            pass

        elif isinstance(node, ir.BinOp):
            if node.op in ARITHMETIC_OPS:
                self.features.arithmetic_op_count += 1
            elif node.op in COMPARISON_OPS:
                self.features.comparison_op_count += 1
            elif node.op in LOGICAL_OPS:
                self.features.logical_op_count += 1
            self._visit_expr(node.left, depth + 1)
            self._visit_expr(node.right, depth + 1)

        elif isinstance(node, ir.UnaryOp):
            if node.op in LOGICAL_OPS:
                self.features.logical_op_count += 1
            self._visit_expr(node.operand, depth + 1)

        elif isinstance(node, ir.Call):
            self.features.function_call_count += 1
            for arg in node.args:
                self._visit_expr(arg, depth + 1)


def extract_program_features(program: "ir.Program") -> Dict[str, FunctionFeatures]:
    """Extract features for every function in a Common IR Program.
    Returns {function_name: FunctionFeatures}."""
    extractor = FeatureExtractor()
    return {func.name: extractor.extract(func) for func in program.functions}