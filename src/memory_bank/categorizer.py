"""Lightweight rule-based message categorizer.

Assigns a single category to assistant messages based on keyword heuristics.
No external dependencies, works fully offline.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, list[str]]] = [
    ("bugfix", [
        r"\bfix(ed|es|ing)?\b",
        r"\bbug\b",
        r"\bregression\b",
        r"\bpatch(ed|es|ing)?\b",
        r"\bhot\s*fix\b",
        r"\bdebugg(ed|ing)\b",
        r"\berror\s+resolved\b",
    ]),
    ("feature", [
        r"\bfeat(ure)?\b",
        r"\bimplement(ed|s|ing)?\b",
        r"\bnew\s+(feature|functionality|endpoint|command|option|flag|tool)\b",
        r"\bintroduc(ed|ing|es)\b",
        r"\badd(ed|ing|s)?\s+support\s+for\b",
    ]),
    ("refactor", [
        r"\brefactor(ed|s|ing)?\b",
        r"\bclean(ed)?\s*up\b",
        r"\breorganiz(ed|ing|es)?\b",
        r"\bextract(ed|ing|s)?\s+(class|function|method|module)\b",
        r"\bsimplif(y|ied|ying)\b",
    ]),
    ("decision", [
        r"\bdecid(ed|ing)?\b",
        r"\bgoing\s+with\b",
        r"\bchos(e|en|ing)\b",
        r"\btrade.?off\b",
        r"\bdesign\s+decision\b",
        r"\barchitectur(e|al)\s+(decision|choice|approach)\b",
    ]),
    ("research", [
        r"\bexplor(e|ed|ing)\b",
        r"\binvestigat(e|ed|ing)\b",
        r"\banalyz(e|ed|ing)\b",
        r"\bexamin(e|ed|ing)\b",
        r"\baccording\s+to\s+(the\s+)?(docs?|documentation|spec|source|code)\b",
        r"\b(the\s+)?(docs?|documentation|spec)\s+(say|says|shows?|indicates?|states?)\b",
        r"\bhow\s+(it|this|they)\s+work(s)?\b",
        r"\blook(ed|ing)\s+(at|into)\s+(the\s+)?(code|source|docs?|documentation|repo|codebase)\b",
    ]),
]

_compiled: list[tuple[str, list[re.Pattern]]] = [
    (cat, [re.compile(p, re.IGNORECASE) for p in pats])
    for cat, pats in _PATTERNS
]


def categorize(content: str) -> str | None:
    """
    Classify message content into a category using keyword heuristics.

    Returns one of: ``"bugfix"``, ``"feature"``, ``"refactor"``,
    ``"decision"``, ``"research"``, or ``None`` if no pattern matches.

    Only intended for assistant messages — callers should filter by role.
    Categories are tried in order; first match wins.
    """
    if not content:
        return None
    for category, patterns in _compiled:
        for pat in patterns:
            if pat.search(content):
                return category
    return None
