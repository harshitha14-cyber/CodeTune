# CodeTune

**An explainable, adaptive compiler optimizer with a Digital Twin and an AI Copilot.**

CodeTune reads a function written in **Python, C, C++ or Java**, optimizes it, **proves** that the optimized version behaves exactly like the original, **predicts** what each optimization strategy will cost, and **explains** every change in plain language. Everything is available through a local web dashboard, a set of command-line tools and a Python API.

---

## Features

| Feature | What it gives you |
|---|---|
| **Multi-language front-end** | Real Python, C, C++ and Java source is parsed with [tree-sitter](https://tree-sitter.github.io/tree-sitter/) grammars and automatically language-detected. |
| **One Common IR** | Every language is translated into a single intermediate representation, so the analysis, optimizer, validator, Digital Twin and Copilot are written once and work for all four languages. |
| **Static analysis** | Per-function features: loops, branches, nesting depth, constants, arithmetic / comparison / logical operations, multiplications and divisions, expression depth, constant assignments. |
| **Adaptive pass selection** | A rule-based selector (feature gates + a dry run + confidence score + reason) and an optional ML selector decide which passes are worth running. |
| **Four optimization passes** | Constant propagation, constant folding, strength reduction and dead-code elimination, run to a fixed point. |
| **Semantic validation** | Differential testing of the original against the optimized code on boundary and random inputs. A pass that changes behaviour is rolled back automatically. |
| **Digital Twin** | Simulates strategies (single passes, pass orders, fixed point, adaptive), predicts their cost, compares the prediction with the measured cost, and recommends the best valid strategy. Supports what-if analysis. |
| **AI Copilot** | Answers questions about your own code and results, at beginner, intermediate or advanced level. Works fully offline; an optional Gemini model rephrases answers and handles open compiler-theory questions. |
| **Insights and refactoring** | Cost hotspots, refactoring suggestions, and a verified automatic loop-invariant hoisting refactoring. |
| **Interactive dashboard** | Local web app (plain HTML, CSS and JavaScript) with a clickable, animated pipeline Flow diagram, side-by-side diffs, pass explanations, Digital Twin charts and a chat panel. |
| **Reports** | Markdown, HTML and JSON reports for optimization runs and Digital Twin runs. |

---

## How it works

```
source (.py / .c / .cpp / .java)
        |  tree-sitter parser
        v
  language-specific syntax tree
        |  per-language translator
        v
     Common IR  <------ everything below sees only this
        |
        v
  Feature extraction  ->  Pass selection (rules + optional ML, with confidence)
        |
        v
  Optimization passes, repeated to a fixed point
        |
        v
  Differential validation  (original vs optimized on many inputs; rollback on mismatch)
        |
        v
  Digital Twin  (predict cost -> measure -> compare -> recommend)
        |
        v
  Optimized code + explanations + Copilot + dashboard + reports
```

### Optimization passes

| Pass | What it does | Example |
|---|---|---|
| `constant_propagation` | Replaces a variable that always holds the same value with that value. | `scale = 8; x * scale` becomes `x * 8` |
| `constant_folding` | Computes constant expressions at compile time. | `2 * 3 + 1` becomes `7` |
| `strength_reduction` | Replaces expensive operations with cheaper ones, only when the operand is provably an integer. | `i * 8` becomes `i << 3` |
| `dead_code_elimination` | Removes unused variables, unreachable code and dead stores; side effects such as function calls are always kept. | `waste = total * 100;` is removed |

### Correctness rules built into the optimizer

- **Language-aware semantics.** `7 / 2` is `3` in C, C++ and Java but `3.5` in Python; `-7 % 3` is `-1` vs `2`. `ir/semantics.py` is the single source of truth, including 32-bit integer overflow.
- **Never fold when unsure** (division by zero, possible overflow, string operations in C).
- **Only provably-local variables** are propagated or deleted, because a global or field can be changed by any call.
- **Impure dead stores keep their expression:** `unused = f(x)` becomes `f(x);`.
- **Type-aware strength reduction:** `n / 8` is never turned into a shift, since that is wrong for negative `n`.

---

## Installation

Requires **Python 3.10 or newer**.

```bash
pip install -r requirements.txt
```

This installs tree-sitter with the Python, C, C++ and Java grammars, and pytest. The ML selector, decision tree and random forest are implemented in plain Python, so no scikit-learn is needed.

---

## Quick start

All commands are run from the `codetune/` folder.

### 1. Dashboard (recommended)

```bash
python run_dashboard.py                      # opens http://127.0.0.1:8765
python run_dashboard.py --port 9000 --no-browser
python run_dashboard.py --ml                 # also show the ML selector (trains once if needed)
```

Paste or drop in a function, or choose one from the **Examples** menu, and press **Analyze & optimize** (Ctrl+Enter). The server only listens on `127.0.0.1`, so nothing leaves your computer except optional Gemini requests.

| Tab | Contents |
|---|---|
| **Flow** | Interactive 8-stage pipeline diagram. Click a stage to see what it did to your code, or press Play to animate it. |
| **Overview** | Pipeline summary, the Common IR and all static features. |
| **Optimized code** | Original and optimized code side by side, a line-by-line comparison and a plain-language explanation of every change. Copy or download the result. |
| **Passes** | Selector decisions with confidence and reasons, what each pass changed, and the validation result. |
| **Digital Twin** | Predicted vs measured cost for every strategy, error percentages and the recommendation. |
| **Insights** | Cost hotspots, refactoring suggestions and a verified refactoring. |
| **Copilot** | Chat with level selection and one-click suggested questions. |

The dashboard also shows proactive alerts (for example a variable that is assigned but never read) and can re-analyze as you type.

### 2. Command-line tools

```bash
# Parse a file and print its Common IR
python demo.py samples/sample.py
python demo.py samples/sample.c

# Static features, pass recommendations, full optimization with validation
python demo.py samples/optimize_demo.c --features
python demo.py samples/optimize_demo.c --select
python demo.py samples/optimize_demo.c --optimize
python demo.py samples/optimize_demo.java --optimize --passes constant_folding,dead_code_elimination
python demo.py samples/optimize_demo.c --optimize --report reports     # .md / .html / .json

# Digital Twin
python twin_demo.py samples/twin_demo.c                        # compare strategies and recommend one
python twin_demo.py samples/twin_demo.c --permutations         # try all 24 pass orders
python twin_demo.py samples/twin_demo.c --order CP,SR          # what if CP runs before SR?
python twin_demo.py samples/twin_demo.c --whatif CF,CP,DCE     # what if exactly this sequence?
python twin_demo.py samples/twin_demo.c --report reports

# ML pass selector
python train_selector.py                                       # train, report accuracy, save the model
python train_selector.py --rules                               # print the readable decision rules
python train_selector.py --compare samples/twin_demo.c         # ML vs rule-based choices

# Copilot in the terminal
python copilot_demo.py samples/twin_demo.c --ask "why is this slow?"

# Check that the installation works
python check_install.py
```

Pass abbreviations: `CP` constant propagation, `CF` constant folding, `SR` strength reduction, `DCE` dead-code elimination.

---

## Gemini (optional)

The Copilot is useful with no internet and no key. Adding a Gemini key lets it phrase answers more naturally, answer open compiler-theory questions, and give advice for code outside the supported subset (clearly marked as unverified).

1. Create a free key at <https://aistudio.google.com/apikey>.
2. Copy `.env.example` to `.env` (same folder as `run_dashboard.py`) and add your key:

   ```
   GEMINI_API_KEY=your_key_here
   # optional: GEMINI_MODEL=gemini-flash-latest
   ```
3. Restart `python run_dashboard.py`. The top bar shows **Gemini: on**.

Behaviour:

- **Automatic on/off.** Gemini is on whenever a key is present. If the quota is reached it pauses itself (about a minute, or an hour for a daily limit), the Copilot continues offline, and Gemini resumes automatically.
- **Server overload (HTTP 503).** The client retries with fallback models.
- **Privacy.** Only your question and a short summary of your code are sent to Google. The key is read from `.env` or the `GEMINI_API_KEY` environment variable, never entered in the web page, and never written anywhere else. `.env` is in `.gitignore`.
- **Scope guard.** Questions unrelated to compiler design, your code or its optimization are refused before any model is called, and the model is instructed not to add facts of its own.

---

## Supported language subset

The subset is deliberately small and identical across all four languages, so the same IR and optimizer apply to each:

- function declarations with parameters
- variable declaration and assignment
- arithmetic, comparison and logical expressions, unary `-` and `!`
- int, float, bool and string literals
- `if` / `else`, `while`, and simple counted `for` loops (rewritten as equivalent `while` loops; in Python, `for x in range(...)`)
- `return` and function calls

Code outside this subset (pointers, arrays, structs and classes as data, templates, `new` / smart pointers, method chaining, and so on) is rejected with a clear message naming the construct and line, instead of producing a wrong result. When Gemini is on, the dashboard also shows AI advice for that code.

---

## Project layout

```
codetune/
  frontend/              tree-sitter wrapper: language detection and parsing
  ir/
    ir_nodes.py          the Common IR node types
    ir_printer.py        IR -> readable pseudocode
    source_printer.py    IR -> source code in the original language
    semantics.py         per-language arithmetic semantics
    ir_utils.py          cloning, purity, local variables, type inference
    interpreter.py       executes IR (test oracle and cost counters)
    translators/         python / c / cpp / java translators
  analysis/
    feature_extractor.py static features per function
    pass_selector.py     rule-based selector with confidence and reasons
  optimizer/             the four passes, registry and pass manager
  validation/            input generation and differential testing
  ml/                    decision tree, random forest, ML selector, training corpus
  digital_twin/          cost model, sandbox, strategies, twin, reports
  copilot/               Copilot, knowledge base, scope guard, refactoring, Gemini client
  reporting/             Markdown / HTML / JSON report generator
  dashboard/
    server.py            local HTTP API
    static/              index.html, style.css, app.js (the frontend)
  samples/               the same programs in all four languages
  tests/                 automated test suite
  run_dashboard.py       start the dashboard
  demo.py                parse, analyze, optimize and report from the command line
  twin_demo.py           Digital Twin command line
  train_selector.py      train and evaluate the ML selector
  copilot_demo.py        Copilot in the terminal
  check_install.py       installation self-check
```

---

## Testing

```bash
python -m pytest tests -v
```

The suite covers all four front-ends producing the same IR shape, every pass, a randomized program generator (differential testing of original vs optimized code in all four languages), the validator, the Digital Twin and its cost model, the ML selector, the Copilot and scope guard, the Gemini client (with a fake server), and the dashboard API. Deliberately breaking a pass makes the differential tests fail, which is what proves the validator works.

---

## Known limitations

- The supported subset above is intentional; arrays, pointers, structs and classes are not modelled yet.
- `int r; r = 11 + c;` is not merged into `int r = 11 + c;`.
- Python parameters have no declared type, so Python receives fewer type-based rewrites (for example, strength reduction is applied only when an integer type is provable).
- A constant branch that contains a declaration is not inlined, to avoid name clashes.
- Costs are in abstract *work units* from a weighted operation model, not wall-clock time.
- Code is executed by CodeTune's own interpreter, never natively.

---

## Technology

Python (analysis, optimizer, validator, Digital Twin, Copilot, local HTTP server) - tree-sitter (parsing) - HTML, CSS and JavaScript (dashboard) - optional Google Gemini API - pytest.