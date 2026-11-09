"""The warning rules (L-W01 .. L-W04): things that usually go wrong later, at run time or in review.

Why: warnings never fail the `pipeline-lint` status. They are advice, so each one is narrow, says what to do, and
the heuristic ones (L-W04) say they are heuristics.
"""
from __future__ import annotations

from typing import Iterable

from .constants import LONG_GPU_STEP_MINUTES
from .model import WARNING
from .pipeline_reader import UNKNOWN
from .registry import (NOT_RESUMABLE, OFF, Hit, LintContext, gpu_steps, parse_minutes, pretty_minutes, rule)


@rule("L-W01", "LongGpuStepNotResumable", WARNING,
      "Make the step resumable (resumable=True, saving checkpoints with kaos_lib.checkpoint), or shorten "
      "hpc_time_limit.")
def long_gpu_step_not_resumable(ctx: LintContext) -> Iterable[Hit]:
    hpc = ctx.catalogue.hpc
    for step in gpu_steps(ctx):
        limit = parse_minutes(step.value("hpc_time_limit", None))
        if limit is None or limit <= LONG_GPU_STEP_MINUTES or ctx.resumable(step) not in (OFF, NOT_RESUMABLE):
            continue
        if hpc is not None and limit > hpc.lane_max_minutes:
            continue   # L-E01 reports it as an error
        yield Hit(ctx.file, ctx.span(step.node("hpc_time_limit")),
                  f"Step '{step.name}' runs up to {pretty_minutes(limit)} and is not resumable. An interruption "
                  f"(a lost machine, the time limit) loses all its work.")


@rule("L-W02", "IdleTimeoutOff", WARNING,
      "Remove idle_timeout=0 to keep the default (a step with no GPU use and no new log line for 20 minutes is "
      "ended), or raise it, for example idle_timeout='40m'.")
def idle_timeout_off(ctx: LintContext) -> Iterable[Hit]:
    for step in gpu_steps(ctx):
        v = step.value("idle_timeout", None)
        if v is False or (v is not UNKNOWN and not isinstance(v, bool) and v is not None and str(v).strip() == "0"):
            yield Hit(ctx.file, ctx.span(step.node("idle_timeout")),
                      f"Step '{step.name}' turns the idle limit off. A hung step keeps its GPU, and its budget, "
                      f"until the time limit.")


@rule("L-W03", "UnpinnedDataset", WARNING,
      "Pin a version: use <dataset>@v1 (a released version) instead of @latest, so a run always reads the same "
      "data.")
def unpinned_dataset(ctx: LintContext) -> Iterable[Hit]:
    seen = set()
    if ctx.dataset is not None and "@latest" in ctx.dataset.value:
        yield Hit(ctx.dataset.file, ctx.dataset.span,
                  f"The dataset '{ctx.dataset.value}' follows the newest data: two runs of the same code can read "
                  f"different data.")
    for step in ctx.pipeline.steps:
        source = ctx.step_source(step)
        for file, span in (source.latest_refs if source else []):
            if (file, span) not in seen:
                seen.add((file, span))
                yield Hit(file, span, "A dataset reference uses @latest: a run reads whatever is newest at the "
                          "time, so results cannot be reproduced.")


@rule("L-W04", "NoMlflowOrModelNotRegistered", WARNING,
      "Log the run to MLflow in the training step (kaos_lib.mlflow.mlflow()) and register the model you keep. "
      "This check is a heuristic: it searches the step's code.")
def no_mlflow_or_model_not_registered(ctx: LintContext) -> Iterable[Hit]:
    training = [s for s in gpu_steps(ctx) if _is_training(s)]
    sources = [(s, ctx.step_source(s)) for s in training]
    for step, source in sources:
        if source is not None and source.found and not source.uses_mlflow:
            yield Hit(ctx.file, ctx.span(step.call), f"Step '{step.name}' looks like a training step, but its code "
                      f"has no MLflow logging, so its runs leave no metrics or parameters to compare.")
    found = [src for _, src in sources if src is not None and src.found]
    registers = any(ctx.step_source(s).registers_model for s in ctx.pipeline.steps if ctx.step_source(s))
    if found and not registers:
        yield Hit(ctx.file, ctx.span(training[0].call), "Training steps exist, but no step of the pipeline "
                  "registers a model, so a trained model is not kept in the registry.")


def _is_training(step) -> bool:
    reads = step.value("reads", [])
    name = step.name
    return (isinstance(reads, (list, tuple)) and "train" in reads) or (isinstance(name, str) and "train" in name)
