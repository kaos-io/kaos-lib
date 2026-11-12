"""The `when=` of a step: a run-form field, or a value of a step it needs, compared with a text, in plain words.

The grammar is the engine's (kubecore/authoring.py), word for word: `<name> == <value>` or `!=`, comparisons joined
with `and` / `or` (`and` first), no parentheses; <name> is a field of the run form or `<step>.<value>`; the value is
a bare word or number or a quoted string. Nothing here runs anything: the text is only read.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal

EXAMPLE = 'when="mode != off"'
FORMS = ('when="mode != off" (a field of the run form) or when="evaluate.passed == true" (a value that the step '
         '"evaluate", which this step needs, handed on with step.result(passed=...))')
ALLOWED = ("A condition compares one name with a text, with == or != and nothing else, for example " + FORMS + ". "
           "Join comparisons with and / or; no parentheses, no < or >.")
VALUE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")     # what step.result(<value>=...) can be given
_NAME = r"[A-Za-z0-9_.-]+"
_COMPARE = rf"({_NAME})\s*(==|!=)\s*(\"[^\"]*\"|'[^']*'|{_NAME})"
_WHOLE = re.compile(rf"\s*{_COMPARE}(?:\s+(?:and|or)\s+{_COMPARE})*\s*")
_COMPARISON = re.compile(_COMPARE)


def fields(text) -> list | None:
    """The names the text compares (run-form fields, or `<step>.<value>`), or None when it is not written as the grammar says."""
    if not (isinstance(text, str) and _WHOLE.fullmatch(text)):
        return None
    return [m.group(1) for m in _COMPARISON.finditer(text)]


def uses_workflow_syntax(text) -> bool:
    return isinstance(text, str) and ("{{" in text or "}}" in text)


def comparisons(text) -> list | None:
    """The (name, operator, text) of every comparison, or None when the text is not written as the grammar says."""
    if not (isinstance(text, str) and _WHOLE.fullmatch(text)):
        return None
    out = []
    for m in _COMPARISON.finditer(text):
        value = m.group(3)
        out.append((m.group(1), m.group(2), value[1:-1] if value[0] in "\"'" else value))
    return out


MAX_EXACT_INTEGER = 2 ** 53          # a result's number is a double: above this an integer is not exact
_JSON_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?\Z")
_LOOKS_NUMERIC = re.compile(r"[+-]?([0-9][0-9_]*\.?[0-9_]*|\.[0-9]+)([eE][+-]?[0-9]+)?\Z")


def has_control_character(text) -> bool:
    return isinstance(text, str) and any(ord(c) < 32 or ord(c) == 127 for c in text)


def value_problem(text: str) -> str:
    """Why a text compared with a step's value cannot be matched reliably, or ''. The same rule as the engine's
    (kubecore/step_contract.py when_text_problem): a number or a boolean value is compared by its JSON text, so a text
    that looks like one but is not written as JSON writes it would never match."""
    if has_control_character(text):
        return "it holds a control character (a line break, a tab): write the text on one line"
    if text.lower() in ("true", "false", "null") and text not in ("true", "false", "null"):
        return "write %s in lowercase: a true or false value is compared as the word true or false" % text.lower()
    if _JSON_NUMBER.match(text):
        if math.isinf(float(text)):
            return "the number is too large for a result to hold"
        if re.fullmatch(r"-?[0-9]+", text) and abs(int(text)) > MAX_EXACT_INTEGER:
            return ("an integer above %d is not held exactly by a result: compare a smaller number, or hand on the "
                    "value as text" % MAX_EXACT_INTEGER)
        return ""
    if _LOOKS_NUMERIC.match(text):
        return "it looks like a number but is not written as one: write it as JSON writes it (for example 0.5, 1, -3 or 1e-5)"
    return ""
