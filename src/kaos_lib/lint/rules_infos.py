"""The info rules (L-I01 .. L-I03): facts worth knowing that need no action.

Why: they explain platform behaviour a client cannot see in pipeline.py (node sharing, learned limits), at no
cost to the status.
"""
from __future__ import annotations

from typing import Iterable

from .model import INFO
from .registry import Hit, LintContext, rule


@rule("L-I04", "StepsBuiltInALoop", INFO,
      "Nothing to fix. To have every check read a step, write it out with a literal name; or run the pipeline file "
      "through kaosctl render, which builds the steps.")
def steps_built_in_a_loop(ctx: LintContext) -> Iterable[Hit]:
    """The checks that read a step's arguments (the kind it declares, the datasets it reads and writes, its folder)
    cannot read a step whose name is not a literal. Say so once, so that a clean report is not taken for more."""
    unread = [s for s in ctx.pipeline.steps if not isinstance(s.name, str)]
    if unread:
        lines = ", ".join(str(s.call.lineno) for s in unread[:5]) + (", ..." if len(unread) > 5 else "")
        yield Hit(ctx.file, ctx.span(unread[0].call),
                  f"{len(unread)} step(s) are built in a loop or a call (line {lines}), so their name is not known "
                  f"here and the checks that read a step's arguments did not look at them.")


@rule("L-I03", "Schedules", INFO, "Nothing to fix.",
      inactive="pipelines cannot declare a schedule yet, so there is nothing to check")
def schedules(ctx: LintContext) -> Iterable[Hit]:
    return ()
