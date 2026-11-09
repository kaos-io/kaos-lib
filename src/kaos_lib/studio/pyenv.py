"""Create one virtual environment from a requirements list: `uv` when it is there, `python -m venv` + pip otherwise.

Why: `kaosctl dev` must give a step the Python and the packages of its image. It never installs `uv` (CON-17, OQ-19): a
missing `uv` is suggested and pip is used. It never lets `uv` download a Python either; a Python of the right minor
version is looked for on the machine and, when there is none, the one running kaosctl is used and the difference is said.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import sys
from dataclasses import dataclass
from typing import Optional

from . import proc
from .constants import VENV_DIR

STAMP = ".kaos-env.json"
UV_INSTALL_HELP = ("uv (a fast Python package installer) was not found, so pip is used: slower, same result. To get uv "
                   "yourself: https://docs.astral.sh/uv/getting-started/installation/ (for example `pipx install uv`). "
                   "kaosctl does not install it.")


@dataclass
class EnvResult:
    """What setting up one environment did."""
    status: str                 # created | updated | up-to-date | failed
    python: str = ""            # the interpreter's version, e.g. 3.11.9
    note: str = ""              # a difference or a problem the user should read
    log: str = ""


def find_uv(which=None) -> Optional[str]:
    return (which or shutil.which)("uv")


def venv_python(venv: pathlib.Path) -> pathlib.Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _minor(version_text: str) -> str:
    return ".".join(version_text.split(".")[:2])


def interpreter_version(python: str) -> str:
    out = proc.run([python, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"], timeout=30)
    return out.stdout.strip() if out.ok else ""


def find_python(minor: Optional[str], uv: Optional[str], which=None) -> tuple:
    """(interpreter path, note) for the wanted minor version; falls back to the running Python with a note."""
    which = which or shutil.which
    mine = ".".join(map(str, sys.version_info[:2]))
    if minor is None:
        return sys.executable, "the base image names no Python version: using the Python that runs kaosctl"
    if minor == mine:
        return sys.executable, ""
    candidates = []
    if uv:
        found = proc.run([uv, "python", "find", minor, "--no-python-downloads"], timeout=30)
        if found.ok and found.stdout.strip():
            candidates.append(found.stdout.strip().splitlines()[-1])
    for name in (f"python{minor}", f"python{minor.replace('.', '')}"):
        if which(name):
            candidates.append(which(name))
    for c in candidates:
        if _minor(interpreter_version(c)) == minor:
            return c, ""
    return sys.executable, (f"Python {minor} (the version of the step's image) was not found on this machine; using "
                            f"Python {mine}. Install Python {minor} yourself (https://www.python.org/downloads/ or "
                            f"`uv python install {minor}`) and run kaosctl dev again to match the image.")


def fingerprint(requirements_text: str, minor: str) -> str:
    return hashlib.sha256((minor + "\n" + requirements_text).encode()).hexdigest()


def _read_stamp(venv: pathlib.Path) -> dict:
    try:
        return json.loads((venv / STAMP).read_text())
    except (OSError, ValueError):
        return {}


def _is_venv(path: pathlib.Path) -> bool:
    return (path / "pyvenv.cfg").is_file()


def ensure_env(step_dir: pathlib.Path, requirements_text: str, python: str, uv: Optional[str]) -> EnvResult:
    """Create or update `<step>/.venv` so that it holds exactly `requirements_text`; idempotent."""
    venv = step_dir / VENV_DIR
    version = interpreter_version(python)
    key = fingerprint(requirements_text, _minor(version))
    existing = venv_python(venv).is_file() and _is_venv(venv)
    if existing and _read_stamp(venv).get("fingerprint") == key:
        return EnvResult("up-to-date", version)
    if venv.exists():
        if not _is_venv(venv):
            return EnvResult("failed", version, f"{venv} exists and is not a virtual environment: remove it or rename it")
        if existing and _minor(interpreter_version(str(venv_python(venv)))) != _minor(version):
            shutil.rmtree(venv)                   # wrong Python minor: a venv cannot change its interpreter
            existing = False
        elif not existing:
            shutil.rmtree(venv)                   # a half-made environment from an earlier failure
    if not existing:
        made = _make_venv(venv, python, uv)
        if not made.ok:
            return EnvResult("failed", version, "could not create the virtual environment", made.text)
    req_file = venv / "kaos-requirements.txt"
    req_file.write_text(requirements_text, encoding="utf-8")
    installed = _install(venv, req_file, uv)
    if not installed.ok:
        return EnvResult("failed", version, "installing the dependencies failed (output below)", installed.text)
    (venv / STAMP).write_text(json.dumps({"fingerprint": key, "python": version}))
    _ignore_everything(venv)
    return EnvResult("updated" if existing else "created", version)


def _make_venv(venv: pathlib.Path, python: str, uv: Optional[str]) -> proc.Result:
    if uv:
        return proc.run([uv, "venv", "--python", python, "--no-python-downloads", str(venv)], timeout=300)
    return proc.run([python, "-m", "venv", str(venv)], timeout=300)


def _install(venv: pathlib.Path, req_file: pathlib.Path, uv: Optional[str]) -> proc.Result:
    py = str(venv_python(venv))
    if uv:
        return proc.run([uv, "pip", "install", "--python", py, "-r", str(req_file)], timeout=3600)
    return proc.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req_file)], timeout=3600)


def _ignore_everything(folder: pathlib.Path) -> None:
    """A .gitignore of `*` inside the folder: the environment is never committed, and no file of the repo is edited."""
    ignore = folder / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
