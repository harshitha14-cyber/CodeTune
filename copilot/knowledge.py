"""
Learning-mode content for the Copilot: every optimization and key concept is
explained at three levels (beginner / intermediate / advanced), each with a small
example, so the same question gets an answer that fits the person asking.
"""

LEVELS = ("beginner", "intermediate", "advanced")

# topic -> {"aliases": [...], level -> text, "example": (before, after)}
TOPICS = {
    "constant_folding": {
        "title": "Constant folding",
        "aliases": ["constant folding", "folding", "fold", "cf"],
        "beginner": "If a calculation only uses fixed numbers, like 2 * 3, the compiler does the maths itself "
                    "while compiling, so the finished program does not repeat it every time it runs. "
                    "It is like writing 6 on a form instead of '2 times 3'.",
        "intermediate": "The compiler evaluates expressions whose operands are all literals at compile time and "
                        "replaces them by the result. It must use the target language's own rules (C integer "
                        "division truncates, Python's / gives a float) and must not fold when the result is "
                        "uncertain, e.g. division by zero or 32-bit overflow.",
        "advanced": "A local, bottom-up rewrite over the expression tree using the language's operational "
                    "semantics for each operator. It is sound only if the abstract evaluation equals the runtime "
                    "evaluation: hence per-language integer division and modulo semantics, 32-bit wrap/overflow "
                    "checks, and no folding of operations that may trap. Short-circuit operators fold with a "
                    "literal left operand without evaluating the right one.",
        "example": ("x = 2 * 3 + 1;", "x = 7;"),
    },
    "constant_propagation": {
        "title": "Constant propagation",
        "aliases": ["constant propagation", "propagation", "propagate", "cp"],
        "beginner": "If a variable is set to a fixed number and never changes afterwards, the compiler swaps every "
                    "use of that variable for the number. That often lets other optimizations kick in.",
        "intermediate": "A forward data-flow analysis tracks which variables hold a known constant at each point. "
                        "At an if/else the facts from both branches are merged (only agreeing facts survive); for a "
                        "loop, any variable assigned inside the loop is forgotten before the loop starts.",
        "advanced": "Forward must-analysis over the constant lattice (undef < constant < not-constant) on structured "
                    "control flow. The join at a merge keeps a fact only if both paths agree; loops are handled "
                    "conservatively by killing every variable defined in the body at the head (a one-step fixpoint). "
                    "Only provably local variables are tracked, and the constant is coerced to the declared type "
                    "(double d = 3 records 3.0).",
        "example": ("a = 4;\nb = a * 2;", "a = 4;\nb = 4 * 2;   (folding then gives 8)"),
    },
    "strength_reduction": {
        "title": "Strength reduction",
        "aliases": ["strength reduction", "strength", "reduction", "sr", "shift"],
        "beginner": "Some operations are slower than others. Multiplying by 8 can be replaced by a 'shift', which "
                    "the processor does much faster, as long as the compiler is sure the number is a whole number.",
        "intermediate": "Replace an expensive operator by a cheaper equivalent: x*2^k becomes x<<k for integers, "
                        "x*2 becomes x+x, and algebraic identities such as x*1 and x+0 are removed. Division and "
                        "modulo by a power of two are NOT rewritten, because for negative numbers / rounds toward "
                        "zero but >> rounds down.",
        "advanced": "Type-directed peephole rewriting. A shift is only valid when the operand is provably an integer "
                    "(declared type, or for Python a flow-insensitive inference that must hold for every "
                    "assignment). x+x is valid for any numeric or sequence type, but only when x has no side effects "
                    "because it duplicates the operand. Signed division by 2^k needs a sign-correcting sequence, so "
                    "the simple rewrite is deliberately omitted.",
        "example": ("y = n * 8;", "y = n << 3;"),
    },
    "dead_code_elimination": {
        "title": "Dead-code elimination",
        "aliases": ["dead code", "dead-code", "dce", "dead store", "unreachable", "dead code elimination"],
        "beginner": "Code that can never run, or whose result nobody uses, is just clutter. The compiler deletes it "
                    "so the program is smaller and faster. If the code also does something visible (like calling a "
                    "function), that part is always kept.",
        "intermediate": "Three clean-ups: (1) branches whose condition is constant are replaced by the branch that "
                        "runs, (2) statements after a return are removed, (3) assignments whose value is never read "
                        "again are removed, found with a backward liveness analysis. Calls and operations that can "
                        "trap (division) are never deleted.",
        "advanced": "Backward may-analysis computing live-variable sets; at joins the sets are unioned and loops "
                    "iterate to a fixpoint (a variable read by the next iteration is live across the back edge). A "
                    "dead store with an impure right-hand side is demoted to an expression statement to preserve "
                    "effects. Stores to non-locals (globals, fields) are treated as observable.",
        "example": ("t = n * 100;   // never read\nreturn n;", "return n;"),
    },
    "loop_invariant_hoisting": {
        "title": "Loop-invariant hoisting",
        "aliases": ["hoisting", "loop invariant", "loop-invariant", "code motion", "hoist"],
        "beginner": "If a loop recalculates something that never changes (like a * b every time round), it is faster to "
                    "calculate it once before the loop and reuse the answer.",
        "intermediate": "A computation inside a loop whose operands are not modified by the loop is moved in front of the "
                        "loop into a temporary. Only side-effect-free expressions that cannot trap are moved.",
        "advanced": "Loop-invariant code motion on structured loops: an expression is invariant if every variable it reads "
                    "is outside defined_names(body). Hoisting a pure, non-trapping expression is safe even when the loop "
                    "executes zero times, because evaluating it early has no observable effect.",
        "example": ("while (i < n) { s = s + a * b; i = i + 1; }", "t = a * b;\nwhile (i < n) { s = s + t; i = i + 1; }"),
    },
    "liveness": {
        "title": "Liveness (live variables)",
        "aliases": ["liveness", "live variable", "live variables", "live"],
        "beginner": "A variable is 'live' if its current value will still be needed later. If nobody will ever read "
                    "what you stored, the store is wasted.",
        "intermediate": "A backward data-flow analysis: a variable is live before a statement if the statement reads "
                        "it, or if it is live after the statement and the statement does not overwrite it.",
        "advanced": "live_in = use ∪ (live_out − def), solved backwards; at branches live_out is the union over "
                    "successors and for loops the equations are iterated to a fixpoint.",
        "example": ("x = 1;\nx = 2;\nreturn x;", "x = 2;\nreturn x;   (the first store is dead)"),
    },
    "digital_twin": {
        "title": "Digital Twin",
        "aliases": ["digital twin", "twin", "simulation", "sandbox"],
        "beginner": "The twin is a safe practice copy of your function. CodeTune tries different optimization "
                    "plans on the copy, predicts how fast each would be, and only then tells you which is best. "
                    "Your real code is never touched.",
        "intermediate": "A virtual replica of the compilation: each strategy (an ordered list of passes) runs on its own "
                        "copy, a static cost model predicts cost, code size and stack memory, and the result is "
                        "differentially tested for safety. It answers what-if questions and keeps versions you can "
                        "roll back to.",
        "advanced": "Static expected-cost estimation (exact for straight-line code and constant-bound loops, 50/50 "
                    "weighting for unknown branches, default trip count for unknown loops) is compared against "
                    "interpreter-measured cost on the validation inputs to quantify prediction error.",
        "example": ("", ""),
    },
    "validation": {
        "title": "Semantic validation (differential testing)",
        "aliases": ["validation", "differential testing", "semantic", "safe", "correct", "equivalent"],
        "beginner": "After optimizing, CodeTune runs the old and the new version on lots of test inputs. If any "
                    "answer differs, the optimization is thrown away.",
        "intermediate": "Both versions are executed by the IR interpreter on boundary values (0, 1, -1, INT_MAX, ...) "
                        "plus seeded random inputs; return values (including their type), errors and termination "
                        "must match. A pass that fails is rolled back and reported.",
        "advanced": "Testing-based translation validation: evidence, not proof (unlike CompCert-style formal "
                    "verification). Its strength is the boundary-value input set and exact comparison of values, "
                    "types and error behaviour; its weakness is inputs it never generates.",
        "example": ("", ""),
    },
    "confidence": {
        "title": "Confidence score",
        "aliases": ["confidence", "probability", "score"],
        "beginner": "A number between 0 and 1 saying how sure CodeTune is that a pass will help. Above 0.5 the pass runs.",
        "intermediate": "The rule-based selector builds it from static features plus a dry run; the ML selector uses the "
                        "average vote of a random forest trained on labelled programs.",
        "advanced": "Rule-based: gate on features, then raise with the number of concrete sites found. ML: the mean of "
                    "per-tree leaf probabilities (not calibrated), thresholded at 0.5.",
        "example": ("", ""),
    },
}

PASS_NAMES = ["constant_propagation", "constant_folding", "strength_reduction", "dead_code_elimination"]


def find_topic(text: str):
    """Longest-alias match wins ('dead code elimination' before 'dead')."""
    t = text.lower()
    best, best_len = None, 0
    for key, info in TOPICS.items():
        for alias in info["aliases"]:
            if len(alias) > 2 and alias in t and len(alias) > best_len:
                best, best_len = key, len(alias)
            elif len(alias) <= 2 and f" {alias} " in f" {t.replace(',', ' ').replace('?', ' ')} " and len(alias) > best_len:
                best, best_len = key, len(alias)
    return best


def explain(topic: str, level: str) -> str:
    info = TOPICS[topic]
    text = f"{info['title']} ({level}): {info[level]}"
    before, after = info["example"]
    if before:
        text += f"\nExample:\n  before: {before.replace(chr(10), chr(10) + '          ')}\n  after:  {after.replace(chr(10), chr(10) + '          ')}"
    return text