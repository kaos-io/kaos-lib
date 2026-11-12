"""`kaosctl lint --fix`: the mechanical part of moving a pipeline.py to the step contract of kaos-lib 0.5.

Why: three changes to every `step()` call are the same in every app, so a person should not type them: rename
`hpc_time_limit=` to `walltime=`, remove `outputs=`, and give a step that has no `kind=` one. A fourth is in
`config/config.yaml`: the `platform` config group is gone, so its line in the defaults is removed. The kind is a choice only
the author can make, so the fix writes a placeholder that lists the six kinds and is not one of them: the check keeps
failing until a kind is chosen. Nothing else in the file is touched, and step code is never rewritten.

Static: the file is parsed, never run. The edits are made on the text at the positions the parser gives, so comments
and layout stay as they are.
"""
from __future__ import annotations

from .constants import KIND_PLACEHOLDER
from .pipeline_reader import read_pipeline
from .project_reader import PLATFORM_DEFAULT
from .source import buffer_source, parse_python

OLD_TIME, NEW_TIME, OUTPUTS = "hpc_time_limit", "walltime", "outputs"
_BLANK = b" \t\r\n"


def _offsets(data: bytes) -> list:
    """The byte offset at which each line starts (line numbers are 1-based, as the parser's)."""
    starts, at = [0], data.find(b"\n")
    while at != -1:
        starts.append(at + 1)
        at = data.find(b"\n", at + 1)
    return starts


def _removal(data: bytes, start: int, end: int, first: int) -> tuple:
    """The span to delete so that the argument at [start, end) goes with exactly one of its commas.

    `first` is where the call's arguments begin: an argument that is not the first takes the comma before it.
    """
    before = start
    while before > first and data[before - 1:before] in (b" ", b"\t", b"\r", b"\n"):
        before -= 1
    if before > first and data[before - 1:before] == b",":
        return before - 1, end
    after = end
    while after < len(data) and data[after:after + 1] in (b" ", b"\t"):
        after += 1
    if data[after:after + 1] == b",":
        after += 1
        while after < len(data) and data[after:after + 1] in (b" ", b"\t"):
            after += 1
    return start, after


def fix_pipeline(text: str, rel: str = "pipeline.py") -> tuple:
    """`(new text, changes)`: `changes` is one line per edit, in file order; the text is unchanged when it is empty
    or when the file cannot be parsed."""
    src = buffer_source(text, rel)
    if parse_python(src) is None:
        return text, []
    data, edits, changes = text.encode("utf-8"), [], []
    starts = _offsets(data)

    def at(line: int, col: int) -> int:
        return starts[line - 1] + col

    for step in read_pipeline(src).steps:
        label = f"line {step.call.lineno}: step {step.name!r}" if isinstance(step.name, str) else \
            f"line {step.call.lineno}"
        first = at(step.call.func.end_lineno, step.call.func.end_col_offset) + 1
        for kw in step.unknown_keywords:
            start = at(kw.lineno, kw.col_offset)
            if kw.arg == OLD_TIME and NEW_TIME in step.args:
                changes.append(f"{label}: {OLD_TIME}= left as it is: walltime= is already there. Remove the one you "
                               "do not mean")
            elif kw.arg == OLD_TIME:
                edits.append((start, start + len(OLD_TIME), NEW_TIME.encode()))
                changes.append(f"{label}: {OLD_TIME}= renamed to {NEW_TIME}=")
            elif kw.arg == OUTPUTS:
                begin, end = _removal(data, start, at(kw.value.end_lineno, kw.value.end_col_offset), first)
                edits.append((begin, end, b""))
                changes.append(f"{label}: {OUTPUTS}= removed (hand values on with step.result(...))")
        if step.opaque or "kind" in step.args or "name" not in step.args:
            continue
        name = step.args["name"]
        edits.append((at(name.end_lineno, name.end_col_offset),) * 2 + (f', kind="{KIND_PLACEHOLDER}"'.encode(),))
        changes.append(f"{label}: kind= added as a placeholder; choose one of the kinds it lists")
    for start, end, new in sorted(edits, reverse=True):
        data = data[:start] + new + data[end:]
    return data.decode("utf-8"), changes


def fix_config(text: str) -> tuple:
    """`(new text, changes)` for config/config.yaml: the `- platform: ...` line of its defaults is removed. The
    platform no longer has that config group."""
    kept, changes = [], []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        if PLATFORM_DEFAULT.match(line.rstrip("\r\n")):
            changes.append(f"line {number}: the `platform` config group removed from the defaults")
        else:
            kept.append(line)
    return "".join(kept), changes
