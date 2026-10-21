"""Run from the codetune folder:  python check_install.py
Reports files that are missing or still the OLD version."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# (path, text that must appear in the file)
EXPECTED = [
    ("__init__.py", None),
    ("ir/ir_nodes.py", None),
    ("ir/ir_printer.py", "print_expr = _print_expr"),
    ("ir/source_printer.py", "def function_to_source"),
    ("ir/translators/base.py", "def parse_int_literal"),
    ("ir/translators/c_translator.py", "def _translate_for"),
    ("ir/translators/java_translator.py", "def _translate_for"),
    ("ir/translators/python_translator.py", "def _used_after"),
    ("frontend/detect.py", "def detect_language"),
    ("ir/semantics.py", "def binop"),
    ("ir/ir_utils.py", "trusted as a contract"),
    ("ir/interpreter.py", "IO_BUILTINS"),
    ("analysis/feature_extractor.py", "constant_assignment_count"),
    ("optimizer/__init__.py", None),
    ("optimizer/base.py", "class OptimizationPass"),
    ("optimizer/constant_folding.py", "class ConstantFolding"),
    ("optimizer/constant_propagation.py", "class ConstantPropagation"),
    ("optimizer/strength_reduction.py", "class StrengthReduction"),
    ("optimizer/dead_code_elimination.py", "class DeadCodeElimination"),
    ("optimizer/registry.py", "PASS_ORDER"),
    ("optimizer/pass_manager.py", "validate"),
    ("validation/__init__.py", None),
    ("validation/input_generator.py", "annotated = language"),
    ("validation/differential_tester.py", "tuple(interp.output)"),
    ("reporting/__init__.py", None),
    ("reporting/report_generator.py", "def write_report"),
    ("digital_twin/__init__.py", None),
    ("digital_twin/cost_model.py", "class StaticCostEstimator"),
    ("digital_twin/strategy.py", "def run_strategy"),
    ("digital_twin/sandbox.py", "class Sandbox"),
    ("digital_twin/twin.py", "class DigitalTwin"),
    ("digital_twin/twin_report.py", "def write_twin_report"),
    ("analysis/pass_selector.py", "Digital Twin in Milestone 4"),
    ("ml/__init__.py", None),
    ("ml/decision_tree.py", "class RandomForest"),
    ("ml/corpus.py", "def store"),
    ("ml/ml_selector.py", "class MLPassSelector"),
    ("copilot/__init__.py", None),
    ("copilot/knowledge.py", "loop_invariant_hoisting"),
    ("copilot/refactor.py", "def hoist_loop_invariants"),
    ("copilot/copilot.py", "def optimized_source"),
    ("copilot/llm.py", "class GeminiClient"),
    ("copilot/scope.py", "def in_scope"),
    ("dashboard/__init__.py", None),
    ("dashboard/page.py", "Analyze &amp; optimize"),
    ("dashboard/server.py", "/api/llm"),
    ("train_selector.py", "File not found"),
    ("copilot_demo.py", "--stdin"),
    ("run_dashboard.py", "GeminiClient"),
    ("samples/twin_demo.c", None),
    ("samples/twin_demo.cpp", None),
    ("samples/twin_demo.py", None),
    ("samples/twin_demo.java", None),
    ("samples/optimize_demo.c", None),
    ("samples/optimize_demo.py", None),
    ("samples/optimize_demo.cpp", None),
    ("samples/optimize_demo.java", None),
    ("tests/conftest.py", "PRISTINE_SAMPLES"),
    ("tests/test_milestone2.py", None),
    ("tests/test_milestone3.py", None),
    ("tests/test_milestone4.py", 'SAMPLES = os.path.join(HERE, "data")'),
    ("tests/test_milestone5.py", "ONLY the facts"),
    ("tests/test_milestone6.py", None),
    ("twin_demo.py", "--watch"),
    ("demo.py", "--no-validate"),
]

bad = 0
for rel, needle in EXPECTED:
    path = os.path.join(HERE, *rel.split("/"))
    if not os.path.exists(path):
        print(f"MISSING  {rel}")
        bad += 1
    elif needle:
        with open(path, encoding="utf-8") as fh:
            if needle not in fh.read():
                print(f"OLD      {rel}   (replace with the latest version)")
                bad += 1
print("All files present and up to date." if bad == 0 else f"\n{bad} problem(s) found.")