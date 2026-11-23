"""The warning rules (L-W01 .. L-W08): things that usually go wrong later, at run time or in review.

Why: warnings never fail the `pipeline-lint` status. They are advice, so each one is narrow, says what to do, and
the heuristic ones (L-W04) say they are heuristics.
"""
from __future__ import annotations

import ast
from typing import Iterable

from .model import WARNING
from .pipeline_reader import UNKNOWN
from .registry import Hit, LintContext, gpu_steps, rule, step_label
from .rules_errors import _needed_steps, _produced_types


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


@rule("L-W07", "DatasetProducerStaysOnCluster", WARNING,
      "Nothing is wrong, but the step will run on the cluster, not on an HPC (Slurm) site. To use HPC for the heavy "
      "work, make it an artifact (or a model) in one step and copy it into the dataset in a cheap second step.")
def dataset_producer_stays_on_cluster(ctx: LintContext) -> Iterable[Hit]:
    """A step that produces a dataset is never given an HPC class: gpu=True does not change that."""
    for step in ctx.pipeline.steps:
        node = step.node("produces")
        made = [el for el in getattr(node, "elts", ()) if isinstance(getattr(el, "func", None), ast.Name)
                and el.func.id == "dataset"]
        if step.is_gpu is True and made and not step.opaque:
            yield Hit(ctx.file, ctx.span(step.node("produces")),
                      f"{step_label(step)} asks for a GPU and produces a dataset. A step that produces a dataset runs "
                      f"on the cluster only: the run form offers it no HPC (Slurm) class.")


@rule("L-W08", "AllowedFailureReachesDataset", WARNING,
      "Remove matrix_allow_failed=True from the step, or make the step that writes the dataset read "
      "step.upstream(...) and call step.skip(reason) when too few items are ok.")
def allowed_failure_reaches_dataset(ctx: LintContext) -> Iterable[Hit]:
    """A step with matrix_allow_failed=True, followed (needs=, directly or through other steps) by a step that
    produces a dataset."""
    steps = [s for s in ctx.pipeline.steps if isinstance(s.name, str) and not s.opaque]
    needs = {s.name: _needed_steps(ctx, s) for s in steps}
    for step in steps:
        if step.value("matrix_allow_failed", None) is not True:
            continue
        after, grew = {step.name}, True
        while grew:
            more = {n for n, ns in needs.items() if ns & after} - after
            after |= more
            grew = bool(more)
        writers = [s.name for s in steps if s.name in after and s.name != step.name
                   and "dataset" in (_produced_types(s) or ())]
        if writers:
            named = ", ".join(repr(w) for w in writers)
            yield Hit(ctx.file, ctx.span(step.node("matrix_allow_failed")),
                      f"{step_label(step)} says matrix_allow_failed=True, and a step after it writes a dataset "
                      f"({named}). A failed training would still let the dataset be written and, if it is promoted, "
                      "become the latest one, because you said failed items are acceptable.")
