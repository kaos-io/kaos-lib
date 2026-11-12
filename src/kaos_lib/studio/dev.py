"""`kaosctl dev`: one ready Python environment per step (PRD-CONSOLE-1682 F-29, D-15).

Why: a client should be able to open a step in an editor and run it without working out its dependencies. The
environment is built from what the step's Dockerfile installs (read, not run), with the Python minor version of the
step's base image when this machine has it, kaos-lib at the version a build would install, and a VS Code interpreter
hint. Steps whose dependencies are several GB (torch, CUDA, tensorflow) are skipped unless asked for (OQ-19).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from . import kaoslib, pyenv, steps, vscode
from .constants import LOCAL_DIR
from .deps import StepDeps, read_step_deps


@dataclass
class DevOutcome:
    """The result for one step, as printed in the summary."""
    step: str
    status: str
    detail: str = ""


def requirements_text(deps: StepDeps, spec: kaoslib.KaosLibSpec) -> str:
    """The requirements file the environment is installed from: indexes first, the step's lines, then kaos-lib.

    A `--index-url` in a step's file (a CUDA wheel index) becomes an extra index here: the step's other packages
    still come from PyPI, which is how its image gets them (a separate `pip install` per file).
    """
    extra = {url for _, url in deps.index_options}
    if deps.declares_kaos_lib_arg or deps.imports_kaos_lib:
        extra.update(spec.index_urls)
    lines = [f"--extra-index-url {url}" for url in sorted(extra)]
    lines += deps.requirements
    if deps.declares_kaos_lib_arg or deps.imports_kaos_lib:
        lines.append(spec.requirement)     # a step that never uses kaos-lib does not get it (data-summary: PyYAML only)
    return "\n".join(lines) + "\n"


def setup_step(step: steps.StepInfo, spec_flag: Optional[str], context: Optional[str], uv: Optional[str],
               echo=print, editor_hint: bool = False) -> DevOutcome:
    """Set up one step's environment and interpreter hint. Never runs the step's code."""
    deps = read_step_deps(step.path)
    spec = kaoslib.resolve(spec_flag, context, deps.kaos_lib_default)
    python, note = pyenv.find_python(deps.python, uv)
    for n in deps.notes:
        echo(f"  note: {n}")
    result = pyenv.ensure_env(pyenv.step_env(step.path), requirements_text(deps, spec), python, uv)
    if result.status == "failed":
        echo(result.log[-2000:])
        return DevOutcome(step.name, "failed", result.note)
    hint = vscode.write_interpreter_hint(step.path) if editor_hint else "unchanged"
    uses = deps.declares_kaos_lib_arg or deps.imports_kaos_lib
    detail = f"Python {result.python}" + (f", kaos-lib from {spec.source}" if uses else "")
    extras = [n for n in (note, "" if hint in ("written", "unchanged") else hint) if n]
    return DevOutcome(step.name, result.status, "; ".join([detail] + extras))


def run_dev(args) -> int:
    """The `kaosctl dev` command. Exit 0 when every selected step is ready, 1 when one failed."""
    root = steps.repo_root(args.path)
    wanted = steps.select(root, args.step)
    uv = pyenv.find_uv()
    if not uv:
        print("NOTE: " + pyenv.UV_INSTALL_HELP)
    outcomes, skipped = [], []
    for step in wanted:
        if not args.step and not args.all and read_step_deps(step.path).heavy():
            skipped.append(step)
            continue
        print(f"{step.name}: setting up its environment in {pyenv.step_env(step.path)} ...")
        outcomes.append(setup_step(step, args.kaos_lib, args.context, uv, editor_hint=args.vscode))
    for o in outcomes:
        print(f"  {o.step}: {o.status} ({o.detail})" if o.detail else f"  {o.step}: {o.status}")
    for s in skipped:
        heavy = ", ".join(read_step_deps(s.path).heavy()[:3])
        print(f"  {s.name}: skipped, its dependencies are large ({heavy} ...). Set it up with: kaosctl dev --step {s.name}")
    failed = [o for o in outcomes if o.status == "failed"]
    if failed:
        print(f"ERROR: {len(failed)} step(s) could not be set up: {', '.join(o.step for o in failed)}.", file=sys.stderr)
        return 1
    print(f"Next: kaosctl step run <step>   (environments live in your cache folder; {LOCAL_DIR} is where runs write)")
    return 0
