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
import sys
from dataclasses import dataclass, field
from typing import Optional

from . import lock, runtime
from .errors import AuthError, LockError, NotFoundError, StepError

ENV = runtime.STEP_CONTEXT_ENV
VERSION = 1                         # of the context and of the result
CONTEXT_CAP = 96 * 1024             # bytes
RESULT_CAP = 32 * 1024              # bytes
KINDS = ("ingest", "transform", "train", "evaluate", "publish", "control")
WORK = "/work"                      # the step's working folder
RESULT_FILE = "/work/output/kaos-result.json"
RESERVED_PREFIX = "kaos-"


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
        if entry["name"].startswith(RESERVED_PREFIX) or entry["name"] in [p.name for p in out]:
            _fail(f"{where}: the name {entry['name']!r} is reserved or used twice.")
        out.append(Produce(entry["name"], entry["type"], entry["repo"], entry.get("promote") is True))
    return tuple(out)


def parse(text: str) -> Step:
    """The step context from its text; StepError saying what is wrong. Fields it does not know are ignored."""
    size = len(text.encode("utf-8"))
    if size > CONTEXT_CAP:
        _fail(f"the step context is {size} bytes; the limit is {CONTEXT_CAP}. Move large values out of the "
              "config into a dataset or an artifact.")
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
        self.checks: dict = {}       # produce name -> (layout, min_files)
        self.done = False
        self.pid = os.getpid()
        self.exit_code = None        # what sys.exit was called with
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


def start(environ=None) -> Step:
    """Read and check the step context; call it once, first. A second call returns the same step."""
    global _running
    if _running is not None:
        return _running.step
    text = (os.environ if environ is None else environ).get(ENV)
    if not text:
        _fail(f"this is not a pipeline step: {ENV} is not set. Run the step with: kaosctl step run <step>")
    step = parse(text)
    lock.DataLock.replay(_pinned(step))
    lock.strict(step.step)
    _running = _Running(step)
    _watch_exit(_running)
    return step


def stop() -> None:
    """Forget the running step (tests; a long-lived process between steps)."""
    global _running
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


def input(name: str) -> pathlib.Path:  # noqa: A001 - the contract's name
    """The folder holding the input ``name``: a dataset the run pinned (``inputs=``), or a dataset, model or
    artifact a step in ``needs=`` wrote. Downloaded once, or the copy staged beside an HPC (Slurm) job."""
    from . import datasets
    run = _need()
    step = run.step
    read = _pinned(step).named(name)
    write = None if read else _upstream_write(step, name)
    if read is None and write is None:
        known = [r.name for r in _pinned(step).reads] + [w.name for up in step.upstream.values() if up
                                                         for w in up.writes]
        _fail(f"'{name}' is not an input of step '{step.step}'. Its inputs are: {_names(known)}. "
              "Add it to inputs=[...] in pipeline.py.")
    try:
        if read is not None:
            return _dataset(run, datasets, name, read)
        return _artifact(run, name, write)
    except NotFoundError:
        entry = read or write
        _fail(f"input '{name}': commit {entry.commit} of {entry.repo} does not exist any more.")


def _dataset(run: _Running, datasets, name: str, read: lock.Read) -> pathlib.Path:
    from .layouts import local
    ref = datasets.DatasetRef(read.repo, read.ref, owner=read.owner)
    if os.environ.get(local.STAGED_ENV) and not local.staged_dir(read.commit, repo=read.repo, owner=read.owner):
        print(f"input '{name}': no whole staged copy of {read.repo} at {read.commit}; downloading it.", flush=True)
    entry = datasets.materialize(ref, client=run.client, commit=read.commit)
    return entry if entry.is_dir() else entry.parent


def _artifact(run: _Running, name: str, write: lock.Write) -> pathlib.Path:
    """A model or an artifact of this run: ``<name>/<experiment>/<run>/`` of its repository, at the written commit."""
    from .layouts import local
    from .outputs import run_prefix
    step = run.step
    prefix = run_prefix(step.experiment, step.run, name)
    target = local.cache_dir(write.repo, write.commit, prefix)
    if not local.marker_matches(target, write.repo, write.commit, prefix):
        local.fetch(run.client, write.repo, write.commit, [prefix], target, prefix, strip=prefix,
                    empty_message=f"input '{name}': {write.repo} holds no files under {prefix} at {write.commit}.")
    return target


def upstream(step: str, required: bool = True) -> Optional[Upstream]:
    """The result of the earlier step ``step`` (a step named in ``needs=``).

    A step that was skipped, or that ended without ``step.result()``, left no result: that raises, naming it.
    With ``required=False`` it returns None instead, for a step that can work without it.
    """
    mine = _need().step
    if step not in mine.upstream:
        _fail(f"step '{step}' is not upstream of '{mine.step}'. Add needs=['{step}'] in pipeline.py.")
    found = mine.upstream[step]
    if found is None and required:
        _fail(f"step '{step}' wrote no result: it was skipped, or it ended without step.result(). "
              f"'{mine.step}' needs it. Use upstream('{step}', required=False) if this step can run without it.")
    return found


# ------------------------------------------------------------------------------------------------------ outputs
def _produce(run: _Running, name: str) -> Produce:
    found = next((p for p in run.step.produces if p.name == name), None)
    if found is None:
        _fail(f"'{name}' is not produced by step '{run.step.step}'. It produces: "
              f"{_names(p.name for p in run.step.produces)}. Add it to produces=[...] in pipeline.py.")
    return found


def output(name: str) -> pathlib.Path:
    """A local folder for the output ``name`` (declared in ``produces=``). What it holds when ``result()`` is
    called is saved; nothing is saved before."""
    run = _need()
    _produce(run, name)
    if name not in run.outputs:
        folder = pathlib.Path(WORK) / "kaos" / "outputs" / name
        folder.mkdir(parents=True, exist_ok=True)
        run.outputs[name] = folder
    return run.outputs[name]


def check(name: str, layout: Optional[str] = None, min_files: int = 1) -> None:
    """A condition the output ``name`` must meet before it is saved: at least ``min_files`` files and, with
    ``layout``, the rules of that dataset layout. Checked inside ``result()``; a failure saves nothing."""
    run = _need()
    _produce(run, name)
    run.checks[name] = (layout, min_files)


def _files(folder: pathlib.Path) -> int:
    from .transfer import local_files
    return len(local_files(folder))


def _problems(run: _Running, produce: Produce) -> list:
    folder = run.outputs.get(produce.name)
    if folder is None:
        return [f"output '{produce.name}' was not written: step '{run.step.step}' declares it in produces= and "
                f"never called step.output('{produce.name}')."]
    count = _files(folder)
    if count == 0:
        return [f"output '{produce.name}' is empty: the step wrote no files into {folder}."]
    layout, min_files = run.checks.get(produce.name, (None, 1))
    found = [f"it holds {count} files; at least {min_files} are needed"] if count < min_files else []
    if layout:
        from . import layouts
        found += layouts.load(layout, run.client).validate(folder).errors
    return [f"output '{produce.name}' failed its check:\n  " + "\n  ".join(found) + "\nNothing was saved."] \
        if found else []


def _save(run: _Running, produce: Produce, folder: pathlib.Path) -> str:
    """Save one output; returns the commit that holds it."""
    step = run.step
    reads = {f"read.{r.name}": r.commit for r in lock.current().reads}
    try:
        if produce.type == "dataset":
            _fail(f"output '{produce.name}': this kaos-lib does not write datasets yet.")
        from .outputs import RunWriter
        writer = RunWriter(step.app, step.experiment, step.run, produce.name, run.client)
        writer.repo = produce.repo
        with writer:
            writer.save(folder)
            return writer.finish({"step": step.step, **reads})
    except AuthError as exc:
        _fail(f"this app may not write {produce.repo}: only what the step declares in produces=[...] in "
              f"pipeline.py can be written. ({exc})")


# ------------------------------------------------------------------------------------------------------- result
def _result(values: dict, writes: list) -> dict:
    return {"version": VERSION, "status": "ok", "values": values,
            "reads": [r.as_dict() for r in lock.current().reads], "writes": [w.as_dict() for w in writes]}


def _sized(result: dict) -> str:
    text = lock.wire(result)
    if len(text) > RESULT_CAP:
        sizes = {k: len(lock.wire(v)) for k, v in result["values"].items()}
        big = max(sizes, key=sizes.get) if sizes else None
        hint = f" The largest value is '{big}' ({sizes[big]} bytes): save it with step.output() instead." if big else ""
        _fail(f"the result is {len(text)} bytes; the limit is {RESULT_CAP}.{hint}")
    return text


def result(**values) -> None:
    """Save every output and hand the result on. ``values`` are small JSON values for the steps that need this
    one (``step.upstream(...).values`` there). Call it once, last; a step with nothing to hand on calls
    ``step.result()``."""
    run = _need()
    if run.done:
        _fail("step.result() was already called.")
    for key, value in values.items():
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
    for produce in produces:
        commit = _save(run, produce, run.outputs[produce.name])
        lock.current().wrote(lock.Write(produce.name, produce.type, produce.repo, commit))
    text = _sized(_result(values, lock.current().writes))
    _ledger_on_mlflow()
    target = pathlib.Path(RESULT_FILE)
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
    """A step that ends well without a result would hand nothing on. Make that a failure of this step."""
    real_exit, real_hook = sys.exit, sys.excepthook

    def exit_(code=0):
        run.exit_code = code
        real_exit(code)

    def hook(*args):
        run.raised = True
        real_hook(*args)

    sys.exit, sys.excepthook = exit_, hook
    atexit.register(_at_exit, run)


def leaving(code) -> None:
    """Tell the step that the process is about to exit with ``code`` on purpose (kaos-lib's own exits)."""
    if _running is not None:
        _running.exit_code = code


def _ended_without_result(run: _Running) -> bool:
    return (run is _running and not run.done and not run.raised and run.exit_code in (None, 0)
            and os.getpid() == run.pid)


def _at_exit(run: _Running) -> None:
    if _ended_without_result(run):
        print(f"ERROR: step '{run.step.step}' ended without step.result(): the next step would get nothing. "
              "Call step.result() as the last line.", file=sys.stderr, flush=True)
        sys.stdout.flush()
        os._exit(1)
