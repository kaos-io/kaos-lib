"""Find the steps of a pipeline repository, statically.

Why: `dev`, `step run` and `build` all start from "which steps does this repository have and where are they". The
answer comes from `pipeline.py` (read with the linter's reader, never imported) plus the step folders on disk, so a
repository without a readable pipeline.py still works through its `steps/*/Dockerfile` folders.
"""
from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field

from ..errors import KaosLibError
from ..lint.constants import PIPELINE_FILE, PRODUCE_TYPES
from ..lint.pipeline_reader import UNKNOWN, read_pipeline
from ..lint.source import TooLarge, parse_python, read_text
from .constants import COMPOSE_STEP, STEPS_DIR


@dataclass
class StepInfo:
    """One step: its name, folder, kind, what it reads and produces, the steps it needs and whether it asks for a GPU."""
    name: str
    folder: str                                   # steps/<name with underscores>, relative to the repository root
    root: pathlib.Path
    needs: list = field(default_factory=list)     # names of the steps it needs
    reads: list = field(default_factory=list)
    gpu: bool = False
    implicit: bool = False                        # compose-and-validate: the platform adds it, pipeline.py does not
    kind: str = ""                                # kind=, "" when it is missing or not a literal
    inputs: list = field(default_factory=list)    # inputs=: the config values that hold a dataset reference
    produces: list = field(default_factory=list)  # produces=: (type, name) for model(...), artifact(...), dataset(...)

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


# Runs pipeline.py with a stand-in for the platform's authoring module that only records the step() calls, so the steps
# a loop builds are known by name. Used only when the static reading found a step whose name it could not read.
_RECORDER = r"""
import json, os, runpy, sys, types
steps = []
class _Pipeline:
    def __init__(self, name): self.name = name
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def write(self, *a, **k): pass
class _Step:
    def __init__(self, name): self.name = name
def step(name, **kw):
    steps.append({"name": name, "kind": kw.get("kind") or "", "reads": list(kw.get("reads") or []),
                  "inputs": list(kw.get("inputs") or []), "needs": [n.name for n in (kw.get("needs") or [])],
                  "gpu": bool(kw.get("gpu")), "produces": [[p.type, p.name] for p in (kw.get("produces") or [])]})
    return _Step(name)
def _produced(kind):
    return lambda name, **kw: types.SimpleNamespace(type=kind, name=name)
authoring = types.ModuleType("kubecore.authoring")
authoring.pipeline, authoring.step = _Pipeline, step
authoring.model, authoring.artifact, authoring.dataset = _produced("model"), _produced("artifact"), _produced("dataset")
package = types.ModuleType("kubecore")
package.authoring, package.__path__ = authoring, []
sys.modules["kubecore"], sys.modules["kubecore.authoring"] = package, authoring
sys.path.insert(0, os.getcwd())
runpy.run_path("pipeline.py", run_name="__main__")
sys.stdout.write("\n@@KAOS-STEPS@@" + json.dumps(steps) + "\n")
"""
RECORD_TIMEOUT = 30


def _recorded_steps(root: pathlib.Path) -> list:
    """The steps pipeline.py builds, as it builds them (loops included), or [] when it cannot be run that way."""
    try:
        done = subprocess.run([sys.executable, "-I", "-c", _RECORDER], cwd=root, capture_output=True, text=True,
                              timeout=RECORD_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return []
    marker = done.stdout.rpartition("@@KAOS-STEPS@@")[2]
    try:
        found = json.loads(marker) if done.returncode == 0 and marker.strip() else []
    except ValueError:
        return []
    return [StepInfo(f["name"], folder_of(f["name"]), root, list(f["needs"]), list(f["reads"]), bool(f["gpu"]),
                     kind=f["kind"], inputs=list(f["inputs"]), produces=[tuple(p) for p in f["produces"]])
            for f in found if isinstance(f.get("name"), str)]


def _pipeline_steps(root: pathlib.Path) -> list:
    try:
        src = read_text(root, root / PIPELINE_FILE, PIPELINE_FILE)
    except TooLarge:
        return []
    if src is None or parse_python(src) is None:
        return []
    facts = read_pipeline(src)
    if any(s.name is UNKNOWN for s in facts.steps) and (built := _recorded_steps(root)):
        return built
    by_var = {s.var: s for s in facts.steps if s.var and s.name is not UNKNOWN}
    out = []
    for s in facts.steps:
        if s.name is UNKNOWN:
            continue
        needs = [by_var[n.id].name for n in _names(s.node("needs")) if n.id in by_var]
        reads, inputs, kind = s.value("reads", []), s.value("inputs", []), s.value("kind", "")
        out.append(StepInfo(s.name, folder_of(s.name), root, needs,
                            list(reads) if isinstance(reads, (list, tuple)) else [], s.is_gpu is True,
                            kind=kind if isinstance(kind, str) else "",
                            inputs=list(inputs) if isinstance(inputs, (list, tuple)) else [],
                            produces=_produces(s.node("produces"))))
    return out


def _produces(node) -> list:
    """`(type, name)` for every `model("x")`, `artifact("x")` or `dataset("x")` of a literal produces=[...]."""
    out = []
    for el in node.elts if isinstance(node, (ast.List, ast.Tuple)) else ():
        if isinstance(el, ast.Call) and isinstance(el.func, ast.Name) and el.func.id in PRODUCE_TYPES and el.args \
                and isinstance(el.args[0], ast.Constant) and isinstance(el.args[0].value, str):
            out.append((el.func.id, el.args[0].value))
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
