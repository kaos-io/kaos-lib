"""Read what a step installs, statically.

Why: `kaosctl dev` must build an environment like the step's image without running anything of the step. The
declaration is read from the Dockerfile's `pip install` lines, a `requirements.txt`, `pyproject.toml` (`[project]`
or poetry) and `poetry.lock`; text only, no build hook, no import (T-17). Precedence (OQ-17): what the Dockerfile
installs is what the image has, so it wins; a dependency file is read only when the Dockerfile points at it
(`-r file`, `poetry export`) or installs nothing itself.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import Optional

from ..lint import dockerfile as df
from ..lint.constants import KAOS_LIB_ARG
from .constants import HEAVY_PACKAGES

try:                                    # Python 3.11+ reads TOML itself; older Pythons use the tomli package
    import tomllib as _toml
except ImportError:                     # pragma: no cover - exercised on Python < 3.11 only
    import tomli as _toml               # type: ignore

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


@dataclass
class StepDeps:
    """What a step's image installs: the Python version, requirement lines, index options and notes for the user."""
    python: Optional[str] = None                      # "3.11", from the base image; None when it names no python
    base_image: str = ""
    requirements: list = field(default_factory=list)  # PEP 508 lines, exactly as pip would take them
    index_options: list = field(default_factory=list)  # [(flag, value)] from the Dockerfile's pip lines
    kaos_lib_default: Optional[str] = None            # the Dockerfile's ARG KAOS_LIB_PACKAGE default
    declares_kaos_lib_arg: bool = False
    imports_kaos_lib: bool = False                    # a .py file of the step mentions kaos_lib (text search, not run)
    notes: list = field(default_factory=list)         # things the user should know (a file not found, a skipped line)
    sources: list = field(default_factory=list)       # which files were read

    def heavy(self) -> list:
        names = {_name(r) for r in self.requirements}
        return sorted(n for n in names if n in HEAVY_PACKAGES or n.startswith("nvidia-"))


def _name(requirement: str) -> str:
    m = _NAME.match(requirement)
    return re.sub(r"[-_.]+", "-", m.group(1).lower()) if m else ""


def read_step_deps(step_dir: pathlib.Path) -> StepDeps:
    """The dependencies of the step in `step_dir`, read from its files. Never executes anything."""
    deps = StepDeps()
    dockerfile = step_dir / "Dockerfile"
    instructions = df.parse(_read(dockerfile)) if dockerfile.is_file() else []
    froms = df.froms(instructions)
    if froms:
        deps.base_image = froms[-1].image
        deps.python = df.python_version(froms[-1].image)
    deps.declares_kaos_lib_arg, deps.kaos_lib_default = df.arg_default(instructions, KAOS_LIB_ARG)
    deps.imports_kaos_lib = _mentions_kaos_lib(step_dir)
    installs = df.pip_installs(instructions)
    for pip in installs:
        if "/" not in pip.exe:               # /opt/poetry/bin/pip installs into a tool's own environment, not the image's
            _fold_pip(deps, pip, step_dir)
    if df.uses_poetry(instructions):
        _fold_poetry(deps, step_dir)
    if not installs and not deps.requirements:
        _fold_dependency_files(deps, step_dir)
    deps.requirements = _unique(deps.requirements)
    return deps


def _mentions_kaos_lib(step_dir: pathlib.Path, max_files: int = 300, max_bytes: int = 1024 * 1024) -> bool:
    for n, path in enumerate(sorted(step_dir.rglob("*.py"))):
        if n >= max_files:
            break
        try:
            if ".venv" in path.parts or path.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        if re.search(r"^\s*(from|import)\s+kaos_lib\b", _read(path), re.M):
            return True
    return False


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _fold_pip(deps: StepDeps, pip: df.PipInstall, step_dir: pathlib.Path) -> None:
    for spec in pip.specs:
        if KAOS_LIB_ARG in spec:
            continue                         # the library is added separately, at the version the platform passes
        if "$" in spec:
            deps.notes.append(f"skipped {spec!r}: it uses a build argument that is not known locally")
        else:
            deps.requirements.append(spec)
    for name in pip.files:
        if name.startswith(("/tmp/", "/opt/")) or "$" in name:
            continue                         # a file made inside the image (poetry export): handled by the poetry path
        _fold_requirements_file(deps, step_dir / name, name)
    deps.index_options += pip.index_options


def _fold_requirements_file(deps: StepDeps, path: pathlib.Path, label: str) -> None:
    text = _read(path)
    if not text:
        deps.notes.append(f"{label}: file not found next to the Dockerfile")
        return
    deps.sources.append(label)
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("--index-url", "--extra-index-url", "-i ", "-f ", "--find-links")):
            flag, _, value = line.partition(" ") if " " in line else line.partition("=")
            deps.index_options.append((flag, value.strip()))
        elif line.startswith("-r "):
            _fold_requirements_file(deps, path.parent / line[3:].strip(), line[3:].strip())
        elif line.startswith("-"):
            deps.notes.append(f"{label}: option {line.split()[0]!r} is not applied locally")
        else:
            deps.requirements.append(line)


def _fold_poetry(deps: StepDeps, step_dir: pathlib.Path) -> None:
    """Poetry steps: the pinned versions of poetry.lock's main group, else pyproject's constraints (best effort)."""
    lock, pyproject = step_dir / "poetry.lock", step_dir / "pyproject.toml"
    try:
        locked = _toml.loads(_read(lock)) if lock.is_file() else {}
    except _toml.TOMLDecodeError:
        locked = {}
    pins = []
    for p in locked.get("package", []):
        if "main" not in (p.get("groups") or [p.get("category", "main")]):
            continue
        if not (p.get("name") and p.get("version")):
            continue
        pin = f"{p['name']}=={p['version']}"
        marker = p.get("markers")            # poetry.lock stores it as a PEP 508 string (sometimes a per-group dict, skipped)
        if isinstance(marker, str) and marker.strip():   # keep e.g. pywin32's sys_platform == "win32"
            pin += f" ; {marker.strip()}"    # so pip/uv skip a win32-only dep on macOS/Linux, matching the real poetry build
        pins.append(pin)
    if pins:
        deps.sources.append("poetry.lock")
        deps.requirements += pins
        return
    try:
        doc = _toml.loads(_read(pyproject)) if pyproject.is_file() else {}
    except _toml.TOMLDecodeError:
        doc = {}
    table = ((doc.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    if table:
        deps.sources.append("pyproject.toml (poetry)")
    for name, spec in table.items():
        if name.lower() == "python":
            continue
        line = _poetry_requirement(name, spec)
        if line:
            deps.requirements.append(line)
        else:
            deps.notes.append(f"pyproject.toml: dependency {name!r} is not a plain version, skipped")


def _poetry_requirement(name: str, spec) -> Optional[str]:
    if isinstance(spec, dict):
        if set(spec) - {"version", "extras", "optional", "markers", "python"} or spec.get("optional"):
            return None
        extras = f"[{','.join(spec['extras'])}]" if spec.get("extras") else ""
        return f"{name}{extras}{_poetry_constraint(spec['version'])}" if spec.get("version") else None
    return f"{name}{_poetry_constraint(spec)}" if isinstance(spec, str) else None


def _poetry_constraint(text: str) -> str:
    text = text.strip()
    if text in ("*", ""):
        return ""
    m = re.match(r"^\^(\d+)(?:\.(\d+))?(?:\.(\d+))?$", text)
    if m:
        major, minor, patch = (int(g) if g is not None else None for g in m.groups())
        if major:
            upper = f"{major + 1}"
        elif minor:
            upper = f"0.{minor + 1}"
        else:
            upper = f"0.0.{(patch or 0) + 1}"
        return f">={text[1:]},<{upper}"
    m = re.match(r"^~(\d+(?:\.\d+)*)$", text)
    if m:
        parts = [int(x) for x in m.group(1).split(".")]
        upper = [parts[0], parts[1] + 1] if len(parts) > 1 else [parts[0] + 1]
        return f">={m.group(1)},<{'.'.join(map(str, upper))}"
    return text if re.match(r"^[<>=!~]", text) else f"=={text}"


def _fold_dependency_files(deps: StepDeps, step_dir: pathlib.Path) -> None:
    """A Dockerfile that installs nothing itself: take requirements.txt, else pyproject [project], else poetry."""
    req = step_dir / "requirements.txt"
    if req.is_file():
        _fold_requirements_file(deps, req, "requirements.txt")
        return
    pyproject = step_dir / "pyproject.toml"
    try:
        doc = _toml.loads(_read(pyproject)) if pyproject.is_file() else {}
    except _toml.TOMLDecodeError:
        doc = {}
    listed = (doc.get("project") or {}).get("dependencies")
    if listed:
        deps.sources.append("pyproject.toml")
        deps.requirements += [str(x) for x in listed]
    elif (doc.get("tool") or {}).get("poetry"):
        _fold_poetry(deps, step_dir)


def _unique(items: list) -> list:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
