"""The warning rules (L-W01 .. L-W05): things that usually go wrong later, at run time or in review.

Why: warnings never fail the `pipeline-lint` status. They are advice, so each one is narrow, says what to do, and
the heuristic ones (L-W04) say they are heuristics.
"""
from __future__ import annotations

from typing import Iterable

from .constants import LONG_GPU_STEP_MINUTES
from .model import WARNING
from .pipeline_reader import UNKNOWN
from .registry import (DECLARED, NOT_VERIFIED, OFF, Hit, LintContext, gpu_steps, parse_minutes, pretty_minutes, rule)


@rule("L-W01", "LongGpuStepNotResumable", WARNING,
      "Make the step resumable (resumable=True, saving checkpoints with kaos_lib.checkpoint), or shorten "
      "walltime.")
def long_gpu_step_not_resumable(ctx: LintContext) -> Iterable[Hit]:
    hpc = ctx.catalogue.hpc
    for step in gpu_steps(ctx):
        limit = parse_minutes(step.value("walltime", None))
        if limit is None or limit <= LONG_GPU_STEP_MINUTES or ctx.resumable(step) not in (OFF, NOT_VERIFIED):
            continue
        if hpc is not None and limit > hpc.lane_max_minutes:
            continue   # L-E01 reports it as an error
        yield Hit(ctx.file, ctx.span(step.node("walltime")),
                  f"Step '{step.name}' runs up to {pretty_minutes(limit)} and is not resumable "
                  f"({'set not resumable' if ctx.resumable(step) == OFF else 'the platform recorded that its last continuation did not resume'}). "
                  f"An interruption (a lost machine, the time limit) loses all its work.")


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


@rule("L-W03", "DatasetVersionInCode", WARNING,
      "Declare the dataset in inputs=[...] in pipeline.py and read it with step.input(): the version is chosen on the "
      "run form, never in step code.")
def dataset_version_in_code(ctx: LintContext) -> Iterable[Hit]:
    seen = set()
    for step in ctx.pipeline.steps:
        source = ctx.step_source(step)
        for file, span in (source.version_refs if source else []):
            if (file, span) not in seen:
                seen.add((file, span))
                yield Hit(file, span, "This string names a dataset and a version. A step reads only the versions the "
                          "run pinned, so a version written in code is either ignored or refused.")


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


@rule("L-W05", "DeclaredResumableDidNotResume", WARNING,
      "Make the step load its checkpoint and continue from it: save into $KAOS_CHECKPOINT_DIR (or with "
      "kaos_lib.checkpoint) and load it when the step starts, so a continuation gets past the checkpoint it started "
      "from.")
def declared_resumable_did_not_resume(ctx: LintContext) -> Iterable[Hit]:
    """The platform's evidence says a continuation of a step that declares resumable did not get past its checkpoint."""
    for step in gpu_steps(ctx):
        recorded = ctx.evidence(step)
        if ctx.resumable(step) != DECLARED or recorded is None or recorded.verified:
            continue
        when = f" on {recorded.since}" if recorded.since else ""
        yield Hit(ctx.file, ctx.span(step.node("resumable")),
                  f"Step '{step.name}' declares resumable, but the platform recorded{when} that a continuation of "
                  f"it did not resume: {recorded.reason or 'it made no progress past its checkpoint'}. A step that "
                  f"restarts from zero on every continuation does not get any further.")
