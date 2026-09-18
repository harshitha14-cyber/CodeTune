"""
Milestone 1 demo.

Usage:
    python3 demo.py samples/sample.py
    python3 demo.py samples/sample.c
    python3 demo.py samples/sample.cpp
    python3 demo.py samples/sample.java

For each file this:
  1. Detects the language from the extension
  2. Parses it with tree-sitter into a real language-specific AST
  3. Translates that AST into CodeTune's Common IR
  4. Pretty-prints the Common IR back as readable pseudocode

Step 4 working correctly (and looking equivalent across all four sample
files, which all implement the same tiny program) is the milestone's proof
that one common representation really does work across languages.
"""

import sys

from codetune.frontend.parser import parse_file
from codetune.ir.translators import get_translator
from codetune.ir.ir_printer import print_program


def compile_to_ir(path: str):
    tree, source_bytes, language = parse_file(path)
    translator = get_translator(language, source_bytes)
    program = translator.translate_program(tree.root_node)
    return program


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 demo.py <source_file>")
        sys.exit(1)

    path = sys.argv[1]
    program = compile_to_ir(path)

    print(f"--- Parsed {path} -> Common IR ---\n")
    print(print_program(program))


if __name__ == "__main__":
    main()
