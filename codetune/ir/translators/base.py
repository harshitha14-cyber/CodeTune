"""
Shared base class for language -> Common IR translators.

Each concrete translator (Python, C, C++, Java) walks that language's own
tree-sitter node types and builds Common IR nodes (see ir/ir_nodes.py).
The node type NAMES differ per grammar, so each translator has its own
dispatch table -- but they all produce the exact same IR shape, which is
what lets one optimizer/feature-extractor/Copilot work across languages.
"""

from .. import ir_nodes as ir


# Operators are spelled differently across languages (Python "and"/"or" vs
# C-family "&&"/"||"). Normalize them all to C-style symbols in the IR so
# downstream code (optimizer, feature extraction) has one op vocabulary.
OP_NORMALIZE = {
    "and": "&&",
    "or": "||",
    "not": "!",
}


class TranslatorBase:
    source_language = "unknown"

    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes

    def text(self, node) -> str:
        return self.source_bytes[node.start_byte:node.end_byte].decode("utf-8")

    def line(self, node) -> int:
        return node.start_point[0] + 1

    def normalize_op(self, op_text: str) -> str:
        return OP_NORMALIZE.get(op_text, op_text)

    def translate_program(self, root_node) -> "ir.Program":
        raise NotImplementedError

    def unsupported(self, node, context: str = ""):
        """Raised when the translator hits a construct outside the supported
        subset (see ir_nodes.py docstring). Kept as a clear, catchable error
        rather than silently producing wrong IR."""
        raise NotImplementedError(
            f"[{self.source_language}] Unsupported construct '{node.type}' "
            f"at line {self.line(node)}{(' in ' + context) if context else ''}. "
            f"Text: {self.text(node)[:60]!r}"
        )
