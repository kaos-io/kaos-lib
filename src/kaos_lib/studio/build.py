"""`kaosctl build [step]`: build a step's image on this machine, as the platform's CI builds it (PRD-CONSOLE-1682
F-32, F-33, F-34, D-17).

Why: a client should be able to see whether an image builds before pushing. The build uses the same Dockerfile, build
arguments (`REGISTRY_URL`, `VERSION`, and `KAOS_LIB_PACKAGE` with its `io.kaos.lib` label when the Dockerfile declares it),
context rule (the step folder; the repository root for compose-and-validate) and architecture as CI's `build-push`.
First the Dockerfile doctor runs (errors stop the build), then an engine is detected and verified; with none usable the
per-OS suggestion is printed and the command stops. The image is tagged locally and is never pushed.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
from typing import Optional

from ..errors import KaosLibError
from ..lint import render
from ..lint.engine import lint_project
from ..lint.model import Report
from . import engine as eng
from . import engine_errors, kaoslib, proc, steps, suggest
from .constants import BUILD_ARCH_ENV, COMPOSE_STEP, LOCAL_IMAGE_PREFIX, LOCAL_REGISTRY, OUTPUT_TAIL_LINES
from .deps import read_step_deps

EXIT_USER_ERROR, EXIT_ERRORS = 1, 2
ARCHES = ("amd64", "arm64")


def target_arch(flag: Optional[str], environ: Optional[dict] = None) -> str:
    """The architecture to build for: `--arch`, else $KAOS_BUILD_ARCH, else amd64 (the platform's default, OQ-23)."""
    value = flag or (environ if environ is not None else os.environ).get(BUILD_ARCH_ENV) or "amd64"
    if value not in ARCHES:
        raise KaosLibError(f"unknown architecture {value!r}: use amd64 or arm64.")
    return value


def git_short_sha(root: pathlib.Path) -> str:
    """The short commit of the repository, or 'nogit' (a local build is tied to the commit like CI's)."""
    done = proc.run(["git", "-C", str(root), "rev-parse", "--short=7", "HEAD"], timeout=10)
    return done.stdout.strip() if done.ok and done.stdout.strip() else "nogit"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-") or "app"


def image_tag(root: pathlib.Path, step: steps.StepInfo, sha: str) -> str:
    """`kaos-local/<app>:<step>-local-<sha>`: the name says it is local, and it is not a registry name."""
    return f"{LOCAL_IMAGE_PREFIX}/{_slug(root.name)}:{step.name}-local-{sha}"


def build_command(exe: str, root: pathlib.Path, step: steps.StepInfo, tag: str, arch: str, registry: str, version: str,
                  spec: Optional[kaoslib.KaosLibSpec], declared: bool, default_spec: Optional[str]) -> list:
    """The engine command, with CI's inputs: Dockerfile, context, REGISTRY_URL, VERSION and the kaos-lib argument and label.

    CI passes `KAOS_LIB_PACKAGE` and the label only to a Dockerfile that declares the ARG. Here the argument is passed when
    a spec was chosen (`--kaos-lib`, `--context`); otherwise the Dockerfile's own default installs, and the label names it.
    """
    context = root if step.name == COMPOSE_STEP else step.path
    cmd = [exe, "build", "--platform", f"linux/{arch}", "-f", str(step.dockerfile), "-t", tag,
           "--build-arg", f"REGISTRY_URL={registry}", "--build-arg", f"VERSION={version}"]
    if declared:
        label = spec.requirement if spec else (default_spec or "")
        if spec:
            cmd += ["--build-arg", f"KAOS_LIB_PACKAGE={spec.requirement}"]
        if label:
            cmd += ["--label", f"io.kaos.lib={label}"]
    return cmd + [str(context)]


def doctor(root: pathlib.Path, selected: list) -> Report:
    """The L-D findings of the selected steps' Dockerfiles, from the same engine `kaosctl lint` runs."""
    report = lint_project(root)
    folders = tuple(f"{s.folder}/Dockerfile" for s in selected)
    report.findings = [f for f in report.findings if f.rule.startswith("L-D") and f.file in folders]
    report.skipped = []
    return report


def _spec(args, step: steps.StepInfo) -> tuple:
    deps = read_step_deps(step.path)
    chosen = kaoslib.resolve(args.kaos_lib, args.context) if (args.kaos_lib or args.context) else None
    return chosen, deps.declares_kaos_lib_arg, deps.kaos_lib_default


def _choose_engine(args, arch: str):
    candidates = eng.detect()
    if args.engine:
        candidates = [c for c in candidates if c[0] == args.engine]
        if not candidates:
            raise KaosLibError(f"--engine {args.engine}: that command was not found on this machine.")
    if not candidates:
        print(suggest.no_engine_message(suggest.detect_platform()), end="")
        return None
    usable, seen = eng.first_usable(candidates, arch)
    if usable is not None:
        return usable
    for v in seen:
        name = v.engine.label if v.engine else "a container engine"
        for p in v.problems:
            print(f"ERROR: {name}: {p.message}\n  Fix: {p.fix}", file=sys.stderr)
    return None


def _report_verification(v: eng.Verification, arch: str) -> None:
    free = f", {v.free_gb:.0f} GB free" if v.free_gb is not None else ""
    print(f"Engine: {v.engine.label} ({v.engine.exe}), {v.engine.arch or 'unknown arch'}{free}; test build ok. "
          f"Building for linux/{arch}.")
    for n in v.notes:
        print(f"  note: {n}")


def run_build(args) -> int:
    """The `kaosctl build` command. 0: built; 2: the doctor found errors; 1: no usable engine, or the build failed."""
    root = steps.repo_root(args.path)
    arch = target_arch(args.arch)
    selected = steps.select(root, [args.step] if args.step else [])
    for s in [s for s in selected if not s.dockerfile.is_file()]:
        print(f"  {s.name}: no Dockerfile, skipped")
    selected = [s for s in selected if s.dockerfile.is_file()]
    if not selected:
        raise KaosLibError("no step with a Dockerfile to build.")
    report = doctor(root, selected)
    if report.findings:
        sys.stdout.write(render.text(report))
    if report.errors:
        print(f"ERROR: the Dockerfile doctor found {report.errors} error(s); fix them, then run kaosctl build again.",
              file=sys.stderr)
        return EXIT_ERRORS
    sha = git_short_sha(root)
    registry, version = args.registry_url or LOCAL_REGISTRY, f"local-{sha}"
    if args.dry_run:
        return _dry_run(args, root, selected, arch, registry, version, sha)
    usable = _choose_engine(args, arch)
    if usable is None:
        return EXIT_USER_ERROR
    _report_verification(usable, arch)
    return _build_all(args, root, selected, usable.engine, arch, registry, version, sha)


def _dry_run(args, root, selected, arch, registry, version, sha) -> int:
    for step in selected:
        spec, declared, default = _spec(args, step)
        cmd = build_command(args.engine or "docker", root, step, image_tag(root, step, sha), arch, registry, version,
                            spec, declared, default)
        print("would run: " + " ".join(cmd))
    return 0


def _build_all(args, root, selected, engine: eng.Engine, arch, registry, version, sha) -> int:
    built = []
    for step in selected:
        spec, declared, default = _spec(args, step)
        tag = image_tag(root, step, sha)
        print(f"Building {step.name} -> {tag}")
        cmd = build_command(engine.exe, root, step, tag, arch, registry, version, spec, declared, default)
        done = proc.stream(cmd, cwd=root, tail=OUTPUT_TAIL_LINES)
        if done.returncode:
            return _explain_failure(step, done)
        built.append(tag)
    print("Built (local only, nothing was pushed): " + ", ".join(built))
    print(f"Next: run a step the way the platform does, for example  {engine.kind} run --rm {built[0]} --params '<params>'")
    return 0


def _explain_failure(step: steps.StepInfo, done: proc.Result) -> int:
    t = engine_errors.translate(done.stdout)
    print(f"ERROR: the build of {step.name} failed (exit {done.returncode}).", file=sys.stderr)
    if t:
        print(f"  {t.message}\n  Fix: {t.fix}", file=sys.stderr)
    else:
        print("  The engine's last lines are above. If the cause is not clear, the Dockerfile doctor and "
              "`kaosctl lint` may point at it.", file=sys.stderr)
    return EXIT_USER_ERROR
