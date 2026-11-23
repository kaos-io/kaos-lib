"""The rule registry and the context every rule reads.

Why: a rule is a small function that yields hits; the registry gives it its id, level, texts and the facts it needs,
so adding a rule is one function and one docs page, and the engine, the report and the docs cannot drift apart.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from .catalogue import Catalogue
from . import constants
from .model import ERROR, INFO, WARNING, Span
from .pipeline_reader import UNKNOWN, PipelineFacts, Step
from .project_reader import DatasetDefault, RunForm, StepSource, read_step_source

REQUIRES_CLASSES = "classes"


@dataclass
class Hit:
    """What a rule reports: where and what; the registry adds the rule's id, level, fix and link."""
    file: str
    span: Span
    message: str
    fix: Optional[str] = None   # overrides the rule's generic fix hint when the hint depends on the finding
    level: Optional[str] = None   # overrides the rule's level for rules that have two (L-D05: error and warning)


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
        return doc_url(self.id)


RULES: list = []

_doc_base: Optional[str] = constants.DOC_BASE


def set_doc_base(url: Optional[str]) -> None:
    """The folder of the rule pages (``https://.../lint/``) for this process, or None: no rule links. The caller
    (the command line) decides; nothing here knows an address."""
    global _doc_base
    if url is not None and not url.startswith("https://"):
        raise ValueError(f"the rule pages folder must be an https address, not {url!r}")
    _doc_base = None if not url else (url if url.endswith("/") else url + "/")


def doc_base() -> Optional[str]:
    return _doc_base


def doc_url(rule_id: str) -> str:
    """The page of a rule, or "" when the folder is unknown."""
    return f"{_doc_base}{rule_id}.html" if _doc_base else ""


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
    values: Optional[dict] = None       # top-level config value -> whether it is a plain text value; None: unknown
    run_form: Optional[RunForm] = None  # the run form's fields; None: unknown
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


def step_label(step: Step) -> str:
    """"Step 'x'", or, for a step whose name is not a literal (built in a loop or a call), where it is built."""
    return f"Step '{step.name}'" if isinstance(step.name, str) else f"The step built at line {step.call.lineno}"


def gpu_steps(ctx: LintContext) -> Iterable[Step]:
    """Steps that are certainly GPU steps (gpu=True)."""
    return (s for s in ctx.pipeline.steps if s.is_gpu is True)
