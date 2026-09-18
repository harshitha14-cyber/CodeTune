"""
CodeTune Multi-Language Front-End
==================================
Instead of hand-writing a lexer/parser for one toy language, CodeTune uses
tree-sitter's production-grade grammars to get a real, accurate AST for
Python, C, C++, and Java source code. This is what makes "optimize any
language" realistic: we don't reinvent parsing, we reuse battle-tested
grammars and focus CodeTune's own work on the optimization side.

Usage:
    from codetune.frontend.parser import parse_source, detect_language

    lang = detect_language("sample.py")
    tree, src_bytes = parse_source(code_string, lang)
"""

from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
import tree_sitter_java as tsjava


SUPPORTED_LANGUAGES = ("python", "c", "cpp", "java")

_EXTENSION_MAP = {
    ".py": "python",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".java": "java",
}

_LANGUAGE_OBJECTS = {
    "python": Language(tspython.language()),
    "c": Language(tsc.language()),
    "cpp": Language(tscpp.language()),
    "java": Language(tsjava.language()),
}

_PARSER_CACHE = {}


def detect_language(filename: str) -> str:
    """Guess the language from a file extension. Raises ValueError if unknown."""
    for ext, lang in _EXTENSION_MAP.items():
        if filename.endswith(ext):
            return lang
    raise ValueError(
        f"Could not detect a supported language for '{filename}'. "
        f"Supported languages: {SUPPORTED_LANGUAGES}"
    )


def _get_parser(language: str) -> Parser:
    if language not in _LANGUAGE_OBJECTS:
        raise ValueError(f"Unsupported language '{language}'. Supported: {SUPPORTED_LANGUAGES}")
    if language not in _PARSER_CACHE:
        _PARSER_CACHE[language] = Parser(_LANGUAGE_OBJECTS[language])
    return _PARSER_CACHE[language]


def parse_source(source_code: str, language: str):
    """
    Parse `source_code` (a str) written in `language`.
    Returns (tree, source_bytes) -- source_bytes is needed because tree-sitter
    node positions are byte offsets, not string indices.
    """
    parser = _get_parser(language)
    source_bytes = source_code.encode("utf-8")
    tree = parser.parse(source_bytes)
    return tree, source_bytes


def parse_file(path: str):
    """Convenience: detect language from extension and parse a file on disk."""
    language = detect_language(path)
    with open(path, "r", encoding="utf-8") as f:
        source_code = f.read()
    tree, source_bytes = parse_source(source_code, language)
    return tree, source_bytes, language


def node_text(node, source_bytes: bytes) -> str:
    """Get the original source text a tree-sitter node spans."""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8")
