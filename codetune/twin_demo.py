"""
CodeTune Digital Twin demo (Milestone 4).

    python twin_demo.py samples/twin_demo.c                       # compare strategies, recommend one
    python twin_demo.py samples/twin_demo.c --permutations        # also try all 24 pass orders (1 sweep)
    python twin_demo.py samples/twin_demo.c --order CP,SR         # "what if I apply CP before SR?"
    python twin_demo.py samples/twin_demo.c --whatif CF,CP,DCE    # "what if I apply exactly this sequence?"
    python twin_demo.py samples/twin_demo.c --function work       # pick a function (default: every function)
    python twin_demo.py samples/twin_demo.c --parallel            # run experiments on a thread pool
    python twin_demo.py samples/twin_demo.c --report reports      # write .md / .html / .json
    python twin_demo.py samples/twin_demo.c --watch 30            # re-simulate whenever the file is saved

Pass names: CP = constant_propagation, CF = constant_folding,
            SR = strength_reduction, DCE = dead_code_elimination.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codetune.digital_twin import DigitalTwin
from codetune.digital_twin.twin_report import build_twin_data, write_twin_report
from codetune.frontend.parser import parse_file
from codetune.ir.translators import get_translator


def _table(twin, experiments):
    print(f"{'Strategy':<30}{'valid':<7}{'predicted':>10}{'measured':>10}{'err%':>7}{'saving%':>9}{'size':>6}{'stack':>7}")
    for e in experiments:
        if e.metrics is None:
            print(f"{e.strategy.name:<30}{'NO':<7}  {e.error}")
            continue
        m = e.metrics
        print(f"{e.strategy.name:<30}{'yes' if e.valid else 'NO':<7}{m.predicted_cost:>10.1f}"
              f"{m.measured_cost if m.measured_cost is not None else float('nan'):>10.1f}"
              f"{m.prediction_error_pct if m.prediction_error_pct is not None else float('nan'):>7}"
              f"{e.saving_pct:>9}{m.code_size:>6}{m.memory_bytes:>7}")


def run_once(twin, args, report_dir=None):
    print(f"\n=== function {twin.func_name} ({twin.language}, revision {twin.revision}) ===")
    b = twin.baseline
    print(f"baseline: predicted cost {b.predicted_cost:.1f}, measured {b.measured_cost}, "
          f"size {b.code_size}, stack {b.memory_bytes} B\n")

    experiments = twin.explore(permutations=args.permutations, parallel=args.parallel)
    _table(twin, experiments)

    rec = twin.recommend(experiments)
    print(f"\nRecommendation: {rec.reason}")
    acc = twin.accuracy(experiments)
    print(f"Prediction accuracy: mean error {acc.mean_error_pct}% (target <= 15%), "
          f"{round(100 * acc.within_15_pct)}% of strategies within 15%, "
          f"{round(100 * acc.rank_agreement)}% of pairs ranked like reality, "
          f"winner matches measured: {acc.winner_matches}")

    what_ifs = []
    if args.order:
        a, b2 = [x.strip() for x in args.order.split(",")]
        res = twin.what_if_order(a, b2)
        print(f"\nWhat if {a} before {b2}?  {res['verdict']}")
        for key in ("a_then_b", "b_then_a"):
            e = res[key]
            print(f"   {e.strategy.name:<12} predicted {e.metrics.predicted_cost:.1f}  size {e.metrics.code_size}")
    if args.whatif:
        w = twin.what_if([x.strip() for x in args.whatif.split(",")])
        what_ifs.append(w)
        print(f"\n{w.question}\n   {w.answer}")

    twin.commit(rec.experiment)
    if report_dir:
        data = build_twin_data(twin, experiments, rec, acc, what_ifs)
        paths = write_twin_report(data, report_dir, basename=f"twin_{twin.func_name}")
        print("\nReport files written:")
        for fmt, p in paths.items():
            print(f"  {fmt:<5} {p}")


def main():
    ap = argparse.ArgumentParser(description="CodeTune Digital Twin")
    ap.add_argument("source_file")
    ap.add_argument("--function", help="only this function (default: all)")
    ap.add_argument("--permutations", action="store_true", help="also simulate all pass orders")
    ap.add_argument("--order", metavar="A,B", help="what if A is applied before B?")
    ap.add_argument("--whatif", metavar="A,B,C", help="what if exactly this pass sequence is applied?")
    ap.add_argument("--parallel", action="store_true", help="use the thread-pool sandbox")
    ap.add_argument("--report", metavar="DIR", help="write .md/.html/.json into DIR")
    ap.add_argument("--watch", type=int, metavar="SECONDS", help="keep watching the file and re-simulate on change")
    args = ap.parse_args()

    tree, src, lang = parse_file(args.source_file)
    program = get_translator(lang, src).translate_program(tree.root_node)
    names = [args.function] if args.function else [f.name for f in program.functions]

    twins = [DigitalTwin.from_file(args.source_file, name) for name in names]
    for t in twins:
        run_once(t, args, args.report)

    if args.watch:
        print(f"\nWatching {args.source_file} for {args.watch}s - save the file to re-simulate (Ctrl+C to stop)...")
        end = time.time() + args.watch
        try:
            while time.time() < end:
                for t in twins:
                    if t.sync():
                        print("\n[sync] source changed - twin rebuilt")
                        run_once(t, args, args.report)
                    elif t.last_error:
                        print(f"\n[sync] could not use the edited file: {t.last_error}")
                        t.last_error = None
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()