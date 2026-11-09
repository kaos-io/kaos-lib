"""Find the steps of a pipeline repository, statically.

Why: `dev`, `step run` and `build` all start from "which steps does this repository have and where are they". The
answer comes from `pipeline.py` (read with the linter's reader, never imported) plus the step folders on disk, so a
repository without a readable pipeline.py still works through its `steps/*/Dockerfile` folders.
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass, field

from ..errors import KaosLibError
from ..lint.constants import PIPELINE_FILE
from ..lint.pipeline_reader import UNKNOWN, read_pipeline
from ..lint.source import TooLarge, parse_python, read_text
from .constants import COMPOSE_STEP, STEPS_DIR


@dataclass
class StepInfo:
    """One step: its name, folder, declared outputs, the steps it needs and whether it asks for a GPU."""
    name: str
    folder: str                                   # steps/<name with underscores>, relative to the repository root
    root: pathlib.Path
    outputs: list = field(default_factory=list)
    needs: list = field(default_factory=list)     # names of the steps it needs
    reads: list = field(default_factory=list)
    gpu: bool = False
    implicit: bool = False                        # compose-and-validate: the platform adds it, pipeline.py does not

    @property
    def path(self) -> pathlib.Path:
        return self.root / self.folder

    @property
    def dockerfile(self) -> pathlib.Path:
        return self.path / "Dockerfile"


def folder_of(name: str) -> str:
    """steps/<name with hyphens as underscores>: how the platform maps a step name to its folder."""
    return f"{STEPS_DIR}/{name.replace('-', '_')}"


def repo_root(path) -> pathlib.Path:
    """The repository folder the user means; an error naming the folder when it does not exist."""
    root = pathlib.Path(path or ".").resolve()
    if not root.is_dir():
        raise KaosLibError(f"{root} is not a folder. Run kaosctl inside your app folder, or pass its path.")
    return root


def _pipeline_steps(root: pathlib.Path) -> list:
    try:
        src = read_text(root, root / PIPELINE_FILE, PIPELINE_FILE)
    except TooLarge:
        return []
    if src is None or parse_python(src) is None:
        return []
    facts = read_pipeline(src)
    by_var = {s.var: s for s in facts.steps if s.var and s.name is not UNKNOWN}
    out = []
    for s in facts.steps:
        if s.name is UNKNOWN:
            continue
        needs = [by_var[n.id].name for n in _names(s.node("needs")) if n.id in by_var]
        outputs = s.value("outputs", [])
        reads = s.value("reads", [])
        out.append(StepInfo(s.name, folder_of(s.name), root, list(outputs) if isinstance(outputs, (list, tuple)) else [],
                            needs, list(reads) if isinstance(reads, (list, tuple)) else [], s.is_gpu is True))
    return out


def _names(node) -> list:
    return [n for n in ast.walk(node) if isinstance(n, ast.Name)] if node is not None else []


def discover(root: pathlib.Path) -> list:
    """The steps of the repository: those of pipeline.py, then any other `steps/<x>/Dockerfile` folder.

    compose-and-validate (which the platform adds to every pipeline) is listed when its folder exists.
    """
    steps = _pipeline_steps(root)
    known = {s.folder for s in steps}
    base = root / STEPS_DIR
    for d in sorted(base.iterdir()) if base.is_dir() else []:
        rel = f"{STEPS_DIR}/{d.name}"
        if d.is_dir() and not d.is_symlink() and rel not in known and (d / "Dockerfile").is_file():
            name = d.name.replace("_", "-")
            steps.append(StepInfo(name, rel, root, implicit=name == COMPOSE_STEP))
    return steps


def find(root: pathlib.Path, name: str) -> StepInfo:
    """One step by name (`data-summary` or `data_summary`); an error that lists the names when it is not there."""
    wanted = name.replace("_", "-")
    steps = discover(root)
    for s in steps:
        if s.name == wanted:
            return s
    known = ", ".join(s.name for s in steps) or "none found"
    raise KaosLibError(f"no step named {name!r} in {root}. Steps: {known}.")


def select(root: pathlib.Path, names: list) -> list:
    """The steps asked for (all of them when `names` is empty)."""
    return [find(root, n) for n in names] if names else discover(root)
