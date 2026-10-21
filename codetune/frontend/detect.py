"""Guess the source language of a pasted snippet (used when the user does not say)."""

import re


def detect_language(code: str) -> str:
    if re.search(r"^\s*def\s+\w+\s*\(.*\)\s*(->\s*[\w\[\], ]+)?\s*:", code, re.M):
        return "python"
    if re.search(r"#include|\bstd::|\busing\s+namespace\b|\bcout\b", code):
        return "cpp" if re.search(r"std::|cout|using\s+namespace|\bclass\b|template\s*<", code) else "c"
    if re.search(r"\bclass\s+\w+", code) and re.search(r"\b(public|private|static|void|int|double|boolean)\b", code):
        return "java"
    return "c" if re.search(r"[{};]", code) else "python"