"""`kaosctl step run <step>`: run one step on this machine with the platform's contract (PRD-CONSOLE-1682 F-30, D-16).

Why: trying a step should not need a cluster. The step is started as the platform starts it, `python -m app.entry
--params <composed params> --<upstream output> <json>`, in its own environment, with the platform's `/work` folder mapped
into `.kaos/local/<step>/work` (outputs are `<name>.json` under `work/output`, and are copied to
`.kaos/local/outputs/<step>/` for the next step to read). It inherits only an allowlisted environment (CON-16) and
needs no login or network unless the step itself reaches for them.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
from typing import Optional

from ..errors import KaosLibError
from . import envallow, pyenv, proc, sample, steps
from .constants import (COMPOSE_STEP, LOCAL_DIR, LOCAL_RUN_ID, OUTPUT_PRINT_CHARS, VENV_DIR)
from .dev import setup_step

WORKMAP = pathlib.Path(__file__).with_name("workmap.py")


def local_dir(root: pathlib.Path) -> pathlib.Path:
    """`.kaos/local` of the repository, with a `.gitignore` of `*` so nothing in it is ever committed."""
    path = root / LOCAL_DIR
    path.mkdir(parents=True, exist_ok=True)
    ignore = path / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    return path


def ensure_environment(step: steps.StepInfo, args) -> pathlib.Path:
    """The step's Python, setting its environment up first (as `kaosctl dev` would) when it is not there."""
    py = pyenv.venv_python(step.path / VENV_DIR)
    if not py.is_file():
        print(f"{step.name} has no environment yet: setting it up (kaosctl dev --step {step.name}) ...")
        outcome = setup_step(step, args.kaos_lib, args.context, pyenv.find_uv())
        if outcome.status == "failed":
            raise KaosLibError(f"cannot set up the environment of {step.name}: {outcome.detail}")
    return py


def compose_params(root: pathlib.Path, args, local: pathlib.Path) -> str:
    """The composed params.yaml text: `--params-file`, or `python -m kubecore.compose` in compose-and-validate's environment."""
    if args.params_file:
        try:
            return pathlib.Path(args.params_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise KaosLibError(f"cannot read --params-file {args.params_file}: {exc.strerror or exc}") from None
    if not (root / "kubecore" / "compose.py").is_file():
        raise KaosLibError("this repository has no kubecore/compose.py to compose the parameters: pass --params-file.")
    compose = steps.find(root, COMPOSE_STEP)
    py = ensure_environment(compose, args)
    out = local / "params.yaml"
    env = {**envallow.allowed(os.environ), "PYTHONPATH": str(root)}
    done = proc.run([str(py), "-m", "kubecore.compose", *args.override, "--output", str(out)], env=env, cwd=root, timeout=300)
    if not done.ok:
        raise KaosLibError("composing the parameters failed:\n" + done.text[-1500:])
    return out.read_text(encoding="utf-8")


def read_inputs(step: steps.StepInfo, root: pathlib.Path, given: list) -> dict:
    """The `--<output>` arguments the platform passes: from `--input name=value|@file`, else an earlier local run of
    the step that produces it, else `{}` (the platform's own default for an output that is not there)."""
    wanted = {}
    for up in step.needs:
        upstream = steps.find(root, up)
        for out in upstream.outputs:
            wanted[out] = root / LOCAL_DIR / "outputs" / upstream.name / f"{out}.json"
    values = {}
    for item in given or []:
        name, eq, value = item.partition("=")
        if not eq:
            raise KaosLibError(f"--input {item!r}: write name=value or name=@file.")
        wanted.setdefault(name, None)
        values[name] = pathlib.Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
    for name, path in wanted.items():
        if name not in values:
            values[name] = path.read_text(encoding="utf-8") if path is not None and path.is_file() else "{}"
            where = f"from {path.relative_to(root)}" if path is not None and path.is_file() else "empty ({}); give it with --input"
            print(f"  input --{name}: {where}")
    return values


def child_env(work: pathlib.Path, dataset_dir: Optional[pathlib.Path]) -> dict:
    """The environment of the step: the allowlist, the work-folder mapping and a run id. Nothing from the platform."""
    env = {**envallow.allowed(os.environ), "KAOS_LOCAL_WORK": str(work), "KUBECORE_RUN_ID": LOCAL_RUN_ID,
           "PYTHONUNBUFFERED": "1"}
    if dataset_dir is not None:
        env["KAOS_LOCAL_DATASET_DIR"] = str(dataset_dir)
    return env


def print_outputs(step: steps.StepInfo, work: pathlib.Path, kept: pathlib.Path) -> None:
    """Print the step's outputs and copy them where the next step's run will look."""
    out = work / "output"
    files = sorted(out.glob("*.json")) if out.is_dir() else []
    declared = set(step.outputs)
    print(f"Outputs of {step.name} (the platform's /work/output, here {out}):")
    if not files:
        print("  none written" + (f" (declared: {', '.join(sorted(declared))})" if declared else ""))
    kept.mkdir(parents=True, exist_ok=True)
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        shutil.copyfile(f, kept / f.name)
        shown = text if len(text) <= OUTPUT_PRINT_CHARS else text[:OUTPUT_PRINT_CHARS] + f"... ({len(text)} characters)"
        print(f"  {f.name}: {shown}")
    for missing in sorted(declared - {f.stem for f in files}):
        print(f"  {missing}.json: declared in pipeline.py but not written")


def run_step(args) -> int:
    """The `kaosctl step run` command. Returns the step's own exit code, or 1 when it could not be started."""
    root = steps.repo_root(args.path)
    step = steps.find(root, args.step)
    py = ensure_environment(step, args)
    local = local_dir(root)
    work = local / "work" / step.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)     # /work exists in the platform's container; /work/output does not until the step makes it
    params = compose_params(root, args, local)
    values = read_inputs(step, root, args.input)
    dataset_dir = _pull_sample(args, local)
    services = envallow.platform_services_read(step.path)
    if services:
        print(f"NOTE: this step reads {', '.join(services)}, which only the platform sets. Here they are not set (no "
              f"platform secret reaches a local run), so a step that needs one stops with its own error, and one that has a fallback (config, a default) runs on it.")
    argv = [str(py), str(WORKMAP), "app.entry", "--params", params]
    for name, value in values.items():
        argv += [f"--{name}", value]
    print(f"Running {step.name}: python -m app.entry --params <{len(params)} characters of composed params>"
          + "".join(f" --{n} ..." for n in values))
    done = proc.stream(argv, env=child_env(work, dataset_dir), cwd=step.path)
    print_outputs(step, work, local / "outputs" / step.name)
    if done.returncode:
        print(f"ERROR: {step.name} exited with code {done.returncode}.", file=sys.stderr)
    else:
        print(f"Done: {step.name} exited 0. Next: kaosctl step run <the step that needs {step.name}>, or kaosctl build {step.name}")
    return done.returncode


def _pull_sample(args, local: pathlib.Path) -> Optional[pathlib.Path]:
    if not args.dataset:
        return None
    dest = local / "data" / args.dataset.replace("/", "_").replace("@", "_at_")
    files, size = sample.pull_sample(args.dataset, dest, args.sample_mb)
    print(f"Sample of {args.dataset}: {files} file(s), {size // 1024} KiB in {dest} (KAOS_LOCAL_DATASET_DIR)")
    return dest
