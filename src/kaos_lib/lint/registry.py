"""The rule registry and the context every rule reads.

Why: a rule is a small function that yields hits; the registry gives it its id, level, texts and the facts it needs,
so adding a rule is one function and one docs page, and the engine, the report and the docs cannot drift apart.
"""
from __future__ import annotations

import math
import pathlib
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from .catalogue import Catalogue
from .constants import DOC_BASE, TIME_PATTERN
from .model import ERROR, INFO, WARNING, Span
from .pipeline_reader import UNKNOWN, PipelineFacts, Step
from .project_reader import DatasetDefault, StepSource, read_step_source

REQUIRES_CLASSES, REQUIRES_HPC, REQUIRES_CONTINUATIONS = "classes", "hpc", "continuations"
_TIME = re.compile(TIME_PATTERN)

# Step resumability as the rules see it.
DECLARED, OFF, VERIFIED, NOT_RESUMABLE, UNKNOWN_STATE = "declared", "off", "verified", "none", "unknown"


@dataclass
class Hit:
    """What a rule reports: where and what; the registry adds the rule's id, level, fix and link."""
    file: str
    span: Span
    message: str
    fix: Optional[str] = None   # overrides the rule's generic fix hint when the hint depends on the finding


@dataclass(frozen=True)
class Rule:
    """A registered rule."""
    id: str
    name: str
    level: str
    fix: str
    check: Callable
    requires: tuple = ()
    inactive: str = ""      # a reason: the rule is registered and documented but cannot run yet

    @property
    def doc(self) -> str:
        return f"{DOC_BASE}{self.id}.html"


RULES: list = []


def rule(id: str, name: str, level: str, fix: str, requires: tuple = (), inactive: str = ""):
    """Register the decorated function `check(ctx) -> Iterable[Hit]` as a rule."""
    assert level in (ERROR, WARNING, INFO)

    def register(fn: Callable) -> Callable:
        RULES.append(Rule(id, name, level, fix, fn, requires, inactive))
        return fn
    return register


@dataclass
class LintContext:
    """Everything a rule may read: the parsed pipeline, the catalogue and the rest of the repository."""
    root: pathlib.Path
    pipeline: PipelineFacts
    catalogue: Catalogue
    sections: Optional[set] = None
    dataset: Optional[DatasetDefault] = None
    _sources: dict = field(default_factory=dict)

    @property
    def file(self) -> str:
        return self.pipeline.src.rel

    def span(self, node) -> Span:
        return self.pipeline.src.span(node)

    def step_source(self, step: Step) -> Optional[StepSource]:
        """The facts of the step's folder, or None when the step's name is not a literal."""
        name = step.name
        if name is UNKNOWN:
            return None
        if name not in self._sources:
            self._sources[name] = read_step_source(self.root, name)
        return self._sources[name]

    def resumable(self, step: Step) -> str:
        """DECLARED (resumable=True or a lead time), OFF (resumable=False), VERIFIED (unset, but the step's code
        uses checkpoints), NOT_RESUMABLE (unset and no checkpoint use found) or UNKNOWN_STATE (cannot tell)."""
        value = step.value("resumable", None)
        if value is UNKNOWN or step.opaque:
            return UNKNOWN_STATE
        if value is False:
            return OFF
        if value is not None:
            return DECLARED
        source = self.step_source(step)
        if source is None or not source.found:
            return UNKNOWN_STATE
        return VERIFIED if source.uses_checkpoint else NOT_RESUMABLE


def parse_minutes(value) -> Optional[int]:
    """A time limit such as '90m', '12h' or '720' (minutes) as minutes; None when it is not that shape."""
    if not isinstance(value, str) or not _TIME.match(value):
        return None
    return int(value.rstrip("mh")) * (60 if value.endswith("h") else 1)


def pretty_minutes(minutes: int) -> str:
    """90 -> '90 minutes', 720 -> '12 hours', 2880 -> '2 days'."""
    if minutes % 1440 == 0:
        n, unit = minutes // 1440, "day"
    elif minutes % 60 == 0:
        n, unit = minutes // 60, "hour"
    else:
        n, unit = minutes, "minute"
    return f"{n} {unit}{'' if n == 1 else 's'}"


def runs_needed(limit: int, lane_max: int) -> int:
    """How many runs of at most lane_max minutes a limit takes."""
    return math.ceil(limit / lane_max)


def gpu_steps(ctx: LintContext) -> Iterable[Step]:
    """Steps that are certainly GPU steps (gpu=True)."""
    return (s for s in ctx.pipeline.steps if s.is_gpu is True)
