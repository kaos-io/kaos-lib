"""The `when=` of a step: a run-form field, or a value of a step it needs, compared with a text, in plain words.

The grammar is the engine's (kubecore/authoring.py), word for word: `<name> == <value>` or `!=`, comparisons joined
with `and` / `or` (`and` first), no parentheses; <name> is a field of the run form or `<step>.<value>`; the value is
a bare word or number or a quoted string. Nothing here runs anything: the text is only read.
"""
from __future__ import annotations

import re

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
