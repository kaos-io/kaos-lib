"""What the render refuses in the ``matrix=`` of a step, as the linter reports it.

Why: the platform's ``step()`` raises on each of these when the pipeline is rendered (docs/step-contract.md, section
12 of the platform contract); the linter says it earlier, with the step and the fix, in the same words. Every check is
here, so the rule that reports them (L-E06) and the ``when=`` check read one source.
"""
from __future__ import annotations

import math
import re

from .constants import (CONTEXT_CAP, MATRIX_AXIS_MAX, MATRIX_AXIS_PATTERN, MATRIX_ENTRY_CAP, MATRIX_INT_LIMIT,
                        MATRIX_MAX_ITEMS, MATRIX_MAX_LEDGER, MATRIX_MIN_BASE, MATRIX_REFUSED_KINDS, MATRIX_TEXT_PATTERN, RESULT_CAP)

_AXIS, _TEXT = re.compile(MATRIX_AXIS_PATTERN), re.compile(MATRIX_TEXT_PATTERN)
EXAMPLE = 'matrix={"lr": [0.01, 0.001], "batch": [16, 32]}'


def value_problem(where: str, value) -> str:
    """Why ``value`` cannot be a value of a combination, or ''."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > MATRIX_INT_LIMIT:
        return (f"{where} is the number {value}, which is beyond {MATRIX_INT_LIMIT} (2 to the power 53): a number that "
                f"large cannot be kept exactly. Write it as text, for example \"{value}\".")
    if isinstance(value, bool) or (isinstance(value, (int, float)) and math.isfinite(value)):
        return ""
    if isinstance(value, str):
        if _TEXT.match(value):
            return ""
        return (f"{where} is the text {value[:30]!r}. A text value is 1 to 64 letters, digits, spaces and the "
                f"characters . _ + / : = @ , ( ) [ ] # % ^ ~ * -")
    kind = {list: "a list", tuple: "a list", dict: "an object", type(None): "empty"}.get(type(value), type(value).__name__)
    return f"{where} is {kind}. A value is a number, true or false, or a short text."


def problems(label: str, matrix, kind, reads, produced_types, needs_matrix: bool, things=None) -> list:
    """``[(message, fix)]`` for the ``matrix=`` of one step. ``matrix`` is its literal value, ``kind`` and ``reads``
    are the literals of ``kind=`` and ``reads=`` (None when not known), ``produced_types`` the set of types in
    ``produces=`` (None when not known) and ``needs_matrix`` whether a step in ``needs=`` has ``matrix=`` itself, ``things`` how many entries ``inputs=`` and
    ``produces=`` hold together (None when not known)."""
    if not isinstance(matrix, dict) or not matrix:
        return [(f"{label}: matrix= is {matrix!r}. Write the values to try for each setting, for example "
                 f"{EXAMPLE}: the step runs once for each combination.", f"Write it like {EXAMPLE}.")]
    found, combinations = [], 1
    for axis, values in matrix.items():
        if not (isinstance(axis, str) and _AXIS.match(axis) and len(axis) <= MATRIX_AXIS_MAX):
            found.append((f"{label}: matrix= holds the name {axis!r}. A name is lowercase letters, digits and _, "
                          f"starting with a letter, at most {MATRIX_AXIS_MAX} characters: it is how the step reads "
                          "the value (step.params['lr']).", "Rename the setting, for example 'lr'."))
        elif isinstance(reads, (list, tuple)) and axis in reads:
            found.append((f"{label}: matrix= has the name {axis!r}, which is also a section the step reads (reads=). "
                          f"Rename one of them: the step would not know which {axis!r} it reads.",
                          "Rename the setting in matrix= or the section in reads=."))
        if not isinstance(values, (list, tuple)) or not values:
            found.append((f"{label}: matrix= gives {axis!r} the value {values!r}. Give a list with at least one value, "
                          f"for example {axis!r}: [1, 2].", f"Write {axis!r}: [<a value>, ...]."))
            continue
        combinations *= len(values)
        for value in values:
            problem = value_problem(f"{label}: matrix= value {value!r} of {axis!r}", value)
            if problem:
                found.append((problem, "Use numbers, true or false, or short texts."))
    if combinations > MATRIX_MAX_ITEMS:
        found.append((f"{label}: matrix= makes {combinations} combinations; a step runs at most {MATRIX_MAX_ITEMS}. "
                      "Remove values, or split the step.", f"Keep the number of combinations at {MATRIX_MAX_ITEMS} or fewer."))
    if kind in MATRIX_REFUSED_KINDS:
        found.append((f"{label}: a step of kind {kind} runs once, so it cannot have matrix=. Give the step the kind of "
                      "the work it does (transform, train, evaluate), or remove matrix=.",
                      "Give the step the kind of the work it does, or remove matrix=."))
    if produced_types and "dataset" in produced_types:
        found.append((f"{label}: a step with matrix= cannot produce a dataset: a dataset has one writer and one "
                      "version per run. Produce a model or an artifact from the matrix step, and let the step after "
                      "it write the dataset.", "Produce a model or an artifact here, and write the dataset in the next step."))
    if things is not None and things > MATRIX_MAX_LEDGER:
        found.append((f"{label}: a step with matrix= may read and write at most {MATRIX_MAX_LEDGER} things in all "
                      f"(inputs= and produces= together; it has {things}): up to {MATRIX_MAX_ITEMS} items hand back "
                      "what they read and wrote in one shared result. Read fewer inputs, or join what the step writes.",
                      f"Read and write at most {MATRIX_MAX_LEDGER} things in all."))
    if needs_matrix:
        found.append((f"{label}: a step with matrix= cannot need another step with matrix=: each combination would "
                      "need the matching one. Put a step between them that picks the combinations to use.",
                      "Put a step between them that picks the combinations to use."))
    return found


def when_reads_value(label: str, head: str) -> str:
    """The refusal of a ``when=`` that reads ``<matrix step>.<value>``."""
    return (f"{label}: when= reads a value of step {head!r}, which runs once for each combination of its matrix= and so "
            "has no one value. A when= may read a field of the run form, or a value of a step that runs once.")


def base_context_cap(needs: int) -> int:
    """What a step's context may cost before the results it needs are joined in, when one of them is a matrix step."""
    return CONTEXT_CAP - RESULT_CAP * (needs - 1) - MATRIX_ENTRY_CAP


def needs_problems(label: str, count: int, fanned: list) -> list:
    """``[(message, fix)]`` for a step that needs the matrix steps ``fanned``: ``count`` is the length of its needs=."""
    found = []
    if len(fanned) > 1:
        found.append((f"{label}: it needs two steps with matrix= ({', '.join(fanned)}). The results of all the items of "
                      "a matrix step share a large part of a step's context, so a step may need one of them. Put a "
                      "step between.", "Put a step between, so that this step needs only one step with matrix=."))
    if fanned and base_context_cap(count) < MATRIX_MIN_BASE:
        most = next(n for n in range(count, 0, -1) if base_context_cap(n) >= MATRIX_MIN_BASE)
        found.append((f"{label}: it needs {count} steps, one of them with matrix=; a step that needs a matrix step may "
                      f"need at most {most} steps in all. The items' results take {MATRIX_ENTRY_CAP // 1024} KiB of its "
                      "context. Join some of the steps it needs, or put a step between.",
                      f"Need at most {most} steps in all."))
    return found


def allow_failed_problems(label: str, value, has_matrix: bool) -> list:
    """``[(message, fix)]`` for ``matrix_allow_failed=``."""
    if value not in (True, False):
        return [(f"{label}: matrix_allow_failed={value!r} must be True or False.", "Write True or False.")]
    if value and not has_matrix:
        return [(f"{label}: matrix_allow_failed=True is for a step with matrix=: it lets the step after it run when "
                 "some items failed. Add matrix=, or remove matrix_allow_failed.",
                 "Add matrix=, or remove matrix_allow_failed.")]
    return []
