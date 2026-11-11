"""The info rules (L-I01 .. L-I03): facts worth knowing that need no action.

Why: they explain platform behaviour a client cannot see in pipeline.py (node sharing, learned limits), at no
cost to the status.
"""
from __future__ import annotations

from typing import Iterable

from .constants import SHORT_LIMIT_MINUTES
from .model import INFO
from .registry import Hit, LintContext, gpu_steps, parse_minutes, pretty_minutes, rule


@rule("L-I01", "NodeSharing", INFO,
      "Nothing to fix. Set walltime, for example walltime='4h', to let the step share a node.")
def node_sharing(ctx: LintContext) -> Iterable[Hit]:
    for step in gpu_steps(ctx):
        if step.value("walltime", None) is None:
            yield Hit(ctx.file, ctx.span(step.call),
                      f"Step '{step.name}' declares no time limit, so it cannot be offered as a guest on a node "
                      f"another job already holds on the HPC (Slurm) site.")


@rule("L-I02", "LearnedLimits", INFO,
      "Nothing to fix. A limit of 2 hours or more is kept exactly as you set it.")
def learned_limits(ctx: LintContext) -> Iterable[Hit]:
    for step in gpu_steps(ctx):
        limit = parse_minutes(step.value("walltime", None))
        if limit is not None and limit < SHORT_LIMIT_MINUTES:
            yield Hit(ctx.file, ctx.span(step.node("walltime")),
                      f"Step '{step.name}' has a limit of {pretty_minutes(limit)}. After a few runs the platform "
                      f"may ask the site for a shorter limit, to fit the step in sooner.")


@rule("L-I03", "Schedules", INFO, "Nothing to fix.",
      inactive="pipelines cannot declare a schedule yet, so there is nothing to check")
def schedules(ctx: LintContext) -> Iterable[Hit]:
    return ()
