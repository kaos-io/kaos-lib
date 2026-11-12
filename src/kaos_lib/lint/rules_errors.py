"""The error rules (L-E01 .. L-E06): problems the platform would refuse at render or at submit.

Why: these fail the `pipeline-lint` status, so each one is something the enhancer, the step() validators or the
HPC (Slurm) admission would reject anyway; the linter says so earlier, with the step and a fix.
"""
from __future__ import annotations

import ast
import re
from typing import Iterable

from .constants import (COMPUTE_CLASS_KEYS, ENGINE_FOLDER, IDENTITY_NAMES, MAX_NEEDS, MAX_READABLE, MIN_DATASET_NAME, NAME_MAX,
                        OLD_APP_NOTICE, OLD_ENTRY_ARGUMENT, PIPELINE_FILE, POD_PATCH_NAMES, PRODUCE_TYPES, REMOVED_STEP_PARAMS,
                        RESERVED_NAME_PREFIX, RESERVED_STEP_NAMES, RESERVED_STEP_SUFFIX, RESERVED_TEMPLATE_NAMES, STEP_KINDS, STEP_NAME_PATTERN, STEP_PARAMS,
                        STEPS_DIR, TIME_PATTERN)
from . import when_text
from .model import ERROR, Span
from .pipeline_reader import UNKNOWN, literal
from .project_reader import platform_group, step_folder
from .registry import (DECLARED, NOT_VERIFIED, OFF, REQUIRES_CLASSES, REQUIRES_CONTINUATIONS, REQUIRES_HPC, STATIC,
                       VERIFIED, Hit, LintContext, gpu_steps, parse_minutes, pretty_minutes,
                       rule, runs_needed, step_label)

_STEP_NAME, _TIME = re.compile(STEP_NAME_PATTERN), re.compile(TIME_PATTERN)
_EVERY = re.compile(r"^([0-9]+)([mh]?)$")
_DEPENDS_TOKEN = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_-]*)(?:\.(?:Succeeded|Failed|Skipped|Omitted|Errored|Daemoned))?")


_step_label = step_label


@rule("L-E01", "TooLongNotResumable", ERROR,
      "Make the step resumable (resumable=True, saving checkpoints with kaos_lib.checkpoint) or set "
      "walltime to the longest run or less.", requires=(REQUIRES_HPC,))
def too_long_not_resumable(ctx: LintContext) -> Iterable[Hit]:
    lane = ctx.catalogue.hpc.lane_max_minutes
    for step in gpu_steps(ctx):
        limit = parse_minutes(step.value("walltime", None))
        state = ctx.resumable(step)
        if limit is None or limit <= lane or state not in (OFF, NOT_VERIFIED):
            continue
        how = "is set not resumable" if state == OFF else "is not declared resumable and the platform recorded " \
            f"that its last continuation did not resume ({ctx.evidence(step).reason or 'no reason given'})"
        yield Hit(ctx.file, ctx.span(step.node("walltime")),
                  f"{_step_label(step)} asks for a time limit of {pretty_minutes(limit)}, but the longest run on "
                  f"the HPC (Slurm) site is {pretty_minutes(lane)}, and the step {how}, so it would be cut off. "
                  f"The platform refuses it at submit.")


@rule("L-E02", "TooLongBeyondContinuations", ERROR,
      "Shorten walltime, or split the work into steps that each fit within the runs allowed.",
      requires=(REQUIRES_HPC, REQUIRES_CONTINUATIONS))
def too_long_beyond_continuations(ctx: LintContext) -> Iterable[Hit]:
    lane, cap = ctx.catalogue.hpc.lane_max_minutes, ctx.catalogue.max_continuations
    for step in gpu_steps(ctx):
        limit = parse_minutes(step.value("walltime", None))
        if limit is None or ctx.resumable(step) not in (DECLARED, VERIFIED, STATIC):
            continue
        runs = runs_needed(limit, lane)
        if runs > cap + 1:
            yield Hit(ctx.file, ctx.span(step.node("walltime")),
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
      "Remove the argument or write it as the message says; step() raises on it when the pipeline is rendered.")
def refused_argument(ctx: LintContext) -> Iterable[Hit]:
    for step in ctx.pipeline.steps:
        yield from _unknown_arguments(ctx, step)
        if step.opaque:
            continue
        yield from _time_arguments(ctx, step)
        yield from _when_argument(ctx, step)
        yield from _every_arguments(ctx, step)


def _unknown_arguments(ctx, step) -> Iterable[Hit]:
    for kw in step.unknown_keywords:
        if kw.arg in REMOVED_STEP_PARAMS:
            yield Hit(ctx.file, ctx.span(kw), f"{_step_label(step)}: {REMOVED_STEP_PARAMS[kw.arg]}")
        else:
            yield Hit(ctx.file, ctx.span(kw), f"step() has no argument '{kw.arg}', so the render fails.",
                      f"Remove it or check the name: step() accepts {', '.join(STEP_PARAMS[:-1])} and "
                      f"{STEP_PARAMS[-1]}.")
    seen = set()
    for kw in step.call.keywords:
        if kw.arg in seen:
            yield Hit(ctx.file, ctx.span(kw), f"step() is given '{kw.arg}' twice, so the render fails.",
                      f"Remove one of the two {kw.arg}=.")
        seen.add(kw.arg)
    for arg in step.extra_positional:
        yield Hit(ctx.file, ctx.span(arg), "step() takes only the name by position: every other argument is given by "
                  "keyword, so this render fails.", "Write it as a keyword, for example kind='train'.")
    if not step.opaque and "name" not in step.args:
        yield Hit(ctx.file, ctx.span(step.call), "step() is called without a name.", "Give the step a name.")


def _needed_steps(ctx, step) -> set:
    """The names of the steps in this step's needs=[...] that can be read: step variables of the same pipeline."""
    node = step.node("needs")
    names = {el.id for el in getattr(node, "elts", ()) if isinstance(el, ast.Name)}
    return {s.name for s in ctx.pipeline.steps if s.var in names and isinstance(s.name, str)}


def _when_argument(ctx, step) -> Iterable[Hit]:
    text = step.value("when", None)
    if text is UNKNOWN or text is None:
        return
    node, label = ctx.span(step.node("when")), _step_label(step)
    if when_text.uses_workflow_syntax(text):
        yield Hit(ctx.file, node, f"{label}: when= is written with plain names, not with {{{{...}}}}. "
                  f"{when_text.ALLOWED}", f"Write the name: {when_text.EXAMPLE}.")
        return
    if when_text.has_control_character(text):
        yield Hit(ctx.file, node, f"{label}: when={text!r} holds a control character (a line break, a tab). Write the "
                  f"condition on one line.", "Write the condition on one line.")
        return
    named = when_text.fields(text)
    if named is None:
        yield Hit(ctx.file, node, f"{label}: when={text!r} is not a condition the platform can read. "
                  f"{when_text.ALLOWED}",
                  f"Write it as a name, == or !=, and a value: {when_text.FORMS}.")
        return
    form, needed = ctx.run_form, _needed_steps(ctx, step)
    declared = {s.name for s in ctx.pipeline.steps if isinstance(s.name, str)}
    for field in named:
        head, dot, key = field.partition(".")
        if dot and head in needed:
            if not when_text.VALUE_KEY.match(key):
                yield Hit(ctx.file, node, f"{label}: when= names the value {key!r} of step {head!r}, which is not a "
                          f"name step.result() could have been given (letters, digits and _).",
                          f"Write {head}.<value> with the keyword you gave step.result(<value>=...).")
                return
            for compared, _, value in when_text.comparisons(text):
                problem = when_text.value_problem(value) if compared == field else ""
                if problem:
                    yield Hit(ctx.file, node, f"{label}: when= compares {head}.{key} with {value!r}, which cannot be "
                              f"matched reliably: {problem}.", "Write the text the way the message says.")
                    return
            continue
        if dot and head in declared:
            yield Hit(ctx.file, node, f"{label}: when= reads a value of step {head!r}, which this step does not need.",
                      f"Add {head} to needs=[...] of this step: a step sees the result of the steps in its needs= only.")
            return
        if form is None or field in form.fields or (
                form.schema and any(field == s or field.startswith(s + "-") for s in form.sections)):
            continue
        yield Hit(ctx.file, node, f"{label}: when={text!r} names {field!r}, which is not a field of the run form. "
                  f"The fields are: {', '.join(sorted(form.fields))}.",
                  "Use the name of a setting as the run form shows it: its path with dashes.")
        return


def _time_arguments(ctx, step) -> Iterable[Hit]:
    limit, resumable = step.value("walltime", None), step.value("resumable", None)
    if limit is not UNKNOWN and limit is not None:
        if not (isinstance(limit, str) and _TIME.match(limit)):
            yield Hit(ctx.file, ctx.span(step.node("walltime")), f"{_step_label(step)}: "
                      f"walltime={limit!r} must be minutes or hours as text, like '90m', '12h' or '720'.")
    if resumable is UNKNOWN or resumable is None or resumable is False:
        return
    ok = resumable is True or (isinstance(resumable, str) and _TIME.match(resumable)
                               and int(resumable.rstrip("mh")) != 0)
    if not ok:
        yield Hit(ctx.file, ctx.span(step.node("resumable")), f"{_step_label(step)}: resumable={resumable!r} must "
                  f"be True or a lead time like '20m' or '1h': how long before the time limit the step is told "
                  f"to save its checkpoint.")


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


@rule("L-E07", "StepDeclaration", ERROR,
      "Give every step a kind, name its dataset inputs in inputs=[...] and what it writes in produces=[...].")
def step_declaration(ctx: LintContext) -> Iterable[Hit]:
    writers = {}                                    # dataset name -> the step that produces it
    any_kind = any("kind" in step.args for block in ctx.pipeline.blocks for step in block.steps)
    for block in ctx.pipeline.blocks:
        made = {}                                   # step variable -> what it produces, as (type, name)
        for step in block.steps:
            if step.opaque:
                continue
            yield from _step_name(ctx, step)
            yield from _folder(ctx, step)
            yield from _kind(ctx, step, any_kind)
            inputs = yield from _inputs(ctx, step)
            produced = yield from _produces(ctx, step)
            yield from _input_is_output(ctx, step, inputs, produced)
            yield from _output_of_needed_step(ctx, step, produced, made)
            yield from _control_handles_no_data(ctx, step, inputs, produced)
            yield from _kind_contract(ctx, step)
            yield from _same_name_twice(ctx, step, inputs, made)
            yield from _one_writer(ctx, step, produced, writers)
            if step.var:
                made[step.var] = produced


_NAME = re.compile(r"^(?=.{1,%d}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?$" % NAME_MAX)
_NAMES = (f"Use lowercase letters, digits and hyphens, at most {NAME_MAX} characters; names starting with "
          f"'{RESERVED_NAME_PREFIX}' are the platform's.")


def _step_name(ctx, step) -> Iterable[Hit]:
    name = step.name
    if not isinstance(name, str) or not _STEP_NAME.match(name):
        return
    if len(name) > NAME_MAX or name.startswith(RESERVED_NAME_PREFIX):
        yield Hit(ctx.file, ctx.span(step.node("name")), f"The step name '{name}' cannot be used. " + _NAMES,
                  "Rename the step and its steps/<folder>.")
    elif name in RESERVED_STEP_NAMES or name.endswith(RESERVED_STEP_SUFFIX):
        yield Hit(ctx.file, ctx.span(step.node("name")), f"The step name '{name}' is the platform's: it keeps "
                  f"{', '.join(RESERVED_STEP_NAMES)} for itself and names the HPC (Slurm) variant of a step "
                  f"'<step>{RESERVED_STEP_SUFFIX}'.", "Rename the step and its steps/<folder>.")


def _folder(ctx, step) -> Iterable[Hit]:
    """Every step has its folder steps/<name with underscores>/ (checked in a repository that has a steps/ folder)."""
    name = step.name
    if not isinstance(name, str) or not (ctx.root / STEPS_DIR).is_dir() or (ctx.root / step_folder(name)).is_dir():
        return
    folder = step_folder(name)
    hyphen = f"{STEPS_DIR}/{name}"
    found = f" There is a folder {hyphen}/: rename it to {folder}/." if (ctx.root / hyphen).is_dir() else ""
    yield Hit(ctx.file, ctx.span(step.node("name")),
              f"Step '{name}' has no folder {folder}/. The folder of a step is steps/ plus the step's name with every "
              f"hyphen written as an underscore.{found}",
              f"Create {folder}/ with a Dockerfile and app/entry.py.")


def _input_is_output(ctx, step, inputs, produced) -> Iterable[Hit]:
    """The step reads an input and writes an output by name, into folders of that name: one name is one thing."""
    for name in sorted({n for _, n in produced} & set(inputs)):
        yield Hit(ctx.file, ctx.span(step.node("produces")), f"{_step_label(step)}: '{name}' is both an input "
                  f"(inputs=) and one of its own outputs (produces=): the step reads and writes by name, so the two "
                  f"must differ.", f"Rename the config value (for example 'previous-{name}', in inputs= and in "
                  f"config/) or the produced name.")


def _output_of_needed_step(ctx, step, produced, made) -> Iterable[Hit]:
    """A step reads what a needed step wrote by name, and writes its own outputs by name: one name is one thing."""
    needs = step.node("needs")
    own = {n for _, n in produced}
    for el in needs.elts if isinstance(needs, (ast.List, ast.Tuple)) else ():
        for _, name in made.get(getattr(el, "id", None), ()):
            if name in own:
                yield Hit(ctx.file, ctx.span(step.node("produces")), f"{_step_label(step)}: {name} is both something "
                          f"the step it needs, {el.id!r}, produces and one of its own outputs (produces=): the step "
                          f"reads and writes by name, so the two must differ.", "Rename the produced name of one of "
                          "the two steps.")


def _kind(ctx, step, any_kind) -> Iterable[Hit]:
    kinds = ", ".join(STEP_KINDS)
    if "kind" not in step.args:
        # An app from before the contract has no kind on any step; a new app that forgot one is not "old".
        yield Hit(ctx.file, ctx.span(step.call), f"{_step_label(step)} has no kind=, which every step declares: one "
                  f"of {kinds}." + ("" if any_kind else f" {OLD_APP_NOTICE}"))
        return
    kind = step.value("kind")
    if kind is not UNKNOWN and kind not in STEP_KINDS:
        yield Hit(ctx.file, ctx.span(step.node("kind")), f"{_step_label(step)}: kind is {kind!r}, which is not a "
                  f"kind. A step is one of {kinds}.", "Choose the kind that says what the step does.")


def _control_handles_no_data(ctx, step, inputs, produced) -> Iterable[Hit]:
    if step.value("kind") == "control" and (inputs or produced):
        yield Hit(ctx.file, ctx.span(step.node("kind")), f"{_step_label(step)}: a control step steers the run and "
                  "handles no data, so it takes no inputs= and no produces=.",
                  "Give the step the kind of the work it does: " + ", ".join(k for k in STEP_KINDS if k != "control"))


def _produced_types(step):
    """The types the step's produces=[...] holds, or None when the list cannot be read statically."""
    node = step.node("produces")
    if node is None:
        return set()
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    types = set()
    for el in node.elts:
        func = el.func if isinstance(el, ast.Call) else None
        kind = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if kind not in PRODUCE_TYPES:
            return None
        types.add(kind)
    return types


def _kind_contract(ctx, step) -> Iterable[Hit]:
    """What each kind requires of what the step produces (the page 'Step kinds')."""
    kind, types = step.value("kind", None), _produced_types(step)
    if types is None or kind not in STEP_KINDS or kind == "control":
        return
    label, others = _step_label(step), ", ".join(k for k in STEP_KINDS if k != kind)
    if kind == "ingest" and "dataset" not in types:
        problem = f'{label}: an ingest step brings data in, so it produces a dataset.', 'Add produces=[dataset("name")].'
    elif kind == "transform" and not types:
        problem = (f"{label}: a transform step turns data into something.",
                   "Add produces=[...] with a dataset, a model or an artifact.")
    elif kind == "train" and "model" not in types:
        problem = (f"{label}: a train step produces a model.",
                   f'Add produces=[model("name")], or give the step the kind of the work it does ({others}).')
    elif kind == "evaluate" and types & {"dataset", "model"}:
        problem = (f"{label}: an evaluate step writes reports only, so it may not produce a dataset or a model.",
                   'Use kind="transform" for a step that makes a dataset, kind="train" for one that makes a model.')
    elif kind == "publish" and types:
        problem = (f"{label}: a publish step delivers a result and produces nothing here.",
                   "Remove produces=, or give the step the kind of the work it does.")
    else:
        return
    yield Hit(ctx.file, ctx.span(step.node("kind")), f"{problem[0]} {problem[1]}", problem[1])


def _one_writer(ctx, step, produced, writers) -> Iterable[Hit]:
    for kind, name in produced:
        if kind != "dataset":
            continue
        if name in writers:
            yield Hit(ctx.file, ctx.span(step.node("produces")), f"{_step_label(step)}: the dataset '{name}' is "
                      f"already produced by step '{writers[name]}'. A dataset has one writer.",
                      "Give one of the two datasets another name.")
        else:
            writers[name] = step.name if isinstance(step.name, str) else "another step"


def _inputs(ctx, step):
    node = step.node("inputs")
    if node is None:
        return []
    value = literal(node)
    if value is UNKNOWN:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) and v for v in value):
        yield Hit(ctx.file, ctx.span(node), f"{_step_label(step)}: inputs must be a list of names, the config "
                  f"values that hold a dataset reference, for example inputs=[\"dataset\"].")
        return []
    for name in sorted({v for v in value if list(value).count(v) > 1}):
        yield Hit(ctx.file, ctx.span(node), f"{_step_label(step)} lists the input '{name}' twice.",
                  "List each input once.")
    for name in value:
        if not _NAME.match(name) or name.startswith(RESERVED_NAME_PREFIX):
            yield Hit(ctx.file, ctx.span(node), f"{_step_label(step)}: {name!r} is not a name for an input. " + _NAMES,
                      "Rename the config value, and the name in inputs=[...].")
        elif ctx.values is not None and not ctx.values.get(name):
            what = "is a section of the config, not a value" if name in ctx.values else "is not in config/"
            yield Hit(ctx.file, ctx.span(node), f"{_step_label(step)}: the input '{name}' {what}. An input is the name "
                      f"of a top-level config value that holds a dataset reference, for example dataset: "
                      f"dataset-default@latest in config/dataset.yaml.", "Add the value to config/, or fix the name.")
    return list(value)


def _produces(ctx, step):
    node = step.node("produces")
    if node is None:
        return []
    if not isinstance(node, (ast.List, ast.Tuple)):
        if literal(node) is not UNKNOWN or isinstance(node, ast.Call):
            yield Hit(ctx.file, ctx.span(node), f"{_step_label(step)}: produces must be a list, for example "
                      f"produces=[model(\"model\")].")
        return []
    seen, produced = set(), []
    for el in node.elts:
        func = el.func if isinstance(el, ast.Call) else None
        kind = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        name = literal(el.args[0]) if kind and el.args else UNKNOWN
        if kind not in PRODUCE_TYPES:
            yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)}: produces takes model(\"name\"), "
                      f"artifact(\"name\") or dataset(\"name\"), not this.")
            continue
        for kw in el.keywords:
            if kw.arg == "of":
                yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)}: dataset(..., of=...) is reserved for a "
                          f"later release and is refused at render.", "Remove of=.")
            else:
                yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)}: {kind}() takes a name and nothing else.",
                          f"Remove {kw.arg or '**'}=.")
        if name is UNKNOWN:
            continue
        if not isinstance(name, str) or not _NAME.match(name) or name.startswith(RESERVED_NAME_PREFIX):
            yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)}: {name!r} is not a name for what a step "
                      f"produces. " + _NAMES, "Rename it.")
        elif kind == "dataset" and len(name) < MIN_DATASET_NAME:
            yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)}: the dataset name {name!r} is too short. A dataset "
                      f"name has {MIN_DATASET_NAME} to {NAME_MAX} characters: it is stored as dataset-<app>-<name>.",
                      "Give the dataset a longer name, for example dataset(\"embeddings\").")
        elif name in seen:
            yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)} produces '{name}' twice.",
                      "Give each thing the step produces its own name.")
        seen.add(name)
        if isinstance(name, str):
            produced.append((kind, name))
    return produced


def _same_name_twice(ctx, step, inputs, made) -> Iterable[Hit]:
    """An input and what the needed steps write are all read by name, so one name cannot mean two things."""
    needs = step.node("needs")
    seen = {}
    if isinstance(needs, (ast.List, ast.Tuple)) and len(needs.elts) > MAX_NEEDS:
        yield Hit(ctx.file, ctx.span(needs), f"{_step_label(step)} needs {len(needs.elts)} steps; a step can need "
                  f"at most {MAX_NEEDS}.", "Put a step in between that gathers some of their results.")
    readable = len(inputs)
    for el in needs.elts if isinstance(needs, (ast.List, ast.Tuple)) else ():
        for kind, name in made.get(getattr(el, "id", None), ()):
            readable += kind == "dataset"
            if name in inputs:
                yield Hit(ctx.file, ctx.span(step.node("inputs")), f"{_step_label(step)} has the input '{name}' "
                          f"and needs a step that produces '{name}': step.input(\"{name}\") could mean either.",
                          "Rename the input (the config value) or what the needed step produces.")
            if name in seen:
                yield Hit(ctx.file, ctx.span(el), f"{_step_label(step)} needs '{seen[name]}' and '{el.id}', which "
                          f"both produce '{name}': step.input(\"{name}\") could mean either.",
                          "Rename what one of the two steps produces.")
            seen.setdefault(name, el.id)
    if readable > MAX_READABLE:
        yield Hit(ctx.file, ctx.span(step.call), f"{_step_label(step)} can read {readable} datasets by name (its "
                  f"inputs and the datasets of the steps it needs); a step may have at most {MAX_READABLE}.",
                  "Split the step, or join datasets it reads.")


@rule("L-E08", "OldStepCode", ERROR, "Create the app again from the template.")
def old_step_code(ctx: LintContext) -> Iterable[Hit]:
    if (ctx.root / ENGINE_FOLDER).is_dir() and not (ctx.root / ENGINE_FOLDER).is_symlink():
        yield Hit(PIPELINE_FILE, Span(1, 1, 1, 1), f"The app has a {ENGINE_FOLDER}/ folder of its own, and an app "
                  f"carries no copy of the engine. {OLD_APP_NOTICE}")
    for step in ctx.pipeline.steps:
        source = ctx.step_source(step)
        if source is None or not source.found:
            continue
        for file, span, what in source.old_contract:
            yield Hit(file, span, f"{_step_label(step)} {what}, which a step no longer does. {OLD_APP_NOTICE}")
        if not source.old_contract and source.has_entry and not source.starts_step:
            yield Hit(ctx.file, ctx.span(step.call), f"{_step_label(step)} never calls step.start() "
                      f"(from kaos_lib import step), so it cannot read its config or its inputs and hands "
                      f"nothing on.")


@rule("L-E09", "PlatformConfigGroup", ERROR, "Create the app again from the template.")
def platform_config_group(ctx: LintContext) -> Iterable[Hit]:
    for file, span, what in platform_group(ctx.root):
        if what == "line":
            yield Hit(file, span, f"config/config.yaml names the `platform` config group, which the platform no "
                      f"longer adds. {OLD_APP_NOTICE}")
        else:
            yield Hit(file, span, f"The app has a config/platform/ folder, which the platform no longer reads. "
                      f"{OLD_APP_NOTICE}")
