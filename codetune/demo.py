"""
CodeTune demo (Milestones 1 + 2).

Usage:
    python3 demo.py samples/sample.py                      # M1: source -> Common IR
    python3 demo.py samples/optimize_demo.c --features     # M2: static features per function
    python3 demo.py samples/optimize_demo.c --select       # M2: which passes, with confidence
    python3 demo.py samples/optimize_demo.c --optimize     # M2: select + run + before/after report
    python3 demo.py samples/optimize_demo.c --optimize --passes constant_folding,dead_code_elimination

Works for .py / .c / .cpp / .java alike -- everything after the front-end only
sees the Common IR.
"""

import argparse
import os
import sys

# Make `import codetune...` work no matter where the script is launched from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codetune.analysis.feature_extractor import extract_program_features
from codetune.analysis.pass_selector import RuleBasedPassSelector
from codetune.frontend.parser import parse_file
from codetune.ir.ir_printer import print_program
from codetune.ir.translators import get_translator
from codetune.optimizer.pass_manager import optimize_program


def compile_to_ir(path: str):
    tree, source_bytes, language = parse_file(path)
    translator = get_translator(language, source_bytes)
    return translator.translate_program(tree.root_node)


def main():
    ap = argparse.ArgumentParser(description="CodeTune demo")
    ap.add_argument("source_file")
    ap.add_argument("--features", action="store_true", help="print static features")
    ap.add_argument("--select", action="store_true", help="print pass recommendations + confidence")
    ap.add_argument("--optimize", action="store_true", help="run the optimizer and print a report")
    ap.add_argument("--passes", help="comma-separated passes to force (skips the selector)")
    args = ap.parse_args()

    program = compile_to_ir(args.source_file)

    if not (args.features or args.select or args.optimize):
        print(f"--- Parsed {args.source_file} -> Common IR ---\n")
        print(print_program(program))
        return

    if args.features:
        print(f"--- Static features: {args.source_file} ---")
        for name, feats in extract_program_features(program).items():
            print(f"\n{name}:")
            for k, v in feats.to_dict().items():
                if k != "function_name":
                    print(f"  {k:<28} {v}")

    if args.select:
        print(f"\n--- Pass selection: {args.source_file} ---")
        selector = RuleBasedPassSelector()
        for func in program.functions:
            print(f"\n{func.name}:")
            for r in selector.select(func, program.source_language):
                mark = "RUN " if r.selected else "skip"
                print(f"  [{mark}] {r.pass_name:<24} confidence {r.confidence:.2f}  - {r.reason}")

    if args.optimize:
        passes = args.passes.split(",") if args.passes else None
        report = optimize_program(program, passes=passes)
        print(f"\n--- Optimization report: {args.source_file} ---\n")
        print(report.to_text())


if __name__ == "__main__":
    main()
