"""The error rules (L-E01 .. L-E06): problems the platform would refuse at render or at submit.

Why: these fail the `pipeline-lint` status, so each one is something the enhancer, the step() validators or the
HPC (Slurm) admission would reject anyway; the linter says so earlier, with the step and a fix.
"""
from __future__ import annotations

import ast
import re
from typing import Iterable

from .constants import (COMPUTE_CLASS_KEYS, DISK_PATTERN, IDENTITY_NAMES, POD_PATCH_NAMES, RESERVED_TEMPLATE_NAMES,
                        STEP_NAME_PATTERN, TIME_PATTERN)
from .model import ERROR
from .pipeline_reader import UNKNOWN, literal
from .registry import (DECLARED, NOT_VERIFIED, OFF, REQUIRES_CLASSES, REQUIRES_CONTINUATIONS, REQUIRES_HPC, STATIC,
                       VERIFIED, Hit, LintContext, gpu_steps, parse_minutes, pretty_minutes,
                       rule, runs_needed)

_STEP_NAME, _DISK, _TIME = re.compile(STEP_NAME_PATTERN), re.compile(DISK_PATTERN), re.compile(TIME_PATTERN)
_EVERY = re.compile(r"^([0-9]+)([mh]?)$")
_DEPENDS_TOKEN = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_-]*)(?:\.(?:Succeeded|Failed|Skipped|Omitted|Errored|Daemoned))?")


def _step_label(step) -> str:
    return f"Step '{step.name}'" if isinstance(step.name, str) else "A step"


@rule("L-E01", "TooLongNotResumable", ERROR,
      "Make the step resumable (resumable=True, saving checkpoints with kaos_lib.checkpoint) or set "
      "hpc_time_limit to the longest run or less.", requires=(REQUIRES_HPC,))
def too_long_not_resumable(ctx: LintContext) -> Iterable[Hit]:
    lane = ctx.catalogue.hpc.lane_max_minutes
    for step in gpu_steps(ctx):
        limit = parse_minutes(step.value("hpc_time_limit", None))
        state = ctx.resumable(step)
        if limit is None or limit <= lane or state not in (OFF, NOT_VERIFIED):
            continue
        how = "is set not resumable" if state == OFF else "is not declared resumable and the platform recorded " \
            f"that its last continuation did not resume ({ctx.evidence(step).reason or 'no reason given'})"
        yield Hit(ctx.file, ctx.span(step.node("hpc_time_limit")),
                  f"{_step_label(step)} asks for a time limit of {pretty_minutes(limit)}, but the longest run on "
                  f"the HPC (Slurm) site is {pretty_minutes(lane)}, and the step {how}, so it would be cut off. "
                  f"The platform refuses it at submit.")


@rule("L-E02", "TooLongBeyondContinuations", ERROR,
      "Shorten hpc_time_limit, or split the work into steps that each fit within the runs allowed.",
      requires=(REQUIRES_HPC, REQUIRES_CONTINUATIONS))
def too_long_beyond_continuations(ctx: LintContext) -> Iterable[Hit]:
    lane, cap = ctx.catalogue.hpc.lane_max_minutes, ctx.catalogue.max_continuations
    for step in gpu_steps(ctx):
        limit = parse_minutes(step.value("hpc_time_limit", None))
        if limit is None or ctx.resumable(step) not in (DECLARED, VERIFIED, STATIC):
            continue
        runs = runs_needed(limit, lane)
        if runs > cap + 1:
            yield Hit(ctx.file, ctx.span(step.node("hpc_time_limit")),
                      f"{_step_label(step)} is resumable, but a time limit of {pretty_minutes(limit)} needs {runs} "
                      f"runs of at most {pretty_minutes(lane)}, and a step continues at most {cap} times "
                      f"({cap + 1} runs in all, {pretty_minutes(lane * (cap + 1))}). The platform refuses it.")


@rule("L-E03", "UnknownClass", ERROR,
      "Pin one of the classes your project offers (the step's class dropdown lists them), or remove the pin.",
      requires=(REQUIRES_CLASSES,))
def unknown_class(ctx: LintContext) -> Iterable[Hit]:
    known = set(ctx.catalogue.classes)
    for d in ctx.pipeline.dicts:
        for key, value in zip(d.keys, d.values):
            if key is not None and literal(key) in COMPUTE_CLASS_KEYS:
                name = literal(value)
                if isinstance(name, str) and name not in known:
                    yield Hit(ctx.file, ctx.span(value),
                              f"The compute class '{name}' is not one your project can use "
                              f"(available: {', '.join(sorted(known))}). The render is refused.")


@rule("L-E04", "ClientIdentity", ERROR,
      "Remove it: the platform chooses the account every step runs as and places the pod. Use step(...) arguments "
      "and compute classes instead.")
def client_identity(ctx: LintContext) -> Iterable[Hit]:
    forbidden = IDENTITY_NAMES + POD_PATCH_NAMES
    for call in ctx.pipeline.calls:
        for kw in call.keywords:
            if kw.arg in forbidden:
                yield Hit(ctx.file, ctx.span(kw), _identity_message(kw.arg))
            if kw.arg == "name" and literal(kw.value) in RESERVED_TEMPLATE_NAMES:
                yield Hit(ctx.file, ctx.span(kw.value), _reserved_message(literal(kw.value)))
    for d in ctx.pipeline.dicts:
        for key in d.keys:
            if key is not None and literal(key) in forbidden:
                yield Hit(ctx.file, ctx.span(key), _identity_message(literal(key)))
    for step in ctx.pipeline.steps:
        if step.name in RESERVED_TEMPLATE_NAMES:
            yield Hit(ctx.file, ctx.span(step.node("name")), _reserved_message(step.name),
                      "Rename the step.")


def _identity_message(name: str) -> str:
    if name in IDENTITY_NAMES:
        return (f"'{name}' gives a pipeline or step its own service account. The platform chooses the account "
                f"every step runs as, so the render is refused.")
    return (f"'{name}' patches a pod's spec. The platform sizes and places pods itself, so the render is "
            f"refused.")


def _reserved_message(name: str) -> str:
    return (f"'{name}' is a template name the platform reserves for its HPC (Slurm) follower, so the render is "
            f"refused.")


@rule("L-E05", "DependencyOrProducer", ERROR,
      "Define each step before the steps that need it, pass the step variables in needs=[...], give each step a "
      "unique lowercase name, and read only sections that exist in config/.")
def dependency_or_producer(ctx: LintContext) -> Iterable[Hit]:
    for block in ctx.pipeline.blocks:
        yield from _names(ctx, block)
        yield from _needs(ctx, block)
    yield from _reads(ctx)
    yield from _depends_cycles(ctx)


def _names(ctx, block) -> Iterable[Hit]:
    seen = set()
    for step in block.steps:
        name = step.name
        if name is UNKNOWN or "name" not in step.args:
            continue
        node = ctx.span(step.node("name"))
        if not _STEP_NAME.match(name):
            yield Hit(ctx.file, node, f"The step name '{name}' is not valid. Use lowercase letters, digits and "
                      f"hyphens, with no hyphen at the start or end (for example 'model-evaluation'): the name "
                      f"becomes the step's template, its steps/<folder> and its image.")
        elif name in seen:
            yield Hit(ctx.file, node, f"Two steps are named '{name}'. Every step needs its own name: it is the "
                      f"step's identity in the pipeline and its image.", "Rename one of the steps.")
        seen.add(name)


def _needs(ctx, block) -> Iterable[Hit]:
    defined, later = set(), {s.var for s in block.steps if s.var and not s.dynamic}
    for step in block.steps:
        needs = step.node("needs")
        if isinstance(needs, (ast.List, ast.Tuple)) and not step.dynamic:
            for el in needs.elts:
                yield from _need(ctx, step, el, defined, later)
        if step.var and not step.dynamic:
            defined.add(step.var)
            later.discard(step.var)


def _need(ctx, step, el, defined, later) -> Iterable[Hit]:
    label = _step_label(step)
    if isinstance(el, ast.Constant) and isinstance(el.value, str):
        yield Hit(ctx.file, ctx.span(el), f"{label} lists '{el.value}' in needs, as text. needs takes the step "
                  f"variables, not their names.", f"Use needs=[{el.value.replace('-', '_')}] with the variable "
                  f"the step is assigned to.")
    elif isinstance(el, ast.Name) and el.id not in defined:
        if el.id in later or el.id == step.var:
            yield Hit(ctx.file, ctx.span(el), f"{label} needs '{el.id}', which is defined after it (or is the "
                      f"step itself). A step can only need a step defined earlier.",
                      f"Move the line that defines '{el.id}' above this step.")
        elif el.id not in ctx.pipeline.bound_names:
            yield Hit(ctx.file, ctx.span(el), f"{label} needs '{el.id}', which is not defined anywhere in "
                      f"pipeline.py.", f"Define it first: {el.id} = step(...), or fix the name.")


def _reads(ctx) -> Iterable[Hit]:
    if ctx.sections is None:
        return
    for step in ctx.pipeline.steps:
        reads = step.node("reads")
        if isinstance(reads, (ast.List, ast.Tuple)):
            for el in reads.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str) and el.value not in ctx.sections:
                    yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)} reads the config section "
                              f"'{el.value}', which does not exist in config/ (sections: "
                              f"{', '.join(sorted(ctx.sections))}).")


def _depends_cycles(ctx) -> Iterable[Hit]:
    """A cycle in the `depends` strings of raw Hera tasks (name= and depends= given as text)."""
    graph, where = {}, {}
    for call in ctx.pipeline.calls:
        kws = {k.arg: k.value for k in call.keywords if k.arg}
        name, depends = literal(kws.get("name")), literal(kws.get("depends"))
        if isinstance(name, str) and isinstance(depends, str):
            graph[name] = {t for t in _DEPENDS_TOKEN.findall(depends)}
            where[name] = kws["depends"]
    for name in sorted(graph):
        if _reaches(graph, name, name):
            yield Hit(ctx.file, ctx.span(where[name]), f"The task '{name}' depends on itself through its "
                      f"'depends' chain: a pipeline cannot run in a cycle.", "Remove one dependency of the cycle.")


def _reaches(graph, start, target) -> bool:
    seen, stack = set(), list(graph.get(start, ()))
    while stack:
        n = stack.pop()
        if n == target:
            return True
        if n not in seen:
            seen.add(n)
            stack.extend(graph.get(n, ()))
    return False


@rule("L-E06", "RefusedArgument", ERROR,
      "Fix the argument as the message says; step() raises on it when the pipeline is rendered.")
def refused_argument(ctx: LintContext) -> Iterable[Hit]:
    for step in ctx.pipeline.steps:
        yield from _unknown_arguments(ctx, step)
        if step.opaque:
            continue
        yield from _disk(ctx, step)
        yield from _time_arguments(ctx, step)
        yield from _every_arguments(ctx, step)


def _unknown_arguments(ctx, step) -> Iterable[Hit]:
    for kw in step.unknown_keywords:
        fix = "Use hpc_time_limit for the HPC (Slurm) time limit." if kw.arg == "walltime" else \
            "Remove it or check the name: step() accepts name, reads, gpu, needs, outputs, when, disk, " \
            "hpc_time_limit, resumable, checkpoint_every and idle_timeout."
        yield Hit(ctx.file, ctx.span(kw), f"step() has no argument '{kw.arg}', so the render fails.", fix)
    if not step.opaque and "name" not in step.args:
        yield Hit(ctx.file, ctx.span(step.call), "step() is called without a name.", "Give the step a name.")


def _disk(ctx, step) -> Iterable[Hit]:
    v = step.value("disk", None)
    if v is not UNKNOWN and v is not None and not (isinstance(v, str) and _DISK.match(v)):
        yield Hit(ctx.file, ctx.span(step.node("disk")), f"{_step_label(step)}: disk={v!r} is not a quantity. Use a "
                  f"string like '20Gi': digits and an optional Ki, Mi, Gi, Ti, K, M, G or T.")


def _time_arguments(ctx, step) -> Iterable[Hit]:
    limit, resumable, gpu = step.value("hpc_time_limit", None), step.value("resumable", None), step.is_gpu
    if limit is not UNKNOWN and limit is not None:
        if not (isinstance(limit, str) and _TIME.match(limit)):
            yield Hit(ctx.file, ctx.span(step.node("hpc_time_limit")), f"{_step_label(step)}: "
                      f"hpc_time_limit={limit!r} must be minutes or hours as text, like '90m', '12h' or '720'.")
        elif gpu is False:
            yield Hit(ctx.file, ctx.span(step.node("hpc_time_limit")), f"{_step_label(step)}: hpc_time_limit only "
                      f"applies to gpu=True steps; only GPU steps run on the HPC (Slurm) site.",
                      "Add gpu=True, or remove hpc_time_limit.")
    if resumable is UNKNOWN or resumable is None or resumable is False:
        return
    ok = resumable is True or (isinstance(resumable, str) and _TIME.match(resumable)
                               and int(resumable.rstrip("mh")) != 0)
    if not ok:
        yield Hit(ctx.file, ctx.span(step.node("resumable")), f"{_step_label(step)}: resumable={resumable!r} must "
                  f"be True or a lead time like '20m' or '1h': how long before the time limit the step is told "
                  f"to save its checkpoint.")
    elif gpu is False:
        yield Hit(ctx.file, ctx.span(step.node("resumable")), f"{_step_label(step)}: resumable only applies to "
                  f"gpu=True steps; only GPU steps run on the HPC (Slurm) site.",
                  "Add gpu=True, or remove resumable.")


def _every_arguments(ctx, step) -> Iterable[Hit]:
    for key, zero_ok, what in (("checkpoint_every", False, "False (no copies) or minutes like '20m', '1h' or 20"),
                               ("idle_timeout", True, "0 (never end the step as idle) or minutes like '40m', "
                                                      "'1h' or 40")):
        v = step.value(key, None)
        if v is UNKNOWN or v is None or v is False:
            continue
        m = _EVERY.match(str(v).strip()) if v is not True else None
        valid = (m and int(m.group(1)) != 0) or (zero_ok and not isinstance(v, bool) and str(v).strip() == "0")
        if not valid:
            yield Hit(ctx.file, ctx.span(step.node(key)), f"{_step_label(step)}: {key}={v!r} must be {what}.")
