"""
CodeTune Copilot (Milestones 5 + 6, report 3.3 / 4.2).

A hybrid assistant, as the report describes:
  * an expert system: intent recognition + answers built ONLY from CodeTune's own
    analysis (features, selector confidences, the validated optimization report,
    Digital Twin predictions, refactoring suggestions) -- so every number it
    quotes is real and checkable;
  * an optional language model (Gemini, see llm.py): it REPHRASES the facts for the
    user's level and answers open compiler-theory questions. It is told to add no
    facts; if it fails the plain answer is used. Without a model the Copilot works
    fully offline.

SCOPE: only compiler design, the user's code and its optimization are answered
(see scope.py); everything else gets a polite refusal before any model is called.
"""

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..analysis.pass_selector import RuleBasedPassSelector
from ..digital_twin import DigitalTwin
from ..digital_twin.cost_model import StaticCostEstimator, estimated_time_ns
from ..digital_twin.strategy import SHORT, Strategy, run_strategy
from ..frontend.parser import parse_source
from ..ir.ir_printer import _print_stmt, print_function
from ..ir.ir_utils import defined_names
from ..ir.source_printer import function_to_source
from ..ir.translators import get_translator
from ..optimizer.pass_manager import optimize_program
from ..optimizer.registry import PASS_ORDER
from . import knowledge
from .knowledge import LEVELS, TOPICS, explain, find_topic
from .llm import OFF_TOPIC_TOKEN, SYSTEM_PROMPT, LLMError, as_llm, rephrase_prompt, theory_prompt
from .refactor import Suggestion, find_suggestions, hoist_loop_invariants
from .scope import OFF_TOPIC_TERMS, REFERENCE, REFUSAL, in_scope

_PASS_ALIASES = {
    "constant_propagation": ["constant propagation", "propagation", "propagate", "cp"],
    "constant_folding": ["constant folding", "folding", "fold", "cf"],
    "strength_reduction": ["strength reduction", "strength", "sr"],
    "dead_code_elimination": ["dead code elimination", "dead-code elimination", "dead code", "dce"],
}

COMMAND_INTENTS = {"simpler", "deeper", "set_level", "help"}
CONTEXT_INTENTS = {"slow", "optimize", "changes", "whatif", "safety", "selection", "features", "show_code"}

HELP = ("I can help with:\n"
        "  - why is this loop slow?                    (cost hotspots)\n"
        "  - how can I optimize this function?         (best plan + verified refactorings)\n"
        "  - what changed? / why did you change line 7?\n"
        "  - what if I apply constant propagation before strength reduction?\n"
        "  - is the optimization safe?                 (validation result)\n"
        "  - show me the optimized code and why you chose it\n"
        "  - which passes did you choose and how sure are you?\n"
        "  - what is constant folding? / what is SSA form?   (learning mode; open questions need Gemini)\n"
        "  - explain simpler / explain in more detail / set level advanced")


@dataclass
class CopilotAnswer:
    text: str
    intent: str
    data: Dict = field(default_factory=dict)
    followups: List[str] = field(default_factory=list)


def _passes_in(text: str) -> List[str]:
    """Pass names mentioned in `text`, in order of appearance."""
    t = " " + re.sub(r"[,.?!]", " ", text.lower()) + " "
    hits = []
    for name, aliases in _PASS_ALIASES.items():
        pos = [t.find(f" {a} ") if len(a) <= 3 else t.find(a) for a in aliases]
        pos = [p for p in pos if p >= 0]
        if pos:
            hits.append((min(pos), name))
    return [n for _, n in sorted(hits)]


def _first_error_line(root) -> Optional[int]:
    """Line (1-based) of the first syntax-error node, or None."""
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            return n.start_point[0] + 1
        stack.extend(reversed(n.children))
    return None


def classify(question: str) -> str:
    t = question.lower().strip()
    if re.search(r"\b(simpler|easier|eli5|too (hard|technical|complicated))\b", t):
        return "simpler"
    if re.search(r"\b(more detail|in depth|deeper|more technical|go deeper)\b", t):
        return "deeper"
    if re.search(r"\b(set|switch|change)\b.*\blevel\b|\blevel\b\s*(to|:)?\s*(beginner|intermediate|advanced)|\bi am an? (beginner|intermediate|advanced)", t):
        return "set_level"
    if re.fullmatch(r"(help|\?|what can you do\??|commands)", t):
        return "help"
    if "what if" in t or re.search(r"\b(before|after)\b", t) and len(_passes_in(t)) >= 2 or "order" in t and _passes_in(t):
        return "whatif"
    if re.search(r"\b(slow|hotspot|bottleneck|performance|expensive|takes? long|cost)\b", t) and "confiden" not in t:
        return "slow"
    if re.search(r"\bwhy did you (choose|select|pick|run|skip)\b|confiden|which passes|selector|machine learning|\bml\b", t):
        return "selection"
    if re.search(r"\b(why|how come)\b.*\b(chang|remov|replac|fold|propag|delet|eliminat|shift|line \d+)|what (changed|did you)|\bchanges\b|\bdiff\b|"
                 r"\bdid you (chang|remov|replac|delet|modif|touch|fold|eliminat)\w*|\bline \d+\b", t):
        return "changes"
    if not re.search(r"\b(safe|valid|correct|slow)\b", t) and re.search(
            r"\b(optimi[sz]ed|final|resulting|improved|prefer\w*|recommended)\b.{0,25}\bcode\b|"
            r"\b(show|give|print|write|display|generate)\b.{0,25}\b(code|version|source)\b|"
            r"\bwhat would you write\b|\brewrite\b|\bcode (that )?you (would )?(prefer|recommend|suggest)", t):
        return "show_code"
    if re.search(r"\b(optimi[sz]e|improve|speed up|faster|better|refactor|suggest|tips?)\b", t):
        return "optimize"
    if re.search(r"\b(safe|safety|correct|valid|same result|behaviou?r|semantic|break|trust)\b", t):
        return "safety"
    if re.search(r"\b(features?|metrics?|complexity|statistics|how big|analy[sz]e)\b", t):
        return "features"
    if re.search(r"\b(what is|what's|explain|teach|learn|how does|tell me about|meaning of)\b", t) or find_topic(t):
        return "learn"
    return "unknown"


class CopilotSession:
    def __init__(self, code: str, language: str, function: Optional[str] = None, level: str = "beginner",
                 llm: Optional[Callable[[str], str]] = None, ml_selector=None):
        if level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}")
        self.level, self.llm, self.ml = level, as_llm(llm), ml_selector
        self.history: List[tuple] = []
        self._last_question: Optional[str] = None
        self.code, self.language = code, language
        self._load(code, language, function)

    # ------------------------------------------------------------------ context

    def _load(self, code, language, function):
        tree, src = parse_source(code, language)
        if tree.root_node.has_error:
            line = _first_error_line(tree.root_node)
            raise ValueError("the code has a syntax error" + (f" near line {line}" if line else "")
                             + " - fix it and try again")
        try:
            program = get_translator(language, src).translate_program(tree.root_node)
        except NotImplementedError as e:
            raise ValueError(f"unsupported construct: {e}")
        if not program.functions:
            raise ValueError("no function found in the code")
        self.program = program
        self.func_name = function or program.functions[0].name
        self.func = next(f for f in program.functions if f.name == self.func_name)
        self.twin = DigitalTwin(program, self.func_name)
        self.report = optimize_program(program, validate=True)
        self.fr = self.report.functions[self.func_name]
        self.features = self.fr.features_before
        self.rule_recs = self.fr.recommendations
        self.ml_recs = self.ml.select(self.func, language) if self.ml is not None else None
        self.suggestions: List[Suggestion] = find_suggestions(self.func, program, language)
        self._experiments = None
        self._recommendation = None
        self._refactor = None

    def update_source(self, code: str, language: Optional[str] = None) -> List[str]:
        """Real-time synchronisation: rebuild the whole context for edited code."""
        self.code = code
        self.language = language or self.language
        self._load(code, self.language, self.func_name if self.func_name else None)
        return self.alerts()

    @property
    def experiments(self):
        if self._experiments is None:
            self._experiments = self.twin.explore()
            self._recommendation = self.twin.recommend(self._experiments)
        return self._experiments

    @property
    def recommendation(self):
        _ = self.experiments
        return self._recommendation

    @property
    def refactoring(self) -> Optional[dict]:
        """Verified automatic refactoring (loop-invariant hoisting), or None."""
        if self._refactor is None:
            new, changes = hoist_loop_invariants(self.func, self.language)
            if not changes:
                self._refactor = {}
            else:
                v = self.twin.validator.check(new)
                m = self.twin._metrics(new)
                combined, valid2, cost2, combined_changes = None, False, None, []
                if v.passed:
                    canon = Strategy("canonical to fixpoint", tuple(PASS_ORDER), 0)
                    combined, combined_changes = run_strategy(new, self.language, canon)
                    v2 = self.twin.validator.check(combined)
                    valid2, cost2 = v2.passed, self.twin._metrics(combined).predicted_cost
                self._refactor = {"func": new, "changes": changes, "valid": v.passed, "validation": v,
                                  "predicted_cost": m.predicted_cost, "combined_valid": valid2,
                                  "combined_cost": cost2, "combined_func": combined,
                                  "combined_changes": combined_changes}
        return self._refactor or None

    # ------------------------------------------------------------------ proactive alerts

    def alerts(self) -> List[str]:
        out = []
        for s in self.suggestions:
            if s.severity in ("warning", "tip"):
                out.append(f"line {s.line}: {s.message}")
        if self.fr.rejected:
            out.append("An optimization was rejected because it changed behaviour: "
                       + ", ".join(r.pass_name for r in self.fr.rejected))
        if self.recommendation.saving_pct >= 10:
            out.append(f"The Digital Twin predicts {self.recommendation.saving_pct}% lower cost with "
                       f"'{self.recommendation.experiment.strategy.name}'.")
        return out

    # ------------------------------------------------------------------ small formatting helpers

    def _cost(self, c: float) -> str:
        if self.level == "beginner":
            return f"about {c:.0f} 'work units'"
        if self.level == "intermediate":
            return f"{c:.0f} cost units"
        return f"{c:.1f} cost units (~{estimated_time_ns(c):.0f} ns at the modelled 3 GHz)"

    def _pass_line(self, name: str) -> str:
        info = TOPICS[name]
        sentences = info[self.level].split(". ")
        short = ". ".join(sentences[:2]).rstrip(".")
        return f"{info['title']}: {short}."

    # ------------------------------------------------------------------ main entry

    def set_llm(self, llm):
        self.llm = as_llm(llm)

    def _allowed(self, intent: str, question: str) -> bool:
        if intent in COMMAND_INTENTS:
            return True
        low = question.lower()
        if intent in CONTEXT_INTENTS:
            if in_scope(question) or _passes_in(low):
                return True
            if any(w in low for w in OFF_TOPIC_TERMS):
                return False
            # clearly about THIS code: "this / it / my ...", a line number, very short, or "did you ..." about our work
            return (bool(REFERENCE.search(low)) or len(low.split()) <= 4 or bool(re.search(r"\bline \d+\b", low))
                    or (intent in ("changes", "selection", "whatif", "safety") and bool(re.search(r"\byou\b", low))))
        return in_scope(question)

    def ask(self, question: str) -> CopilotAnswer:
        question = question.strip()[:500]
        intent = classify(question)
        if not self._allowed(intent, question):
            ans = CopilotAnswer(REFUSAL, "off_topic", followups=["why is this slow?", "what is constant folding?"])
            self.history.append((question, ans))
            return ans
        if intent == "learn" and find_topic(question) is None:
            intent = "unknown"
        handler = getattr(self, f"_answer_{intent}")
        ans = handler(question)
        if intent not in ("simpler", "deeper", "set_level", "help", "unknown", "off_topic"):
            self._last_question = question
        if self.llm is not None and intent not in COMMAND_INTENTS | {"unknown", "off_topic"}:
            ans = self._rephrase(question, ans)
        self.history.append((question, ans))
        return ans

    def _rephrase(self, question: str, ans: CopilotAnswer) -> CopilotAnswer:
        """Let the language model reword the facts (it may not add any)."""
        try:
            text = self.llm.generate(rephrase_prompt(self.level, question, ans.text), SYSTEM_PROMPT)
            if text.strip() == OFF_TOPIC_TOKEN:
                return ans                                   # facts were in scope; keep our own answer
            ans.data["facts"] = ans.text
            ans.text = text.strip()
            ans.data["llm"] = True
        except LLMError as e:
            ans.data["llm_error"] = str(e)
        except Exception as e:                               # never let the model break the session
            ans.data["llm_error"] = f"{type(e).__name__}: {e}"
        return ans

    def optimized_source(self) -> dict:
        """The best version of the analysed function that CodeTune has VERIFIED, as real source
        code in the user's own language, with the reasons for every change."""
        base = self.twin.baseline.predicted_cost
        rec = self.recommendation
        best_func, label, changes = rec.experiment.func, rec.experiment.strategy.name, list(rec.experiment.changes)
        cost = rec.experiment.metrics.predicted_cost
        r = self.refactoring
        if r and r["valid"] and r["combined_valid"] and r["combined_cost"] is not None and r["combined_cost"] < cost - 1e-9:
            best_func, cost = r["combined_func"], r["combined_cost"]
            label = "loop-invariant hoisting + canonical passes"
            changes = list(r["changes"]) + list(r["combined_changes"])
        groups = {}
        for c in changes:
            groups.setdefault(c.pass_name, []).append(c)
        why = []
        for name, cs in groups.items():
            info = TOPICS.get(name)
            why.append({"pass": name, "title": info["title"] if info else name, "count": len(cs),
                        "explanation": info[self.level] if info else "",
                        "examples": [f"line {c.line}: {c.description}" for c in cs[:3]]})
        return {"code": function_to_source(best_func, self.language), "language": self.language,
                "original": function_to_source(self.func, self.language), "strategy": label,
                "cost_before": base, "cost_after": cost,
                "saving_pct": round(100.0 * (base - cost) / base, 1) if base else 0.0,
                "validated": True, "why": why, "func": best_func}

    # ------------------------------------------------------------------ intents

    def _answer_help(self, q) -> CopilotAnswer:
        return CopilotAnswer(HELP, "help", followups=["why is this slow?", "how can I optimize this function?"])

    def _answer_set_level(self, q) -> CopilotAnswer:
        m = re.search(r"(beginner|intermediate|advanced)", q.lower())
        if not m:
            return CopilotAnswer("Choose one of: beginner, intermediate, advanced.", "set_level")
        self.level = m.group(1)
        return CopilotAnswer(f"Okay - explanations are now at the {self.level} level.", "set_level",
                             {"level": self.level})

    def _shift(self, step: int, word: str) -> CopilotAnswer:
        i = max(0, min(len(LEVELS) - 1, LEVELS.index(self.level) + step))
        if LEVELS[i] == self.level:
            return CopilotAnswer(f"I am already at the {self.level} level - that is as {word} as I go.", "level")
        self.level = LEVELS[i]
        if self._last_question:
            again = self.ask(self._last_question)
            again.text = f"(level: {self.level})\n" + again.text
            return again
        return CopilotAnswer(f"Okay - explanations are now at the {self.level} level.", "level", {"level": self.level})

    def _answer_simpler(self, q):
        return self._shift(-1, "simple")

    def _answer_deeper(self, q):
        return self._shift(+1, "detailed")

    # -- why is it slow ---------------------------------------------------------------

    def hotspots(self) -> List[dict]:
        est = StaticCostEstimator(self.twin._program_with(self.func))
        env, p, rows = {}, 1.0, []
        for s in self.func.body.statements:
            before = dict(env)
            c, pf = est._stmt(s, env)
            row = {"line": s.line, "cost": p * c, "kind": type(s).__name__,
                   "code": (_print_stmt(s, 0) or [""])[0].strip()}
            if type(s).__name__ == "While":
                assigned = defined_names(s.body)
                inv = {k: v for k, v in before.items() if k not in assigned}
                row["trips"] = est._trip_count(s, before, inv, assigned)
            rows.append(row)
            p *= pf
        total = sum(r["cost"] for r in rows) or 1.0
        for r in rows:
            r["share_pct"] = round(100.0 * r["cost"] / total, 1)
        return sorted(rows, key=lambda r: -r["cost"])

    def _answer_slow(self, q) -> CopilotAnswer:
        rows = self.hotspots()
        top = rows[:3]
        total = self.twin.baseline.predicted_cost
        lines = [f"The twin predicts {self._cost(total)} for one call of {self.func_name}."]
        for i, r in enumerate(top, 1):
            where = f"the loop at line {r['line']}" if r["kind"] == "While" else f"line {r['line']} ({r['code']})"
            extra = ""
            if r["kind"] == "While":
                extra = f" It runs about {r['trips']:.0f} iterations, so its cost is multiplied by that."
            lines.append(f"{i}. {where} is {r['share_pct']}% of the cost.{extra}")
        rec = self.recommendation
        if rec.saving_pct > 0:
            lines.append(f"Good news: the best compiler plan ('{rec.experiment.strategy.name}') lowers the total by "
                         f"{rec.saving_pct}% - see 'how can I optimize this function?'.")
        relevant = [s for s in self.suggestions if s.kind in ("hoist", "heavy_op_in_loop", "cse", "unknown_call")]
        if relevant:
            lines.append("What you can do:")
            lines += [f"  - line {s.line}: {s.message} {s.fix}" for s in relevant[:3]]
        elif rec.saving_pct <= 0:
            lines.append("Nothing obviously wasteful stands out in this function.")
        return CopilotAnswer("\n".join(lines), "slow", {"hotspots": top},
                             ["how can I optimize this function?", "what if I apply constant propagation before strength reduction?"])

    # -- how to optimize ---------------------------------------------------------------------

    def _answer_optimize(self, q) -> CopilotAnswer:
        base, rec = self.twin.baseline.predicted_cost, self.recommendation
        lines = []
        best = rec.experiment
        if rec.saving_pct > 0:
            lines.append(f"Best compiler plan: '{best.strategy.name}' - predicted cost {self._cost(base)} -> "
                         f"{self._cost(best.metrics.predicted_cost)} ({rec.saving_pct}% lower). It passed validation "
                         f"({best.validation.tests_conclusive} tests, 0 mismatches).")
        else:
            lines.append("The compiler passes find nothing to improve in this function.")
        r = self.refactoring
        data = {"recommendation": best.strategy.name, "saving_pct": rec.saving_pct}
        if r and r["valid"]:
            combined = r["combined_cost"] if r["combined_valid"] else r["predicted_cost"]
            gain = round(100.0 * (base - combined) / base, 1) if base else 0.0
            lines.append(f"Refactoring I verified for you: {r['changes'][0].description}"
                         f"{' (and ' + str(len(r['changes']) - 1) + ' more)' if len(r['changes']) > 1 else ''}. "
                         f"With the compiler passes on top, predicted cost is {self._cost(combined)} ({gain}% below the "
                         f"original). Refactored code:\n{print_function(r['combined_func'] or r['func'])}")
            data.update({"refactoring_gain_pct": gain})
        tips = [s for s in self.suggestions if s.kind in ("cse", "unused", "heavy_op_in_loop", "unknown_call")][:3]
        if tips:
            lines.append("Other ideas:")
            lines += [f"  - line {s.line}: {s.message} {s.fix}" for s in tips]
        return CopilotAnswer("\n".join(lines), "optimize", data,
                             ["is it safe?", "what changed?", "why is this slow?"])

    # -- explain changes ------------------------------------------------------------------------

    def _answer_changes(self, q) -> CopilotAnswer:
        changes = self.fr.changes
        if not changes:
            return CopilotAnswer("The optimizer did not change anything: no pass found a safe, useful rewrite.",
                                 "changes")
        m = re.search(r"line\s+(\d+)", q.lower())
        shown = [c for c in changes if m and c.line == int(m.group(1))] if m else changes
        if m and not shown:
            lines_with = sorted({c.line for c in changes})
            return CopilotAnswer(f"Nothing was changed on line {m.group(1)}. Lines with changes: "
                                 f"{', '.join(map(str, lines_with))}.", "changes")
        lines = [f"{len(shown)} change(s)" + (f" on line {m.group(1)}" if m else "") + ":"]
        for c in shown[:12]:
            lines.append(f"  line {c.line} [{SHORT.get(c.pass_name, c.pass_name)}] {c.description}")
        if len(shown) > 12:
            lines.append(f"  ... and {len(shown) - 12} more")
        for p in dict.fromkeys(c.pass_name for c in shown):
            lines.append(self._pass_line(p))
        return CopilotAnswer("\n".join(lines), "changes", {"count": len(shown)},
                             ["is it safe?", "what is dead code elimination?"])

    # -- what-if --------------------------------------------------------------------------------

    def _answer_whatif(self, q) -> CopilotAnswer:
        names = _passes_in(q)
        t = q.lower()
        if not names:
            return CopilotAnswer("Name the passes, e.g. 'what if I apply constant propagation before strength "
                                 "reduction?' or 'what if I only use dead code elimination?'.", "whatif")
        if len(names) >= 2 and re.search(r"\b(before|after|order)\b", t):
            first, second = names[0], names[1]
            if re.search(r"\bafter\b", t) and "before" not in t:
                first, second = second, first
            res = self.twin.what_if_order(first, second)
            a, b = res["a_then_b"], res["b_then_a"]
            text = (f"{res['verdict']}\n  {SHORT[first]} then {SHORT[second]}: predicted {self._cost(a.metrics.predicted_cost)}\n"
                    f"  {SHORT[second]} then {SHORT[first]}: predicted {self._cost(b.metrics.predicted_cost)}\n"
                    "(each plan runs the two passes once, like a fixed compiler pipeline)")
            return CopilotAnswer(text, "whatif", {"verdict": res["verdict"]}, ["how can I optimize this function?"])
        w = self.twin.what_if(names)
        return CopilotAnswer(f"{w.question}\n{w.answer}", "whatif", {"saving_pct": w.vs_original_pct},
                             ["how can I optimize this function?"])

    # -- safety ---------------------------------------------------------------------------------

    def _answer_safety(self, q) -> CopilotAnswer:
        v = self.fr.validation
        lines = [f"Validation {v.summary()}."]
        if self.fr.rejected:
            lines.append("Rejected (they changed behaviour and were rolled back): "
                         + ", ".join(r.pass_name for r in self.fr.rejected))
        lines.append(f"Operations executed on the tests dropped {v.original_cost} -> {v.optimized_cost} "
                     f"({v.cost_reduction_pct}% fewer).")
        lines += [f"Warning: {w}" for w in v.warnings]
        lines.append("Honest limit: this is differential testing - strong evidence on boundary and random inputs, "
                     "not a formal proof." if self.level != "beginner" else
                     "This is a very thorough test, not a mathematical proof.")
        return CopilotAnswer("\n".join(lines), "safety", {"passed": v.passed}, ["what is differential testing?"])

    # -- selection / confidence -------------------------------------------------------------------

    def _answer_selection(self, q) -> CopilotAnswer:
        lines = ["Rule-based selector (features + a dry run of each pass):"]
        for r in self.rule_recs:
            lines.append(f"  {'RUN ' if r.selected else 'skip'} {r.pass_name:<24} confidence {r.confidence:.2f} - {r.reason}")
        if self.ml_recs:
            lines.append("ML selector (random forest on static features only):")
            for r in self.ml_recs:
                lines.append(f"  {'RUN ' if r.selected else 'skip'} {r.pass_name:<24} confidence {r.confidence:.2f}")
            agree = sum(1 for a, b in zip(self.rule_recs, self.ml_recs) if a.selected == b.selected)
            lines.append(f"The two selectors agree on {agree} of {len(self.rule_recs)} passes.")
        lines.append(knowledge.explain("confidence", self.level))
        return CopilotAnswer("\n".join(lines), "selection", {}, ["what is constant folding?"])

    # -- features ---------------------------------------------------------------------------------

    def _answer_features(self, q) -> CopilotAnswer:
        f = self.features
        lines = [f"{self.func_name}: {f.loop_count} loop(s), {f.branch_count} branch(es), {f.arithmetic_op_count} arithmetic "
                 f"operation(s) ({f.mul_div_op_count} multiply/divide/modulo), {f.constant_count} constant(s), "
                 f"{f.variable_count} variable(s), {f.function_call_count} call(s)."]
        if f.constant_assignment_count:
            lines.append(f"{f.constant_assignment_count} variable(s) are set to a constant - good material for constant propagation.")
        if f.loop_count:
            lines.append("Loops multiply every cost inside them, so they matter most for speed.")
        return CopilotAnswer("\n".join(lines), "features", f.to_dict(), ["why is this slow?"])

    # -- learning mode -------------------------------------------------------------------------------

    def _answer_learn(self, q) -> CopilotAnswer:
        topic = find_topic(q)
        if topic is None:
            return self._answer_theory(q)
        text = explain(topic, self.level)
        used = [c for c in self.fr.changes if c.pass_name == topic]
        if used:
            text += f"\nIn YOUR code this pass made {len(used)} change(s), e.g. line {used[0].line}: {used[0].description}"
        return CopilotAnswer(text, "learn", {"topic": topic},
                             ["explain simpler" if self.level != "beginner" else "explain in more detail"])

    # -- show the optimized code -----------------------------------------------------------------

    def _answer_show_code(self, q) -> CopilotAnswer:
        o = self.optimized_source()
        lines = []
        if o["saving_pct"] > 0:
            lines.append(f"Here is the version I would use. It is predicted to cost {self._cost(o['cost_after'])} instead of "
                         f"{self._cost(o['cost_before'])} ({o['saving_pct']}% lower) and I verified that it behaves the same "
                         f"as your original on boundary and random inputs ('{o['strategy']}'):")
        else:
            lines.append("Your code is already as cheap as I can safely make it, so I would keep it as it is:")
        lines.append(f"```{o['language']}\n{o['code'].rstrip()}\n```")
        if o["why"]:
            lines.append("Why - each change and the reason:")
            for w in o["why"]:
                lines.append(f"  * {w['title']} ({w['count']}x): {w['explanation']}")
                lines += [f"      {e}" for e in w["examples"][:2]]
        return CopilotAnswer("\n".join(lines), "show_code", {"code": o["code"], "language": o["language"],
                                                              "saving_pct": o["saving_pct"]},
                             ["is it safe?", "why is this slow?", "what changed?"])

    # -- open questions (theory) and refusals -------------------------------------------------------

    def _answer_theory(self, q) -> CopilotAnswer:
        """An in-scope question that none of the built-in intents matched."""
        if self.llm is not None:
            context = (f"Language {self.language}; function {self.func_name}; predicted cost {self.twin.baseline.predicted_cost:.0f}; "
                       f"best plan '{self.recommendation.experiment.strategy.name}' "
                       f"({self.recommendation.saving_pct}% lower, validated). Learner level: {self.level}.")
            try:
                text = self.llm.generate(theory_prompt(self.level, q, context, self.code), SYSTEM_PROMPT).strip()
                if text == OFF_TOPIC_TOKEN:
                    return CopilotAnswer(REFUSAL, "off_topic")
                return CopilotAnswer(text, "theory", {"llm": True},
                                     ["how can I optimize this function?", "what is constant folding?"])
            except LLMError as e:
                note = f"(The Gemini model could not answer: {e}.)"
            except Exception as e:
                note = f"(The Gemini model failed: {type(e).__name__}.)"
            return CopilotAnswer(f"{note}\n" + self._offline_hint(), "theory", {"llm_error": note})
        return CopilotAnswer(self._offline_hint(), "theory")

    def _offline_hint(self) -> str:
        names = ", ".join(info["title"] for info in TOPICS.values())
        return ("That is an open compiler-theory question and I only have built-in lessons for: " + names +
                ". Turn on the Gemini model (settings, or set GEMINI_API_KEY) to answer open questions, or ask "
                "about your own code, e.g. 'why is this slow?' or 'show me the optimized code'.")

    def _answer_unknown(self, q) -> CopilotAnswer:
        return self._answer_theory(q)

    def _answer_off_topic(self, q) -> CopilotAnswer:
        return CopilotAnswer(REFUSAL, "off_topic")