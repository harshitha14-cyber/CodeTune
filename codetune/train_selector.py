"""
Train and evaluate the ML pass selector (Milestone 5).

    python train_selector.py                    # train on 1200 generated programs, report accuracy, save model
    python train_selector.py --programs 3000 --seed 7
    python train_selector.py --rules            # also print the readable decision rules per pass
    python train_selector.py --compare samples/twin_demo.c    # ML vs rule-based choices on a file
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codetune.analysis.pass_selector import RuleBasedPassSelector
from codetune.frontend.parser import parse_file
from codetune.ir.translators import get_translator
from codetune.ml.ml_selector import DEFAULT_MODEL_PATH, MLPassSelector
from codetune.optimizer.registry import PASS_ORDER


def main():
    ap = argparse.ArgumentParser(description="Train the CodeTune ML pass selector")
    ap.add_argument("--programs", type=int, default=1200, help="size of the generated training corpus")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trees", type=int, default=15)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--out", default=DEFAULT_MODEL_PATH, help="where to save the model (JSON)")
    ap.add_argument("--rules", action="store_true", help="print the readable decision tree of every pass")
    ap.add_argument("--compare", metavar="FILE", help="compare ML and rule-based selection on a source file")
    args = ap.parse_args()

    t0 = time.time()
    sel = MLPassSelector.train(n_programs=args.programs, seed=args.seed, n_trees=args.trees, max_depth=args.depth)
    print(f"Trained in {time.time() - t0:.1f}s\n")
    print(sel.eval_report.to_text())
    sel.save(args.out)
    print(f"\nModel saved to {args.out}")

    if args.rules:
        for p in PASS_ORDER:
            print(f"\n--- decision rules for {p} ---")
            print(sel.explain(p))

    if args.compare:
        if not os.path.exists(args.compare):
            sys.exit(f"\nFile not found: {args.compare}\n(check the path - sample files live in the 'samples' folder)")        
        tree, src, lang = parse_file(args.compare)
        program = get_translator(lang, src).translate_program(tree.root_node)
        rule = RuleBasedPassSelector()
        for func in program.functions:
            print(f"\n=== {func.name} ({lang}) ===")
            print(f"{'pass':<24}{'rule conf':>10}{'ML conf':>9}   decision")
            for a, b in zip(rule.select(func, lang), sel.select(func, lang)):
                same = "agree" if a.selected == b.selected else "DIFFER"
                print(f"{a.pass_name:<24}{a.confidence:>10.2f}{b.confidence:>9.2f}   "
                      f"rule={'run' if a.selected else 'skip'}  ml={'run' if b.selected else 'skip'}  {same}")


if __name__ == "__main__":
    main()