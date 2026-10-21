"""
Scope guard: the Copilot only answers questions about compiler design, the user's code
and its optimization (and how CodeTune works). Everything else gets a polite refusal.

Layers of defence
  1. this keyword gate runs BEFORE anything else, so off-topic questions never reach the
     analysis code or the language model (saves quota, blocks misuse);
  2. the Gemini system prompt repeats the restriction and tells the model to answer with the
     token OFF_TOPIC, which the Copilot turns into the same refusal;
  3. user text is wrapped in tags and declared to be data, not instructions.

It is a heuristic (keyword based), not a perfect classifier: a cleverly worded off-topic
question that uses compiler vocabulary can pass layer 1, which is why layer 2 exists.
"""

import re

# unambiguous compiler / CodeTune vocabulary: always in scope (matched at the START of a word)
CORE_PREFIXES = [
    "compil", "lexer", "lexical", "tokeniz", "tokenis", "parser", "parsing", "grammar", "abstract syntax", "parse tree",
    "intermediate representation", "three-address", "three address", "control flow", "basic block", "data flow",
    "dataflow", "liveness", "live variable", "register alloc", "code generation", "codegen", "assembler", "linker",
    "llvm", "clang", "bytecode", "virtual machine", "symbol table", "semantic analysis", "type check", "type infer",
    "decompil", "optimi", "inlining", "loop unroll", "vectoriz", "vectoris", "peephole", "common subexpression",
    "dead code", "dead store", "constant fold", "constant propag", "strength reduc", "tail call", "loop invariant",
    "hoisting", "codetune", "digital twin", "pass selector", "differential test", "syntax error", "type system",
]
# unambiguous short words (must match as whole words)
CORE_WORDS = ["ast", "ssa", "cfg", "cse", "jit", "gcc", "ir", "dce", "llvm", "ll(1)", "lalr", "lr", "ll"]

# everyday programming words: in scope unless the question is clearly about something else
COMMON_PREFIXES = [
    "code", "program", "function", "variable", "loop", "branch", "statement", "expression", "operator", "algorithm",
    "complexity", "big-o", "big o", "runtime", "run time", "performance", "benchmark", "profil", "recursi",
    "refactor", "integer", "float", "overflow", "memory", "cache", "register", "instruction", "interpreter",
    "syntax", "python", "java", "c++", "cpp", "source", "twin", "selector", "confidence", "validation", "strategy",
    "hotspot", "sandbox", "predicted", "bug", "token", "pars", "shift", "modulo", "bit", "cost", "pass",
]
COMMON_WORDS = ["c", "ast"]

# weak signals: only count for short, clearly-referential questions about "this/it/my ..."
WEAK_TERMS = ["slow", "fast", "faster", "safe", "safety", "changed", "change", "why did you", "which passes", "explain",
              "level", "simpler", "detail", "helps", "result", "correct", "better", "sure", "what if"]

OFF_TOPIC_TERMS = [
    "recipe", "cook", "egg", "weather", "movie", "film", "song", "lyrics", "football", "soccer", "cricket match",
    "election", "president", "prime minister", "stock price", "bitcoin", "crypto", "horoscope", "girlfriend",
    "boyfriend", "dating", "medicine", "doctor", "symptom", "diet", "joke", "poem", "story", "capital of",
    "celebrity", "travel", "hotel", "flight", "religion", "politic", "lottery", "gossip", "airport", "restaurant",
]

REFERENCE = re.compile(r"\b(this|it|that|my|your|these|those)\b|\bthe (function|code|loop|program|result)\b")


def _prefix_re(terms):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in terms) + ")")


def _word_re(terms):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in terms) + r")(?![a-z0-9])")


_CORE = (_prefix_re(CORE_PREFIXES), _word_re(CORE_WORDS))
_COMMON = (_prefix_re(COMMON_PREFIXES), _word_re(["ast"]))

REFUSAL = ("I'm CodeTune's Copilot, so I can only help with compiler design, your code and how it is "
           "analysed and optimized - for example 'why is this loop slow?', 'what if I apply constant "
           "propagation before strength reduction?' or 'what is liveness analysis?'. "
           "Please ask me something along those lines.")


def _hit(patterns, text):
    return any(p.search(text) for p in patterns)


def in_scope(question: str) -> bool:
    t = question.lower()
    if _hit(_CORE, t):
        return True
    if any(w in t for w in OFF_TOPIC_TERMS):
        return False
    if _hit(_COMMON, t):
        return True
    return len(t.split()) <= 12 and any(w in t for w in WEAK_TERMS) and bool(REFERENCE.search(t))