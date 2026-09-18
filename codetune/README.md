# CodeTune — Milestone 1

**Multi-language front-end + Common IR.**

## What this milestone does

Instead of hand-writing a lexer/parser for a single toy language, CodeTune
uses [tree-sitter](https://tree-sitter.github.io/tree-sitter/)'s
production-grade grammars to parse **real Python, C, C++, and Java** source
code into accurate ASTs. Each language then gets its own small translator
that converts that AST into **one shared Common IR** (`codetune/ir/ir_nodes.py`).

Every later CodeTune module — feature extraction, optimization passes, the
ML pass-selector, the Digital Twin, and the Copilot — only ever needs to
understand this one IR. That's what makes "optimize code in any of these
languages" tractable: the hard, language-specific work (parsing) is done
once per language at the front door, and everything else is written once.

```
source (.py / .c / .cpp / .java)
        │  tree-sitter
        ▼
  language-specific AST
        │  per-language translator
        ▼
     Common IR   <-- everything downstream only ever sees this
        │  ir_printer
        ▼
  readable pseudocode (before/after comparisons later)
```

## Supported subset (deliberately small, same across all 4 languages)

- function declarations with parameters
- variable declaration + assignment
- arithmetic / comparison / logical binary expressions, unary `-` / `!`
- literals: int, float, bool, string
- `if` / `else`
- `while`
- `return`
- function calls

Anything outside this subset raises a clear `NotImplementedError` naming the
construct and line number, rather than silently producing wrong IR. Growing
the subset (for loops, arrays, more operators, etc.) is expected in later
milestones and only touches the per-language translators + `ir_nodes.py`.

## Project layout

```
codetune/
  frontend/
    parser.py            # tree-sitter wrapper: detect_language, parse_file
  ir/
    ir_nodes.py           # the Common IR node types
    ir_printer.py          # Common IR -> readable pseudocode
    translators/
      base.py             # shared helpers (text, line, op normalization)
      python_translator.py
      c_translator.py
      cpp_translator.py    # subclasses CTranslator (grammars overlap heavily)
      java_translator.py
samples/                  # the same tiny program in all 4 languages
tests/test_milestone1.py  # proves all 4 languages -> the same IR shape
demo.py                   # CLI: parse a file, print its Common IR
```

## Running it

```bash
pip install -r requirements.txt

python3 demo.py samples/sample.py
python3 demo.py samples/sample.c
python3 demo.py samples/sample.cpp
python3 demo.py samples/sample.java

python3 -m pytest tests/ -v
```

All four sample files implement the same tiny program (`square` +
`clamp`, using if/else, while, and a function call) precisely so you can
diff their printed IR by eye and see they produce the same shape.

## Known limitations (by design, for now)

- Only one function-call expression form supported per language (no method
  chaining, no `this.foo()`, no operator overloading, etc.)
- No arrays, structs/classes-as-data, or for-loops yet
- Java: only a single top-level class with methods is handled
- No type-checking — types are captured as text (e.g. `"int"`) for later
  feature extraction, not validated

These are intentional scope cuts for Milestone 1, not bugs — extending the
supported subset is straightforward from here and can be prioritized based
on what your test corpus (Milestone 2) actually needs.
