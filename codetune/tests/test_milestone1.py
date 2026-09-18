"""
Milestone 1 tests.

These check two things per language:
  1. tree-sitter parses the sample file without errors.
  2. The translator produces the *same shaped* Common IR regardless of
     source language -- 2 functions, matching param counts, matching
     statement counts in `clamp`. That equivalence is the actual point of
     Milestone 1: one IR, four languages.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from codetune.frontend.parser import parse_file
from codetune.ir.translators import get_translator
from codetune.ir import ir_nodes as ir

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "samples")

FILES = {
    "python": "sample.py",
    "c": "sample.c",
    "cpp": "sample.cpp",
    "java": "sample.java",
}


def _compile(language):
    path = os.path.join(SAMPLES_DIR, FILES[language])
    tree, source_bytes, detected_lang = parse_file(path)
    assert detected_lang == language
    assert not tree.root_node.has_error, f"{language}: tree-sitter reported a parse error"
    translator = get_translator(language, source_bytes)
    return translator.translate_program(tree.root_node)


def test_all_languages_parse_without_errors():
    for lang in FILES:
        program = _compile(lang)
        assert isinstance(program, ir.Program)
        assert program.source_language == lang


def test_all_languages_produce_two_functions():
    for lang in FILES:
        program = _compile(lang)
        names = [f.name for f in program.functions]
        assert names == ["square", "clamp"], f"{lang}: got {names}"


def test_all_languages_agree_on_clamp_shape():
    """The `clamp` function should translate to the same parameter count
    everywhere, and the same statement count among the typed languages
    (C/C++/Java each have one extra top-level statement vs. Python: the
    `int z;` declaration-without-initializer, which Python's grammar has
    no equivalent for since names don't need declaring before use)."""
    shapes = {}
    for lang in FILES:
        program = _compile(lang)
        clamp = next(f for f in program.functions if f.name == "clamp")
        shapes[lang] = (len(clamp.params), len(clamp.body.statements))

    assert shapes["python"] == (2, 6)
    for lang in ("c", "cpp", "java"):
        assert shapes[lang] == (2, 7), f"{lang} shape {shapes[lang]} != expected (2, 7)"


def test_square_body_is_a_single_return_of_binop():
    for lang in FILES:
        program = _compile(lang)
        square = next(f for f in program.functions if f.name == "square")
        assert len(square.body.statements) == 1
        ret = square.body.statements[0]
        assert isinstance(ret, ir.Return)
        assert isinstance(ret.value, ir.BinOp)
        assert ret.value.op == "*"


def test_if_else_translates_correctly_everywhere():
    for lang in FILES:
        program = _compile(lang)
        clamp = next(f for f in program.functions if f.name == "clamp")
        if_stmts = [s for s in clamp.body.statements if isinstance(s, ir.If)]
        assert len(if_stmts) == 1, f"{lang}: expected exactly one if-statement"
        if_node = if_stmts[0]
        assert isinstance(if_node.cond, ir.BinOp)
        assert if_node.cond.op == ">"
        assert if_node.else_block is not None
        assert len(if_node.then_block.statements) == 1
        assert len(if_node.else_block.statements) == 1


def test_while_translates_correctly_everywhere():
    for lang in FILES:
        program = _compile(lang)
        clamp = next(f for f in program.functions if f.name == "clamp")
        while_stmts = [s for s in clamp.body.statements if isinstance(s, ir.While)]
        assert len(while_stmts) == 1, f"{lang}: expected exactly one while-statement"
        assert while_stmts[0].cond.op == "<"


def test_unsupported_construct_raises_clear_error():
    """A construct outside the supported subset should fail loudly, not
    silently produce wrong IR."""
    tree, source_bytes = __import__("codetune.frontend.parser", fromlist=["parse_source"]).parse_source(
        "def f():\n    for i in range(10):\n        pass\n", "python"
    )
    translator = get_translator("python", source_bytes)
    try:
        translator.translate_program(tree.root_node)
        assert False, "expected NotImplementedError for unsupported 'for' loop"
    except NotImplementedError as e:
        assert "Unsupported construct" in str(e)
