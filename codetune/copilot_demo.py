"""
CodeTune Copilot in the terminal (Milestone 5/6).

    python copilot_demo.py                                  # paste YOUR code, then chat about it
    python copilot_demo.py mycode.c                         # use a file (.c .cpp .java .py)
    python copilot_demo.py mycode.py --ask "show me the optimized code"
    type mycode.c | python copilot_demo.py --stdin --language c      # code from a pipe
    python copilot_demo.py mycode.c --gemini                # use Gemini (needs GEMINI_API_KEY)
    python copilot_demo.py mycode.c --level advanced --ml --function work

Type 'quit' to leave. Try: help
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codetune.copilot import CopilotSession
from codetune.frontend.detect import detect_language

EXT_LANG = {".py": "python", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".java": "java"}


def read_pasted_code() -> str:
    print("Paste your code now. Finish with a line that contains only END (or press Ctrl+Z then Enter on Windows / Ctrl+D).")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="CodeTune Copilot")
    ap.add_argument("source_file", nargs="?", help="source file; omit to paste code interactively")
    ap.add_argument("--stdin", action="store_true", help="read the code from standard input")
    ap.add_argument("--language", choices=["python", "c", "cpp", "java"], help="override language detection")
    ap.add_argument("--function")
    ap.add_argument("--level", default="beginner", choices=["beginner", "intermediate", "advanced"])
    ap.add_argument("--ask", action="append", help="ask a question and exit (repeatable)")
    ap.add_argument("--ml", action="store_true", help="also show the ML selector's opinion (trains it if needed)")
    ap.add_argument("--gemini", action="store_true", help="use Gemini for open questions (GEMINI_API_KEY)")
    args = ap.parse_args()

    if args.stdin:
        code, lang, source_name = sys.stdin.read(), args.language, "<stdin>"
    elif args.source_file:
        if not os.path.exists(args.source_file):
            sys.exit(f"File not found: {args.source_file}\n(check the path - sample files live in the 'samples' folder)")
        ext = os.path.splitext(args.source_file)[1].lower()
        lang = args.language or EXT_LANG.get(ext)
        with open(args.source_file, encoding="utf-8") as fh:
            code = fh.read()
        source_name = args.source_file
    else:
        code, lang, source_name = read_pasted_code(), args.language, "<pasted code>"
    if not code.strip():
        sys.exit("No code given.")
    lang = lang or detect_language(code)

    ml = llm = None
    if args.ml:
        from codetune.ml import MLPassSelector
        print("Loading ML selector (trains once if no saved model)...")
        ml = MLPassSelector.load_or_train()
    if args.gemini:
        from codetune.copilot.llm import GeminiClient
        llm = GeminiClient()
        if not llm.available:
            print("Warning: GEMINI_API_KEY is not set - running in offline mode.\n"
                  "  PowerShell: $env:GEMINI_API_KEY = 'your key'     cmd: set GEMINI_API_KEY=your key")
            llm = None
        else:
            print(f"Gemini enabled ({llm.model}): your questions and a summary of your code are sent to Google.")

    try:
        session = CopilotSession(code, lang, args.function, level=args.level, ml_selector=ml, llm=llm)
    except ValueError as e:
        sys.exit(f"Could not analyse {source_name}: {e}")

    print(f"\nCodeTune Copilot - {source_name} ({lang}), function '{session.func_name}', level {session.level}")
    for a in session.alerts():
        print(f"  ! {a}")

    if args.ask:
        for q in args.ask:
            print(f"\n> {q}\n{session.ask(q).text}")
        return

    print("\nAsk me anything (type 'help' or 'quit').")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in ("quit", "exit", "q"):
            break
        if q:
            ans = session.ask(q)
            print(ans.text)
            if ans.followups:
                print("\n  you could also ask: " + " | ".join(ans.followups))


if __name__ == "__main__":
    main()