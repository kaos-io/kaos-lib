"""The `when=` of a step: a run-form field compared with a value, in plain words.

The grammar is the engine's (kubecore/authoring.py), word for word: `<field> == <value>` or `!=`, comparisons joined
with `and` / `or` (`and` first), no parentheses; the value is a bare word or number or a quoted string. Nothing here
runs anything: the text is only read.
"""
from __future__ import annotations

import re

EXAMPLE = 'when="mode != off"'
_NAME = r"[A-Za-z0-9_.-]+"
_COMPARE = rf"({_NAME})\s*(==|!=)\s*(\"[^\"]*\"|'[^']*'|{_NAME})"
_WHOLE = re.compile(rf"\s*{_COMPARE}(?:\s+(?:and|or)\s+{_COMPARE})*\s*")
_COMPARISON = re.compile(_COMPARE)


def fields(text) -> list | None:
    """The run-form fields the text compares, or None when it is not written as the grammar says."""
    if not (isinstance(text, str) and _WHOLE.fullmatch(text)):
        return None
    return [m.group(1) for m in _COMPARISON.finditer(text)]


def uses_workflow_syntax(text) -> bool:
    return isinstance(text, str) and ("{{" in text or "}}" in text)
