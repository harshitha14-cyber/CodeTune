"""
Shared base class for language -> Common IR translators.

Each concrete translator (Python, C, C++, Java) walks that language's own
tree-sitter node types and builds Common IR nodes (see ir/ir_nodes.py).
The node type NAMES differ per grammar, so each translator has its own
dispatch table -- but they all produce the exact same IR shape, which is
what lets one optimizer/feature-extractor/Copilot work across languages.

Milestone 6 hardening (real user code):
  * compound assignment (x += e) and ++/-- statements become  x = x op e
  * `for` loops are desugared into init + while (+ update at the end of the body)
  * anything the IR cannot represent exactly is rejected with a clear message
    instead of being silently mistranslated.
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

COMPOUND_ASSIGN = {
    "+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%", "<<=": "<<", ">>=": ">>",
    "&=": "&", "|=": "|", "^=": "^", "//=": "//", "**=": "**",
}

C_FAMILY_BINARY_OPS = {"+", "-", "*", "/", "%", "<<", ">>", "&", "|", "^", "&&", "||",
                       "==", "!=", "<", ">", "<=", ">="}
PYTHON_BINARY_OPS = {"+", "-", "*", "/", "//", "%", "**", "<<", ">>", "&", "|", "^"}

# Friendly advice for constructs the IR does not model.
HINTS = {
    "break_statement": "rewrite the loop with a condition (e.g. a flag variable) instead of break",
    "continue_statement": "rewrite with an if around the rest of the loop body instead of continue",
    "do_statement": "rewrite do-while as a while loop",
    "switch_statement": "rewrite switch as if / else-if",
    "switch_expression": "rewrite switch as if / else-if",
    "enhanced_for_statement": "use a classic for/while loop with an index",
    "conditional_expression": "rewrite the ternary a ? b : c as an if / else statement",
    "ternary_expression": "rewrite the ternary as an if / else statement",
    "update_expression": "use i++ / i-- only as a statement (or write i = i + 1)",
    "subscript_expression": "arrays / pointers are not supported yet",
    "array_access": "arrays are not supported yet",
    "pointer_expression": "pointers are not supported yet",
    "cast_expression": "casts are not supported yet",
    "char_literal": "character literals are not supported yet",
    "character_literal": "character literals are not supported yet",
    "for_statement": "this form of for loop is not supported; use a while loop",
    "comparison_operator": "this comparison operator is not supported",
    "none": "None is not supported yet",
    "list": "lists are not supported yet",
    "list_comprehension": "comprehensions are not supported yet",
    "tuple": "tuples are not supported yet",
    "lambda": "lambdas are not supported yet",
    "import_statement": "put imports outside the function",
    "global_statement": "global statements are not supported",
    "try_statement": "try / except is not supported yet",
    "with_statement": "with is not supported yet",
    "assert_statement": "assert is not supported yet",
}


def parse_int_literal(text: str, language: str) -> int:
    """C/C++/Java/Python integer literal -> int (hex, binary, octal, digit separators)."""
    t = text.replace("_", "").replace("'", "")
    if language != "python":
        t = t.rstrip("uU")
    if language == "python":
        return int(t, 0)
    low = t.lower()
    if low.startswith(("0x", "0b")):
        return int(t, 0)
    if len(t) > 1 and t[0] == "0" and t.isdigit():
        return int(t, 8)
    return int(t)


class TranslatorBase:
    source_language = "unknown"

    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes
        self._reset_function_state()

    # -- per-function state (loop-variable renaming, fresh temp names) --------------

    def _reset_function_state(self):
        self._renames = [{}]
        self._reserved = set()          # every identifier that occurs in the current function
        self._plain_decls = set()       # names declared outside for-initialisers, incl. params
        self._for_names_used = set()    # loop variables already claimed by an earlier for loop
        self._fresh = 0

    def rename(self, name: str) -> str:
        for m in reversed(self._renames):
            if name in m:
                return m[name]
        return name

    def fresh_name(self, base: str) -> str:
        n = 1
        while f"{base}_{n}" in self._reserved:
            n += 1
        name = f"{base}_{n}"
        self._reserved.add(name)
        return name

    def loop_var_name(self, name: str) -> str:
        """A for-loop variable keeps its name only if nothing else in the function uses
        that name as a declaration; otherwise it gets a fresh one (exact: renamed only
        inside the loop, which is where a C/Java loop variable lives)."""
        if name in self._plain_decls or name in self._for_names_used:
            return self.fresh_name(name)
        self._for_names_used.add(name)
        return name

    # -- helpers ------------------------------------------------------------------------

    def text(self, node) -> str:
        return self.source_bytes[node.start_byte:node.end_byte].decode("utf-8")

    def line(self, node) -> int:
        return node.start_point[0] + 1

    def normalize_op(self, op_text: str) -> str:
        return OP_NORMALIZE.get(op_text, op_text)

    def collect_identifiers(self, node):
        out, stack = set(), [node]
        while stack:
            n = stack.pop()
            if n.type == "identifier":
                out.add(self.text(n))
            stack.extend(n.children)
        return out

    def translate_program(self, root_node) -> "ir.Program":
        raise NotImplementedError

    def unsupported(self, node, context: str = ""):
        """Raised when the translator hits a construct outside the supported
        subset (see ir_nodes.py docstring). Kept as a clear, catchable error
        rather than silently producing wrong IR."""
        hint = HINTS.get(node.type)
        raise NotImplementedError(
            f"[{self.source_language}] Unsupported construct '{node.type}' "
            f"at line {self.line(node)}{(' in ' + context) if context else ''}. "
            f"Text: {self.text(node)[:60]!r}" + (f" -- {hint}" if hint else "")
        )

    def stmt_list(self, translated):
        """Normalise what a statement translator returns (node, list or None) to a list."""
        if translated is None:
            return []
        return list(translated) if isinstance(translated, (list, tuple)) else [translated]