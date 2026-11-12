"""A pipeline step: what the platform gives it and what it hands on.

A step is ``python -m app.entry`` with no arguments. The platform gives it one value, the step context
(``$KAOS_STEP_CONTEXT``), and takes back one file, the result. This module reads the one and writes the other::

    from kaos_lib import step

    ctx = step.start()               # the run, the app, the step and the composed config: ctx.params
    data = step.input("raw")         # a folder holding the dataset version the run pinned for the input "raw"
    out = step.output("report")      # a folder to write into; saved when result() is called
    prev = step.upstream("prepare")  # an earlier step's result: prev.values, prev.reads, prev.writes
    step.result(rows=1200)           # save the outputs and hand the result on: the last call of the step

A step names its inputs and outputs; it never names a version. Which version of a dataset an input is was
chosen when the run was submitted and reached the step as an exact commit. ``pipeline.py`` declares the names:
``inputs=`` for datasets, ``needs=`` for earlier steps, ``produces=`` for what the step writes.

Everything that goes wrong raises ``StepError`` with a message that says what to change, and the step fails:
a step never hands on a partial or an empty result.
"""
from __future__ import annotations

import atexit
import json
import os
import pathlib
import re
import shutil
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional

from . import lock, runtime, writer
from .errors import AuthError, EmptyDataset, LockError, NotFoundError, PermissionDenied, StepError
from .layouts import local

ENV = runtime.STEP_CONTEXT_ENV
VERSION = 1                         # of the context and of the result
CONTEXT_CAP = 96 * 1024             # the most a context may cost (lock.cost)
RESULT_CAP = 8 * 1024               # the most a result may cost
KINDS = ("ingest", "transform", "train", "evaluate", "publish", "control")
WORK = "/work"                      # the step's working folder
RESULT_FILE = "/work/output/kaos-result.json"
RESERVED_PREFIX = "kaos-"
RESERVED_FOLDER = ".kaos"                   # the folder at the root of a dataset that the platform keeps for itself
NAME_MAX = 40
NAME = re.compile(r"^(?=.{1,%d}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?$" % NAME_MAX)   # step, input and produces names
LOCAL_WORK_ENV = "KAOS_LOCAL_WORK"          # set by `kaosctl step run`: the folder that stands for /work there; outputs
                                            # then stay on this machine, under $KAOS_STAGED_ROOT


def _work(path: str) -> pathlib.Path:
    """``path`` (under the working folder), or its place on this machine in a local run."""
    here = os.environ.get(LOCAL_WORK_ENV)
    return pathlib.Path(here + path[len(WORK):]) if here and path.startswith(WORK) else pathlib.Path(path)


@dataclass(frozen=True)
class Produce:
    """One thing the step declares in ``produces=``. ``promote`` (datasets): this run moves the dataset's latest."""
    name: str
    type: str
    repo: str
    promote: bool = False


@dataclass(frozen=True)
class Upstream:
    """The result of an earlier step: its values, the datasets it read and what it wrote."""
    step: str
    values: dict
    reads: tuple = ()
    writes: tuple = ()


@dataclass(frozen=True)
class Step:
    """The step context: where the step runs and what the run pinned for it."""
    run: str
    app: str
    project: str
    step: str
    kind: str
    experiment: str
    params: dict
    ledger: lock.DataLock = field(compare=False, repr=False, default_factory=lock.DataLock)
    produces: tuple = ()
    upstream: dict = field(default_factory=dict)    # step name -> Upstream, or None when that step left no result


# --------------------------------------------------------------------------------------------------- the context
def _fail(message: str):
    raise StepError(message)


def _found(value) -> str:
    return "it is missing" if value is None else f"found {type(value).__name__} {str(value)[:40]!r}"


def _result_of(name: str, entry) -> Optional[Upstream]:
    where = f"the step context: upstream.{name}"
    if not isinstance(entry, dict) or entry.get("version") != VERSION:
        _fail(f"{where} is not a result at version {VERSION} ({_found(entry)}).")
    if entry.get("status") == "absent":
        return None
    if entry.get("status") != "ok":
        _fail(f"{where} has status {entry.get('status')!r}; a result is 'ok' or 'absent'.")
    if not isinstance(entry.get("values"), dict):
        _fail(f"{where} has no values ({_found(entry.get('values'))}).")
    try:
        part = lock.DataLock.parse({"version": lock.VERSION, "reads": entry.get("reads"),
                                    "writes": entry.get("writes")}, where)
    except LockError as exc:
        _fail(str(exc))
    return Upstream(name, entry["values"], tuple(part.reads), tuple(part.writes))


def _produces(entries) -> tuple:
    if not isinstance(entries, list):
        _fail(f"the step context has no produces ({_found(entries)}).")
    out = []
    for i, entry in enumerate(entries):
        where = f"the step context: produces[{i}]"
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) and entry[k]
                                                   for k in ("name", "type", "repo")):
            _fail(f"{where} needs a name, a type and a repo ({_found(entry)}).")
        if entry["type"] not in lock.WRITE_TYPES:
            _fail(f"{where} has type {entry['type']!r}; it is one of {', '.join(lock.WRITE_TYPES)}.")
        if entry["name"].startswith(RESERVED_PREFIX) or entry["name"] in [p.name for p in out] \
                or not NAME.match(entry["name"]):
            _fail(f"{where}: the name {entry['name']!r} is reserved, used twice or not a name (lowercase "
                  f"letters, digits and hyphens, at most {NAME_MAX} characters).")
        out.append(Produce(entry["name"], entry["type"], entry["repo"], entry.get("promote") is True))
    return tuple(out)


def parse(text: str) -> Step:
    """The step context from its text; StepError saying what is wrong. Fields it does not know are ignored."""
    size = lock.cost(text)
    if size > CONTEXT_CAP:
        _fail(f"the step context costs {size}; the limit is {CONTEXT_CAP}. Make the config smaller, or have the "
              "steps this one needs hand on less: large values belong in a dataset or an artifact.")
    try:
        data = json.loads(text)
    except ValueError as exc:
        data = exc
    if not isinstance(data, dict):
        why = data if isinstance(data, ValueError) else f"it is a {type(data).__name__}"
        _fail(f"the step context is not a JSON object ({why}). The platform built it wrongly: report this "
              "with the run's name.")
    if data.get("version") != VERSION or isinstance(data.get("version"), bool):
        _fail(f"the step context has version {data.get('version')!r}; this kaos-lib reads version {VERSION}. "
              "Upgrade kaos-lib in the step's image.")
    for key in ("run", "app", "project", "step", "experiment"):
        if not isinstance(data.get(key), str) or not data[key]:
            _fail(f"the step context has no {key} ({_found(data.get(key))}).")
    if data.get("kind") not in KINDS:
        _fail(f"the step context has kind {data.get('kind')!r}; a step is one of {', '.join(KINDS)}.")
    if not isinstance(data.get("params"), dict):
        _fail(f"the step context has no params ({_found(data.get('params'))}).")
    given = data.get("ledger")
    if not isinstance(given, dict) or given.get("version") != lock.VERSION:
        _fail(f"the step context has no ledger at version {lock.VERSION} ({_found(given)}).")
    try:
        ledger = lock.DataLock.parse(given, "the step context: ledger")
    except LockError as exc:
        _fail(str(exc))
    if not isinstance(data.get("upstream"), dict):
        _fail(f"the step context has no upstream ({_found(data.get('upstream'))}).")
    return Step(data["run"], data["app"], data["project"], data["step"], data["kind"], data["experiment"],
                data["params"], ledger, _produces(data.get("produces")),
                {name: _result_of(name, entry) for name, entry in data["upstream"].items()})


# ------------------------------------------------------------------------------------------------ the running step
class _Running:
    def __init__(self, step: Step):
        self.step = step
        self.outputs: dict = {}      # produce name -> local folder
        self.scratch = None          # the folder step.workdir() gave
        self.copies: dict = {}       # input name -> its writable copy
        self.checks: dict = {}       # produce name -> (layout, min_files)
        self.done = False
        self.pid = os.getpid()
        self.undo = None             # sys.exit, sys.excepthook and atexit.register as they were
        self.late = []               # the exit handlers registered after start()
        self.quit = None             # the exit code of the last sys.exit of the main thread
        self.raised = False          # an exception reached the top
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _connect()
        return self._client


_running: Optional[_Running] = None


def _connect():
    from .lakefs import LakeFS
    return LakeFS.connect()


def _need() -> _Running:
    if _running is None:
        _fail("call step.start() first.")
    return _running


def _pinned(step: Step) -> lock.DataLock:
    """What the step may read: the inputs the run pinned, and the datasets the steps before it wrote."""
    made = [lock.Read(w.repo, w.commit, w.commit, None, w.name)
            for up in step.upstream.values() if up for w in up.writes if w.type == "dataset"]
    return lock.DataLock(step.ledger.reads + made)


def _one_meaning(step: Step) -> None:
    """A name is an input or an output of a step, never both: the folder of an output would replace the input."""
    inputs = {r.name for r in step.ledger.reads} | {w.name for up in step.upstream.values() if up for w in up.writes}
    for produce in step.produces:
        if produce.name in inputs:
            _fail(f"step '{step.step}' writes the output '{produce.name}' and also reads an input named "
                  f"'{produce.name}'. Give the output a different name: an input and an output of one step must "
                  "not share a name.")


def start(environ=None) -> Step:
    """Read and check the step context; call it once, first. A second call returns the same step.

    A context that is missing or cannot be read ends the process: one line on stderr that names the cause, exit
    code 1.
    """
    global _running
    if _running is not None:
        return _running.step
    text = (os.environ if environ is None else environ).get(ENV)
    try:
        if not text:
            _fail(f"this is not a pipeline step: {ENV} is not set. Run the step with: kaosctl step run <step>")
        step = parse(text)
        _one_meaning(step)
    except StepError as exc:        # nothing of the step ran yet: one line that names the cause, no traceback
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    lock.DataLock.replay(_pinned(step))
    lock.strict(step.step)
    for read in step.ledger.reads:  # every declared input is part of what the step read, opened or not
        lock.current().record(read.repo, read.ref, read.commit, read.owner, read.name)
    _running = _Running(step)
    _watch_exit(_running)
    return step


def stop() -> None:
    """Forget the running step (tests; a long-lived process between steps)."""
    global _running
    if _running is not None and _running.undo:
        sys.exit, sys.excepthook, atexit.register = _running.undo
        atexit.unregister(_at_exit)
    _running = None
    lock.strict(None)
    lock.DataLock.replay(None)


# ------------------------------------------------------------------------------------------------------- inputs
def _names(items) -> str:
    return ", ".join(sorted(set(items))) or "none"


def _upstream_write(step: Step, name: str):
    for up in step.upstream.values():
        for write in (up.writes if up else ()):
            if write.name == name:
                return write
    return None


def input(name: str, optional: bool = False, writable: bool = False) -> Optional[pathlib.Path]:  # noqa: A001
    """The folder holding the input ``name``: a dataset the run pinned (``inputs=``), or a dataset, model or
    artifact a step in ``needs=`` wrote. Downloaded once, or the copy staged beside an HPC (Slurm) job. Read-only.

    ``writable=True`` returns a private full copy of it that the step may write into (tools that write beside
    their inputs); the copy costs the input's size in disk and time, and is emptied and made again at each attempt.

    When the name is not there because a needed step did not run, this raises, naming the name and the steps;
    with ``optional=True`` it returns None instead.
    """
    found = _find(name, optional)
    if found is None or not writable:
        return found
    run = _need()
    if name not in run.copies:      # a real copy: a tool may rewrite a file, so no link may reach the staged one
        run.copies[name] = _fresh(_work(WORK) / "kaos" / "inputs" / name, f"input '{name}'")
        shutil.copytree(found, run.copies[name], symlinks=True, dirs_exist_ok=True)
    return run.copies[name]


def _find(name: str, optional: bool) -> Optional[pathlib.Path]:
    from . import datasets
    run = _need()
    step = run.step
    read = _pinned(step).named(name)
    write = None if read else _upstream_write(step, name)
    if read is None and write is None:
        absent = [s for s, up in step.upstream.items() if up is None]
        if absent and optional:
            return None
        known = [r.name for r in _pinned(step).reads] + [w.name for up in step.upstream.values() if up
                                                         for w in up.writes]
        if absent:
            _fail(f"input '{name}' of step '{step.step}' is not there, and {_names(absent)} did not run: a step "
                  f"that did not run produced nothing. Use input('{name}', optional=True) if this step can run "
                  f"without it. What is there: {_names(known)}.")
        _fail(f"'{name}' is not an input of step '{step.step}'. Its inputs are: {_names(known)}. "
              "Add it to inputs=[...] in pipeline.py.")
    try:
        if read is not None:
            return _dataset(run, datasets, name, read)
        return _artifact(run, name, write)
    except NotFoundError:
        entry = read or write
        _fail(f"input '{name}': commit {entry.commit} of {entry.repo} does not exist any more.")
    except EmptyDataset:
        _fail(f"input '{name}': {read.repo} holds no files at the version this run read ({read.ref}). Push data to "
              f"it with `kaosctl dataset push <folder> {read.repo}`, or choose another dataset for '{name}' on the "
              "run form.")


def _dataset(run: _Running, datasets, name: str, read: lock.Read) -> pathlib.Path:
    from . import layouts
    staged = local.staged_dir(read.commit, repo=read.repo, owner=read.owner)
    layout = local.staged_info(staged).get("layout") if staged else None
    if layout:     # the copy says which layout it is: nothing to ask lakeFS
        entry = layouts.load(layout).entry_of(staged, local.cache_dir(read.repo, read.commit, owner=read.owner))
        lock.record(read.repo, read.ref, read.commit, read.owner, read.name)
    else:
        if os.environ.get(local.STAGED_ENV) and not staged:
            print(f"input '{name}': no whole staged copy of {read.repo} at {read.commit}; downloading it.", flush=True)
        ref = datasets.DatasetRef(read.repo, read.ref, owner=read.owner)
        entry = datasets.materialize(ref, client=run.client, commit=read.commit)
    return entry if entry.is_dir() else entry.parent


def _artifact(run: _Running, name: str, write: lock.Write) -> pathlib.Path:
    """A model or an artifact of this run: ``<name>/<experiment>/<run>/`` of its repository, at the written commit."""
    from .outputs import run_prefix
    step = run.step
    staged = local.staged_dir(write.commit, repo=write.repo)
    if staged:
        return staged
    prefix = run_prefix(step.experiment, step.run, name)
    target = local.cache_dir(write.repo, write.commit, prefix)
    if not local.marker_matches(target, write.repo, write.commit, prefix):
        local.fetch(run.client, write.repo, write.commit, [prefix], target, prefix, strip=prefix,
                    empty_message=f"input '{name}': {write.repo} holds no files under {prefix} at {write.commit}.")
    return target


def upstream(step: str, optional: bool = False) -> Optional[Upstream]:
    """The result of the earlier step ``step`` (a step named in ``needs=``).

    A step that did not run (it was skipped) left no result: that raises, naming it. With ``optional=True`` it
    returns None instead, for a step that can work without it.
    """
    mine = _need().step
    if step not in mine.upstream:
        _fail(f"step '{step}' is not upstream of '{mine.step}'. Add needs=['{step}'] in pipeline.py.")
    found = mine.upstream[step]
    if found is None and not optional:
        _fail(f"step '{step}' did not run, so it left no result, and '{mine.step}' needs it. "
              f"Use upstream('{step}', optional=True) if this step can run without it.")
    return found


# ------------------------------------------------------------------------------------------------------ outputs
def _produce(run: _Running, name: str) -> Produce:
    found = next((p for p in run.step.produces if p.name == name), None)
    if found is None:
        _fail(f"'{name}' is not produced by step '{run.step.step}'. It produces: "
              f"{_names(p.name for p in run.step.produces)}. Add it to produces=[...] in pipeline.py.")
    return found


def output(name: str) -> pathlib.Path:
    """The folder for the output ``name`` (declared in ``produces=``), empty the first time it is asked for in
    this attempt. What it holds when ``result()`` is called is saved; nothing is saved before."""
    run = _need()
    _produce(run, name)
    if name not in run.outputs:
        run.outputs[name] = _fresh(_work(WORK) / "kaos" / "outputs" / name, f"output '{name}'")
    return run.outputs[name]


def _fresh(folder: pathlib.Path, what: str) -> pathlib.Path:
    """``folder``, made empty: an earlier attempt's files are never part of this one."""
    if folder.is_symlink():
        _fail(f"{what}: {folder} is a link, and the folder must be a real folder. Nothing was changed.")
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def workdir() -> pathlib.Path:
    """A scratch folder for files that are neither an input nor an output (run folders, caches of ML tools).
    Empty at each attempt, never uploaded."""
    run = _need()
    if run.scratch is None:
        run.scratch = _fresh(_work(WORK) / "kaos" / "scratch", "the work folder")
    return run.scratch


def check(name: str, layout: Optional[str] = None, min_files: int = 1) -> None:
    """A condition the output ``name`` must meet before it is saved: at least ``min_files`` files and, with
    ``layout``, the rules of that dataset layout. Checked inside ``result()``; a failure saves nothing."""
    run = _need()
    _produce(run, name)
    run.checks[name] = (layout, min_files)


def _problems(run: _Running, produce: Produce) -> list:
    """What is wrong with an output before anything is saved: not written, empty, a reserved path, a failed check."""
    from .transfer import local_files
    folder = run.outputs.get(produce.name)
    if folder is None:
        return [f"output '{produce.name}' was not written: step '{run.step.step}' declares it in produces= and "
                f"never called step.output('{produce.name}')."]
    paths = list(local_files(folder))
    if not paths:
        return [f"output '{produce.name}' is empty: the step wrote no files into {folder}."]
    if produce.type == "dataset" and any(p == RESERVED_FOLDER or p.startswith(RESERVED_FOLDER + "/") for p in paths):
        return [f"output '{produce.name}' holds a file in {RESERVED_FOLDER}/, which the platform keeps for itself "
                f"in every dataset. Write it elsewhere."]
    layout, min_files = run.checks.get(produce.name, (None, 1))
    found = [f"it holds {len(paths)} files; at least {min_files} are needed"] if len(paths) < min_files else []
    if layout:
        from . import layouts
        found += layouts.load(layout, run.client).validate(folder).errors
    return [f"output '{produce.name}' failed its check:\n  " + "\n  ".join(found) + "\nNothing was saved."] \
        if found else []


def _keep_locally(produce: Produce, folder: pathlib.Path, root: pathlib.Path) -> str:
    """A local run (``kaosctl step run``) uploads nothing: the output is kept in ``root/<name>``, marked as a whole
    copy so that the next local step finds it as its input. The commit is a hash of the content."""
    from .transfer import fingerprint
    commit = fingerprint(folder)
    target = root / produce.name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(folder, target)
    local.staged_marker(target).write_text(json.dumps(
        {"repo": produce.repo, "commit": commit, "full": True, "layout": "raw", **local.stamp(target)}))
    return commit


def _seal(run: _Running, produce: Produce) -> writer.Sealed:
    from .outputs import run_prefix
    step, dataset = run.step, produce.type == "dataset"
    meta = {"kaos.run": step.run, "kaos.app": step.app, "kaos.step": step.step,
            **{f"kaos.read.{r.name}": r.commit for r in lock.current().reads}}
    if not dataset:       # what the model panel and the outputs repository have always had on a commit
        meta.update(app=step.app, experiment=step.experiment, run=step.run, kind=produce.name)
    return writer.seal(
        run.client, produce.repo, run.outputs[produce.name], name=produce.name,
        prefix="" if dataset else run_prefix(step.experiment, step.run, produce.name),
        branch=writer.run_branch(step.run, step.step, produce.name),
        tag_prefix=writer.keep_prefix(step.run, step.step) if dataset else None,
        message=f"{produce.name}: {step.experiment}/{step.run}", meta=meta)


def _save(run: _Running) -> list:
    """Save every output; returns their ledger writes. Seal all of them first, promote only then: a step that
    fails while writing moves no ``main``. Models and artifacts are promoted before datasets, so that the one
    case that cannot be undone (two datasets promoted, the second merge failing) is as narrow as it can be."""
    if os.environ.get(LOCAL_WORK_ENV):
        root = pathlib.Path(os.environ[local.STAGED_ENV])
        return [lock.Write(p.name, p.type, p.repo, _keep_locally(p, run.outputs[p.name], root))
                for p in run.step.produces]
    sealed, writes, repo = [], [], ""
    try:
        for produce in run.step.produces:
            repo = produce.repo
            sealed.append((produce, _seal(run, produce)))
        for produce, s in sorted(sealed, key=lambda item: item[0].type == "dataset"):
            repo = produce.repo
            commit = writer.promote(s) if produce.type != "dataset" or produce.promote else s.commit
            writes.append(lock.Write(produce.name, produce.type, produce.repo, commit))
    except PermissionDenied as exc:
        _fail(f"this app may not write {repo}: only what the step declares in produces=[...] in pipeline.py can "
              f"be written. ({exc})")
    except AuthError as exc:
        _fail("lakeFS rejected the credential this step was given, or it has expired. The app cannot fix this: "
              f"report it to the platform team with the run's name ({run.step.run}). ({exc})")
    finally:
        for _, s in sealed:
            writer.discard(s)
    order = {p.name: i for i, p in enumerate(run.step.produces)}
    return sorted(writes, key=lambda w: order[w.name])


# ------------------------------------------------------------------------------------------------------- result
def _result(values: dict, writes: list) -> dict:
    return {"version": VERSION, "status": "ok", "values": values,
            "reads": [r.as_dict() for r in lock.current().reads], "writes": [w.as_dict() for w in writes]}


def _sized(result: dict) -> str:
    text = lock.wire(result)
    if lock.cost(text) > RESULT_CAP:
        sizes = {k: lock.cost(lock.wire(v)) for k, v in result["values"].items()}
        big = max(sizes, key=sizes.get) if sizes else None
        hint = f" The largest value is '{big}' ({sizes[big]})." if big else ""
        _fail(f"the result costs {lock.cost(text)}; the limit is {RESULT_CAP}.{hint} A result carries a few small "
              "values: log metrics to MLflow, or write the rest into an artifact with step.output() and hand on "
              "its name.")
    return text


def result(**values) -> None:
    """Save every output and hand the result on. ``values`` are small JSON values for the steps that need this
    one (``step.upstream(...).values`` there). Call it once, last; a step with nothing to hand on calls
    ``step.result()``."""
    run = _need()
    if run.done:
        _fail("step.result() was already called.")
    for key, value in values.items():
        if key.startswith(RESERVED_PREFIX):
            _fail(f"result value '{key}': names starting with '{RESERVED_PREFIX}' are the platform's.")
        try:
            lock.wire(value)
        except (TypeError, ValueError):
            _fail(f"result value '{key}' is a {type(value).__name__}; values are text, numbers, booleans, "
                  "lists and objects.")
    produces = run.step.produces
    problems = [p for produce in produces for p in _problems(run, produce)]
    if problems:
        _fail("\n".join(problems))
    _sized(_result(values, [lock.Write(p.name, p.type, p.repo, "0" * 64) for p in produces]))   # before any save
    for write in _save(run):
        lock.current().wrote(write)
    text = _sized(_result(values, lock.current().writes))
    _ledger_on_mlflow()
    target = _work(RESULT_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_text(text, encoding="ascii")
    os.replace(partial, target)
    run.done = True


def _ledger_on_mlflow() -> None:
    """The step's reads and writes on its MLflow run(s), when it has any. Never fails the step."""
    frameworks = sys.modules.get("kaos_lib.frameworks")
    if frameworks is not None:
        frameworks.rewrite_ledgers()


# ------------------------------------------------------------------------------- a step must not end without one
def _watch_exit(run: _Running) -> None:
    """A step that ends without a result would hand nothing on, so it must end with a non-zero exit code.

    The exit code of the last ``sys.exit(n)`` of the main thread is kept (it is also what ``argparse`` and
    ``checkpoint.exit_for_restart`` use); a step cannot tell whether that exit was the one that ended it, so a
    caught one keeps its code as well. In every other case without a result (a normal end, exit code 0, an exit in
    another thread, a bare ``raise SystemExit(n)``) the step ends with 1. Out of reach: ``os._exit``.
    """
    real_exit, real_hook, real_register = sys.exit, sys.excepthook, atexit.register

    def exit_(code=None):
        if threading.current_thread() is threading.main_thread():
            run.quit = code % 256 if isinstance(code, int) else (0 if code is None else 1)   # the process keeps 8 bits
        real_exit(code)

    def hook(*args):
        run.raised = True
        real_hook(*args)

    def register(func, *args, **kwargs):
        run.late.append(func)
        return real_register(func, *args, **kwargs)

    run.undo = (real_exit, real_hook, real_register)
    sys.exit, sys.excepthook, atexit.register = exit_, hook, register
    real_register(_at_exit, run)


def _at_exit(run: _Running) -> None:
    if run is _running and not run.done and not run.raised and os.getpid() == run.pid:
        code = (run.quit or 0) % 256
        if not code:          # nothing chose a non-zero code: the step would have ended well
            print(f"ERROR: step '{run.step.step}' ended without step.result(): the next step would get nothing. "
                  "Call step.result() as the last line.", file=sys.stderr, flush=True)
        # Exit handlers run last-registered first, so this one has run before those registered before start(). Those
        # that were registered after it have run already: take them off, then run the rest before forcing the exit.
        atexit.unregister(_at_exit)
        for func in run.late:
            atexit.unregister(func)
        atexit._run_exitfuncs()
        sys.stdout.flush()
        os._exit(code or 1)
