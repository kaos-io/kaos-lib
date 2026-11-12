"""Reads the rest of the repository the rules need: the config tree's sections, the dataset default and what each
step's source does (checkpoints, MLflow, model registration, `latest` dataset references).

Why: several rules look at files next to pipeline.py. Keeping the reading here, with its limits, means a rule is a
few lines of judgement and the linter stays static: step code is parsed, never imported or run.
"""
from __future__ import annotations

import ast
import pathlib
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

from .constants import (CHECKPOINT_DIR_ENV, CHECKPOINT_FRAMEWORKS, CHECKPOINT_STATE_NAMES, CONFIG_DIR, MAX_FILE_BYTES,
                        MAX_STEP_BYTES, MAX_STEP_FILES, OLD_ENTRY_ARGUMENT, OLD_ENTRY_VARIABLES, PIPELINE_FILE,
                        STEPS_DIR)

ENTRY_FILE = "app/entry.py"        # the module the platform starts: python -m app.entry
from .model import Span
from .source import SourceFile, TooLarge, inside, parse_python, read_text

LATEST_REF = re.compile(r"@latest\b")
PLATFORM_SECTION = "platform"   # the platform-owned group: not a section a step reads


@dataclass
class StepSource:
    """What the Python files of one step folder do. `found` is False when the folder does not exist."""
    found: bool = False
    uses_checkpoint: bool = False      # static evidence: kaos_lib.checkpoint, KAOS_CHECKPOINT_DIR, save_state/load_state,
                                       # or a framework the library hooks automatically
    uses_mlflow: bool = False
    registers_model: bool = False
    latest_refs: list = field(default_factory=list)   # (file, Span) of a string holding `@latest`
    has_entry: bool = False            # app/entry.py exists: the module the platform starts
    starts_step: bool = False          # the code calls kaos_lib.step (step.start())
    old_contract: list = field(default_factory=list)  # (file, Span, what): how steps were written before kaos_lib.step


@dataclass
class DatasetDefault:
    """The `dataset:` value of config/dataset.yaml and where it is."""
    file: str
    value: str
    span: Span


def step_folder(name: str) -> str:
    """The folder a step's code lives in: steps/<name with hyphens as underscores>."""
    return f"{STEPS_DIR}/{name.replace('-', '_')}"


def config_sections(root: pathlib.Path) -> Optional[set]:
    """Top-level sections of the config tree (files and group folders of config/), or None without a config folder."""
    cfg = root / CONFIG_DIR
    if not cfg.is_dir() or cfg.is_symlink():
        return None
    names = set()
    for p in cfg.iterdir():
        if p.is_symlink():
            continue
        if p.is_dir():
            names.add(p.name)
        elif p.suffix in (".yaml", ".yml") and p.stem != "config":
            names.add(p.stem)
    main = cfg / "config.yaml"
    if inside(root, main) and main.stat().st_size <= MAX_FILE_BYTES:
        try:
            doc = yaml.safe_load(main.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            doc = None
        if isinstance(doc, dict):
            names.update(str(k) for k in doc if k != "defaults")
    names.discard(PLATFORM_SECTION)
    return names


def dataset_default(root: pathlib.Path) -> Optional[DatasetDefault]:
    """The top-level `dataset:` scalar of config/dataset.yaml with its position, or None."""
    try:
        src = read_text(root, root / CONFIG_DIR / "dataset.yaml", f"{CONFIG_DIR}/dataset.yaml")
        node = yaml.compose(src.text) if src else None
    except (TooLarge, yaml.YAMLError):
        return None
    if not isinstance(node, yaml.MappingNode):
        return None
    for key, value in node.value:
        if getattr(key, "value", None) == "dataset" and isinstance(value, yaml.ScalarNode):
            a, b = value.start_mark, value.end_mark
            return DatasetDefault(src.rel, str(value.value), Span(a.line + 1, a.column + 1, b.line + 1, b.column + 1))
    return None


PLATFORM_DEFAULT = re.compile(r"^(\s*)-\s*(?:override\s+)?/?platform\s*:.*$")   # `- platform: live` in a defaults list
ROOT_CONFIG = f"{CONFIG_DIR}/config.yaml"


def platform_group(root: pathlib.Path) -> list:
    """Where the app still carries the `platform` config group the platform no longer has: `(file, Span, what)`
    for each `- platform: ...` line of config/config.yaml and for a config/platform/ folder."""
    found = []
    try:
        src = read_text(root, root / ROOT_CONFIG, ROOT_CONFIG)
    except TooLarge:
        src = None
    for number, line in enumerate(src.text.splitlines() if src else (), 1):
        if PLATFORM_DEFAULT.match(line):
            start = len(line) - len(line.lstrip()) + 1
            found.append((ROOT_CONFIG, Span(number, start, number, len(line.rstrip()) + 1), "line"))
    if (root / CONFIG_DIR / PLATFORM_SECTION).is_dir():
        found.append((ROOT_CONFIG if src else PIPELINE_FILE, Span(1, 1, 1, 1), "folder"))
    return found


def _scan_python(src: SourceFile, out: StepSource) -> None:
    """Fold one parsed step file into the step's facts (imports, names, string constants)."""
    docstrings = {id(n.body[0].value) for n in ast.walk(src.tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(src.tree):
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            mods = [base] + [f"{base}.{a.name}" for a in n.names]
        else:
            mods = []
        for m in mods:
            top = m.split(".")[0]
            out.uses_checkpoint |= m.endswith("kaos_lib.checkpoint") or top in CHECKPOINT_FRAMEWORKS \
                or m == "kubecore.checkpoint_helper"
            out.uses_mlflow |= "mlflow" in m.lower()
        if isinstance(n, ast.Name) and "mlflow" in n.id.lower():
            out.uses_mlflow = True
        if isinstance(n, ast.Name):
            out.uses_checkpoint |= n.id in CHECKPOINT_STATE_NAMES
        if isinstance(n, ast.Attribute):
            out.uses_checkpoint |= n.attr in CHECKPOINT_STATE_NAMES
            out.uses_mlflow |= "mlflow" in n.attr.lower()
            out.registers_model |= "register_model" in n.attr or "registered_model" in n.attr
        if isinstance(n, ast.keyword) and n.arg and "registered_model" in n.arg:
            out.registers_model = True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            out.uses_mlflow |= "mlflow" in n.value.lower()
            out.uses_checkpoint |= CHECKPOINT_DIR_ENV in n.value
            out.registers_model |= n.value.startswith("models:/")
            if LATEST_REF.search(n.value):
                out.latest_refs.append((src.rel, src.span(n)))
            if n.value == OLD_ENTRY_ARGUMENT:
                out.old_contract.append((src.rel, src.span(n), f"takes {OLD_ENTRY_ARGUMENT} on its command line"))
            elif n.value in OLD_ENTRY_VARIABLES:
                out.old_contract.append((src.rel, src.span(n), f"reads {n.value} from the environment"))
        if isinstance(n, ast.Attribute) and n.attr == "start" and isinstance(n.value, ast.Name) and n.value.id == "step":
            out.starts_step = True


def read_step_source(root: pathlib.Path, name: str) -> StepSource:
    """The facts of a step's folder. Limits apply: at most MAX_STEP_FILES files and MAX_STEP_BYTES bytes."""
    out, folder = StepSource(), root / step_folder(name)
    if not folder.is_dir() or folder.is_symlink():
        return out
    out.found = True
    budget, count = MAX_STEP_BYTES, 0
    for path in sorted(folder.rglob("*")):
        if path.suffix not in (".py", ".toml", ".txt") or not inside(root, path):
            continue
        count += 1
        size = path.stat().st_size
        if count > MAX_STEP_FILES or size > MAX_FILE_BYTES or size > budget:
            continue   # beyond the limits: skipped, the facts stay what was read
        budget -= size
        src = read_text(root, path)
        if src is None:
            continue
        if path.suffix == ".py":
            out.has_entry |= path.relative_to(folder).as_posix() == ENTRY_FILE
            if parse_python(src) is not None:
                _scan_python(src, out)
        else:   # dependency files: an `mlflow` dependency counts as MLflow use
            out.uses_mlflow |= "mlflow" in src.text.lower() and path.name != "poetry.lock"
    return out
