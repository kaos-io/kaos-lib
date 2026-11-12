"""The step-API schema: what `step()` accepts, as JSON, for editors and other tools (`kaosctl lint --schema`).

Why: completion, hover text and the "unknown argument" quick fix in an editor must come from the library, never from a
hand-kept list in the editor. The argument order, the accepted shapes and the thresholds are read from `constants`
(the same values the rules use), so a rule change and its schema cannot drift apart; the rule-set version is in the
document, and an editor refuses a schema of a version it does not know.

Static and offline: nothing here imports client code or reads a repository.
"""
from __future__ import annotations

import json

from .constants import (DEFAULT_LIMIT_MINUTES, DOC_BASE, LONG_GPU_STEP_MINUTES, RULESET_VERSION,
                        STEP_NAME_PATTERN, STEP_PARAMS, TIME_PATTERN)

# The shape of this document. Bump when a field an editor reads changes meaning or goes away.
SCHEMA_VERSION = 1

# Where the step API is imported from in a pipeline.py (the linter follows `from <module>.authoring import step`).
AUTHORING_MODULES = ("kubecore.authoring",)

GUIDE_URL = DOC_BASE[: -len("lint/")] + "lint.html"


def _value(insert: str, doc: str) -> dict:
    return {"insert": insert, "label": insert, "doc": doc}


# One entry per step() argument, in the order of STEP_PARAMS. `rules` lists the rule pages that explain the argument.
_PARAMS = {
    "name": dict(
        type="str", required=True, rules=("L-E05", "L-E06"), snippet='"${1:step-name}"',
        doc="The step's name. It becomes the step's template in the pipeline, its `steps/<folder>` (hyphens as "
            "underscores) and its image, so use lowercase letters, digits and hyphens, with no hyphen at the start "
            "or end, for example `model-evaluation`. Every step needs its own name.",
        pattern=STEP_NAME_PATTERN, values=[]),
    "kind": dict(
        type="str", required=True, rules=("L-E07",), snippet='"${1|ingest,transform,train,evaluate,publish,control|}"',
        doc="What the step is. Required. The platform labels the step with it and offers only the compute "
            "classes that fit the kind.",
        values=[_value('"ingest"', "Brings data in from outside."),
                _value('"transform"', "Turns data into other data: preprocess, filter, split, convert."),
                _value('"train"', "Trains a model."),
                _value('"evaluate"', "Measures a model or a dataset."),
                _value('"publish"', "Registers or delivers a result."),
                _value('"control"', "Decides or coordinates; does no data work itself.")]),
    "reads": dict(
        type="list[str]", rules=("L-E05",), snippet='["${1:train}"]',
        doc="The config sections the step reads (the files and folders of `config/`, for example `\"train\"`). A "
            "section that does not exist is refused when the pipeline is rendered.",
        values=[]),
    "produces": dict(
        type="list[model|artifact|dataset]", rules=("L-E07",), snippet='[${1|model,artifact,dataset|}("${2:name}")]',
        doc="What the step writes: `model(\"name\")`, `artifact(\"name\")` or `dataset(\"name\")`. The step "
            "writes each into the folder `step.output(\"name\")` gives it, and `step.result()` saves them.",
        values=[_value('[model("model")]', "The step writes a model."),
                _value('[artifact("report")]', "The step writes files that belong to this run."),
                _value('[dataset("clean")]', "The step writes a version of the dataset `clean`.")]),
    "gpu": dict(
        type="bool", rules=("L-E06", "L-W01", "L-W02"), snippet="True",
        doc="Run the step on a GPU class. Without it the step runs on a CPU machine. How many GPUs it gets on HPC depends on node sharing.",
        default="False",
        values=[_value("True", "The step is offered the GPU classes."), _value("False", "A CPU step (the default).")]),
    "inputs": dict(
        type="list[str]", rules=("L-E07",), snippet='["${1:dataset}"]',
        doc="The names of the config values that hold a dataset reference, for example `\"dataset\"` for "
            "`dataset: dataset-my-data@latest`. The platform pins each to one exact version when the run starts, and "
            "the step reads it with `step.input(\"dataset\")`. Step code never names a version.",
        values=[]),
    "needs": dict(
        type="list[step]", rules=("L-E05",), snippet="[${1:previous_step}]",
        doc="The steps that must finish first. Give the step variables (`needs=[prepare]`), not their names, and "
            "define each step above the steps that need it.",
        values=[]),
    "when": dict(
        type="str", rules=("L-E06",), snippet='"${1:field} != ${2:off}"',
        doc="A condition in plain words: the name of a run-form field, `==` or `!=`, and a value, for example "
            "`\"mode != off\"`. Join comparisons with `and` / `or`. The step runs only when it is true. A step that "
            "needs a conditional step is still started when the conditional step is skipped.",
        values=[]),
    "walltime": dict(
        type="str", rules=("L-E01", "L-E02", "L-E06", "L-W01", "L-I02"), snippet='"${1:12h}"',
        doc="The default time limit of the step, as minutes or hours in text: `\"90m\"`, `\"12h\"` or `\"720\"` "
            "(minutes). The person who starts the run sets the limit on the run form (`<step>-walltime`, at most 30 "
            f"days); this value is what the form starts with. Without it the form starts with {DEFAULT_LIMIT_MINUTES // 60} "
            f"hours. A step with a limit above {LONG_GPU_STEP_MINUTES // 60} hours should be resumable.",
        pattern=TIME_PATTERN,
        values=[_value('"90m"', "90 minutes."), _value('"4h"', "4 hours."), _value('"12h"', "12 hours."),
                _value('"24h"', "24 hours.")]),
    "resumable": dict(
        type="bool|str", rules=("L-E01", "L-E02", "L-E06", "L-W01", "L-W05"), snippet="True",
        doc="Whether the step can continue from a checkpoint after the site stops it. `True` tells the step to save "
            "10 minutes before its time limit; a lead time such as `\"20m\"` or `\"1h\"` changes that. `False` says "
            "the step never continues. Save with `kaos_lib.checkpoint`.",
        pattern=TIME_PATTERN,
        values=[_value("True", "Resumable: the step saves a checkpoint 10 minutes before its time limit."),
                _value("False", "Not resumable: the step is never continued from a checkpoint."),
                _value('"20m"', "Resumable, told to save 20 minutes before its time limit."),
                _value('"1h"', "Resumable, told to save 1 hour before its time limit.")]),
    "checkpoint_every": dict(
        type="bool|str|int", rules=("L-E06",), snippet='"${1:20m}"',
        doc="The default for how often the platform copies the step's checkpoint folder (`KAOS_CHECKPOINT_DIR`): "
            "minutes such as `\"20m\"`, `\"1h\"` or `20`. `False` turns the copies off. The person who starts the run "
            "can change it on the run form (`<step>-checkpoint-every`). GPU steps copy every 10 minutes by default.",
        pattern=r"^[0-9]+[mh]?$",
        values=[_value('"20m"', "Copy every 20 minutes."), _value('"1h"', "Copy every hour."),
                _value("False", "Do not copy the checkpoint folder.")]),
    "idle_timeout": dict(
        type="bool|str|int", rules=("L-E06", "L-W02"), snippet='"${1:40m}"',
        doc="How long a GPU step may show no GPU use and no new log line before the platform ends it as idle: "
            "minutes such as `\"40m\"`, `\"1h\"` or `40`. The default is 20 minutes. `0` (or `False`) turns the "
            "idle limit off, so a hung step keeps its GPU until its time limit.",
        pattern=r"^[0-9]+[mh]?$",
        values=[_value('"40m"', "Allow 40 minutes without GPU use or log lines."),
                _value('"1h"', "Allow one hour without GPU use or log lines."),
                _value("0", "Never end the step as idle.")]),
}


def _parameter(position: int, name: str) -> dict:
    spec = dict(_PARAMS[name])
    rules = spec.pop("rules")
    out = {"name": name, "position": position, "type": spec.pop("type"), "required": spec.pop("required", False),
           "default": spec.pop("default", None), "gpu_only": spec.pop("gpu_only", False),
           "pattern": spec.pop("pattern", None), "doc": spec.pop("doc"), "snippet": spec.pop("snippet"),
           "values": spec.pop("values"),
           "links": [{"title": rule, "url": f"{DOC_BASE}{rule}.html"} for rule in rules]}
    assert not spec, f"unused schema fields for {name}: {sorted(spec)}"
    return out


def _rules() -> list:
    from .engine import ALL_RULES   # late: importing the engine registers every rule
    return [{"id": r.id, "name": r.name, "level": r.level, "fix": r.fix, "doc": r.doc} for r in ALL_RULES]


def build_schema() -> dict:
    """The schema as a dict: the `step()` arguments, the rules, all versioned with the rule set."""
    missing = set(STEP_PARAMS) ^ set(_PARAMS)
    assert not missing, f"STEP_PARAMS and the schema differ: {sorted(missing)}"
    return {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "guide": GUIDE_URL,
        "authoring_modules": list(AUTHORING_MODULES),
        "step": {"function": "step", "parameters": [_parameter(i, n) for i, n in enumerate(STEP_PARAMS)]},
        "pipeline": {"function": "pipeline",
                     "doc": "`with pipeline(\"name\") as p:` opens a pipeline; every `step(...)` call inside it adds "
                            "a step. The check reads these calls without running your code."},
        "rules": _rules(),
    }


def schema_json() -> str:
    """The schema as JSON text: two-space indent, fixed key order, a final newline (byte-stable, like the report)."""
    return json.dumps(build_schema(), indent=2, ensure_ascii=False) + "\n"
