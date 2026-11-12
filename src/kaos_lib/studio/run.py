"""`kaosctl step run <step>`: run one step on this machine with the platform's contract (PRD-CONSOLE-1682 F-30, D-16).

Why: trying a step should not need a cluster. The step is started as the platform starts it, `python -m app.entry` with
no arguments and the step context in `$KAOS_STEP_CONTEXT`, in its own environment. What differs from the platform is
only where things are: the `/work` folder is mapped into `.kaos/local/work/<step>`, each input is a folder under
`.kaos/local/staged/` (a local folder, or a small sample of a dataset), the step's outputs are kept there too and are
never uploaded, and its result is kept in `.kaos/local/results/<step>.json` for the next step. It inherits only an
allowlisted environment (CON-16) and needs no login or network unless a sample of a dataset is asked for.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import shutil
import sys

import yaml

from .. import datasets, lock, testing
from ..errors import KaosLibError
from ..lint.constants import STEP_KINDS
from . import envallow, pipeline_engine, pyenv, proc, sample, steps
from .constants import LOCAL_DIR, LOCAL_RUN_ID, OUTPUT_PRINT_CHARS
from .dev import setup_step

RESULT_NAME = "kaos-result.json"
PLATFORM_SECTIONS = ("platform", "plan")

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
    """The step's Python: `--python` as given (nothing is built), else the step's environment in the cache folder,
    set up first (as `kaosctl dev` would) when it is not there."""
    if args.python:
        py = pathlib.Path(os.path.abspath(args.python))      # the step starts in its own folder: a relative path would not resolve
        if not py.is_file():
            raise KaosLibError(f"--python {args.python}: no such interpreter ({py}).")
        if not proc.run([str(py), "-c", "import kaos_lib"]).ok:
            raise KaosLibError(f"--python {args.python} cannot import kaos_lib: install kaos-lib into that "
                               "environment. Nothing was changed there.")
        return py
    py = pyenv.venv_python(pyenv.step_env(step.path))
    if not py.is_file():
        print(f"{step.name} has no environment yet: setting it up (kaosctl dev --step {step.name}) ...")
        outcome = setup_step(step, args.kaos_lib, args.context, pyenv.find_uv())
        if outcome.status == "failed":
            raise KaosLibError(f"cannot set up the environment of {step.name}: {outcome.detail}")
    return py


def compose_params(root: pathlib.Path, args, local: pathlib.Path) -> str:
    """The composed params.yaml text: `--params-file`, else the platform's pipeline engine (fetched, checked and run
    as `kaosctl render` does)."""
    if args.params_file:
        try:
            return pathlib.Path(args.params_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise KaosLibError(f"cannot read --params-file {args.params_file}: {exc.strerror or exc}") from None
    try:
        pin = pipeline_engine.resolve_pin(getattr(args, "engine_wheel", None), args.context)
    except KaosLibError as exc:
        raise KaosLibError("To run with the settings you have, write a params.yaml (a section per config file the step "
                           "reads, e.g. `prepare:` with `min_bytes: 1` below it) and pass --params-file params.yaml. "
                           "Composing the settings from config/ needs the platform's pipeline-context file for your "
                           f"app, which you do not make yourself. {exc}") from None
    py = pipeline_engine.ensure(root, pin, pyenv.find_uv())
    profile = pipeline_engine.profile_of(root, getattr(args, "profile", None))
    return pipeline_engine.compose(root, py, profile, list(args.override), local / "params.yaml")


def _dataset_of(params: dict, name: str) -> tuple:
    """`(repository, ref)` the config names for the input (`<repository>@<ref>`), for the ledger: what a real run
    would have pinned. A setting that holds no reference gives `dataset-<name>` at `local`."""
    value = params.get(name)
    repo, _, ref = value.rpartition("/")[2].partition("@") if isinstance(value, str) else ("", "", "")
    return repo or datasets.dataset_repo(name), ref or "local"


def stage_inputs(step: steps.StepInfo, args, params: dict, staged: pathlib.Path) -> list:
    """Put every input of the step in `staged/<name>` and return the ledger reads that name them."""
    given = {}
    for item in args.input or []:
        name, eq, value = item.partition("=")
        if not eq or not value:
            raise KaosLibError(f"--input {item!r}: write NAME=<folder> or NAME=<dataset>@<version>.")
        if name not in step.inputs:
            raise KaosLibError(f"--input {name}: {step.name} has no input '{name}'. Its inputs (inputs= in "
                               f"pipeline.py) are: {', '.join(step.inputs) or 'none'}.")
        given[name] = value
    reads = []
    for name in step.inputs:
        if name not in given:
            raise KaosLibError(f"{step.name} reads the input '{name}'. Give it with --input {name}=<folder> (a folder "
                               f"on this machine) or --input {name}=<dataset>@<version> (a small sample; needs "
                               "`kaosctl login`).")
        target, value = staged / name, given[name]
        repo, ref = _dataset_of(params, name)
        if pathlib.Path(value).is_dir():
            reads.append(testing.stage_input(staged, name, value, repo, ref))
            where = f"the folder {value}"
        else:
            shutil.rmtree(target, ignore_errors=True)
            files, size = sample.pull_sample(value, target, args.sample_mb)
            reads.append(testing.mark(target, sample.repository(value), value.partition("@")[2], sample.layout(value)))
            where = f"a sample of {value} ({files} file(s), {size // 1024} KiB)"
        print(f"  input {name}: {where}")
    return reads


def upstream_results(step: steps.StepInfo, args, results: pathlib.Path) -> dict:
    """The result of every step this one needs: `--upstream`, else its last local run, else "did not run"."""
    given = {}
    for item in args.upstream or []:
        name, eq, value = item.partition("=")
        if not eq or name not in step.needs:
            raise KaosLibError(f"--upstream {item!r}: write STEP=<json> or STEP=@<file>, for a step {step.name} "
                               f"needs ({', '.join(step.needs) or 'it needs none'}).")
        given[name] = pathlib.Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
    out = {}
    for name in step.needs:
        kept = results / f"{name}.json"
        text = given.get(name) or (kept.read_text(encoding="utf-8") if kept.is_file() else None)
        try:
            out[name] = json.loads(text) if text else dict(testing.ABSENT)
        except ValueError as exc:
            raise KaosLibError(f"the result given for {name} is not JSON ({exc}).") from None
        where = "from --upstream" if name in given else f"from its last local run ({kept.name})" if text else \
            "did not run here: the step sees it as not run. Run it first, or give its result with --upstream"
        print(f"  upstream {name}: {where}")
    return out


def step_context(root: pathlib.Path, step: steps.StepInfo, params: dict, reads: list, upstream: dict) -> dict:
    """The step context of a local run, in the contract's field order."""
    if step.kind not in STEP_KINDS:
        raise KaosLibError(f"{step.name} has no kind in pipeline.py: add kind=\"...\", one of {', '.join(STEP_KINDS)}.")
    app = re.sub(r"[^a-z0-9-]", "-", root.name.lower()).strip("-") or "app"
    experiment = (params.get("experiment") or {}).get("name") if isinstance(params.get("experiment"), dict) else None
    run = f"{LOCAL_RUN_ID}-{datetime.datetime.now(datetime.timezone.utc):%Y%m%dt%H%M%Sz}"
    # As on the platform: a step gets the config sections it names in reads=, never the platform's own.
    own = {k: v for k, v in params.items() if k in step.reads and k not in PLATFORM_SECTIONS}
    return testing.local_context(run=run, app=app, step_name=step.name, kind=step.kind, params=own, reads=reads,
                                 experiment=experiment if isinstance(experiment, str) and experiment else app,
                                 produces=step.produces, upstream=upstream)


def child_env(work: pathlib.Path, staged: pathlib.Path, context: dict) -> dict:
    """The environment of the step: the allowlist, the step context and where this machine keeps things. Nothing
    from the platform."""
    return {**envallow.allowed(os.environ), "KAOS_STEP_CONTEXT": lock.wire(context), "KAOS_LOCAL_WORK": str(work),
            "KAOS_STAGED_ROOT": str(staged), "PYTHONUNBUFFERED": "1"}


def print_result(step: steps.StepInfo, work: pathlib.Path, results: pathlib.Path, staged: pathlib.Path) -> None:
    """Print the step's result and keep it where the next step's run will look."""
    file = work / "output" / RESULT_NAME
    kept = results / f"{step.name}.json"
    if not file.is_file():
        kept.unlink(missing_ok=True)
        print(f"Result of {step.name}: none written. The steps that need it would see it as not run.")
        return
    text = file.read_text(encoding="utf-8", errors="replace")
    results.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    try:
        result = json.loads(text)
    except ValueError:
        result = {}
    values = json.dumps(result.get("values", {}))
    print(f"Result of {step.name} (kept in {kept}):")
    print("  values: " + (values if len(values) <= OUTPUT_PRINT_CHARS else values[:OUTPUT_PRINT_CHARS] + "..."))
    for read in result.get("reads", []):
        print(f"  read    {read.get('name')}: {read.get('repo')} at {str(read.get('commit'))[:12]}")
    for write in result.get("writes", []):
        print(f"  wrote   {write.get('name')} ({write.get('type')}): {staged / str(write.get('name'))}")


def run_step(args) -> int:
    """The `kaosctl step run` command. Returns the step's own exit code, or 1 when it could not be started."""
    root = steps.repo_root(args.path)
    step = steps.find(root, args.step)
    py = ensure_environment(step, args)
    local = local_dir(root)
    work, staged, results = local / "work" / step.name, local / "staged", local / "results"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)     # /work exists in the platform's container; /work/output does not until the step makes it
    staged.mkdir(exist_ok=True)
    try:
        params = yaml.safe_load(compose_params(root, args, local)) or {}
    except yaml.YAMLError as exc:
        raise KaosLibError(f"the composed parameters are not YAML ({exc}).") from None
    if not isinstance(params, dict):
        raise KaosLibError("the composed parameters are not a mapping.")
    context = step_context(root, step, params, stage_inputs(step, args, params, staged),
                           upstream_results(step, args, results))
    services = envallow.platform_services_read(step.path)
    if services:
        print(f"NOTE: this step reads {', '.join(services)}, which only the platform sets. Here they are not set (no "
              f"platform secret reaches a local run), so a step that needs one stops with its own error, and one that has a fallback (config, a default) runs on it.")
    print(f"Running {step.name}: python -m app.entry (run {context['run']}; the step context holds "
          f"{len(lock.wire(context['params']))} characters of composed params: {', '.join(context['params']) or 'no section'})")
    done = proc.stream([str(py), str(WORKMAP), "app.entry"], env=child_env(work, staged, context), cwd=step.path)
    print_result(step, work, results, staged)
    if done.returncode:
        print(f"ERROR: {step.name} exited with code {done.returncode}.", file=sys.stderr)
    else:
        print(f"Done: {step.name} exited 0. Next: kaosctl step run <the step that needs {step.name}>, or kaosctl build {step.name}")
    return done.returncode
