"""A pipeline step: what the platform gives it and what it hands on.

A step is ``python -m app.entry`` with no arguments. The platform gives it one value, the step context
(``$KAOS_STEP_CONTEXT``), and takes back one file, the result. This module reads the one and writes the other::

    from kaos_lib import step

    ctx = step.start()               # the run, the app, the step and the composed config: ctx.params
    data = step.input("raw")         # a folder holding the dataset version the run pinned for the input "raw"
    out = step.output("report")      # a folder to write into; saved when result() is called
    prev = step.upstream("prepare")  # an earlier step's result: prev.values, prev.reads, prev.writes
    runs = step.upstream("train")    # after a step with matrix=: a list with one entry for each item (see Upstream item)
    step.result(rows=1200)           # save the outputs and hand the result on: the last call of the step
    step.skip("not good enough")     # or: end the step as skipped, with the reason; nothing is saved

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
import traceback
from dataclasses import dataclass, field
from typing import Optional

from . import lock, runtime, writer
from .errors import AuthError, EmptyDataset, KaosLibError, LockError, NotFoundError, PermissionDenied, StepError
from .layouts import local

ENV = runtime.STEP_CONTEXT_ENV
VERSION = 1                         # of the context and of the result
CONTEXT_CAP = 96 * 1024             # the most a context may cost (lock.cost)
RESULT_CAP = 8 * 1024               # the most a result may cost
MATRIX_VALUES_CAP = 16 * 1024       # the most the ``values`` of all items of a matrix step may cost together
MATRIX_INT_LIMIT = 2 ** 53             # a whole number in an item's result may not be larger (the next step gets it as a float)
MATRIX_MAX_ITEMS = 32               # the most items (combinations) a matrix step runs
MATRIX_STATUSES = ("ok", "failed", "skipped")
SKIP_REASON_MAX = 300               # characters of the reason of step.skip()
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
    """One thing the step declares in ``produces=``."""
    name: str
    type: str
    repo: str


@dataclass(frozen=True)
class Upstream:
    """The result of an earlier step: its values, the datasets it read and what it wrote."""
    step: str
    values: dict
    reads: tuple = ()
    writes: tuple = ()


@dataclass(frozen=True)
class UpstreamItem:
    """One item of an earlier step that has ``matrix=``: ``step.upstream("train")`` is a list of these, one for each
    combination, in index order. ``values``, ``reads`` and ``writes`` are what the item handed on and are empty
    unless ``status`` is "ok"; ``reason`` is what a skipped item gave to ``step.skip()``."""
    step: str
    index: int
    matrix: dict            # the item's combination: {"lr": 0.01, "batch": 16}
    status: str             # "ok", "failed" (it handed back no result) or "skipped"
    values: dict = field(default_factory=dict)
    reads: tuple = ()
    writes: tuple = ()
    reason: str = ""


@dataclass(frozen=True)
class Matrix:
    """Which item of its ``matrix=`` this run of the step is: ``index`` of ``of``, and the item's ``values``."""
    index: int
    of: int
    values: dict


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
    upstream: dict = field(default_factory=dict)    # step name -> Upstream (a list of UpstreamItem after a step with
                                                    # matrix=), or None when that step left no result
    skipped: dict = field(default_factory=dict)     # step name -> the reason it gave to step.skip(); "" when it did not run
    matrix: Optional[Matrix] = None                 # set when the step has matrix=; its values are also in params


# --------------------------------------------------------------------------------------------------- the context
def _fail(message: str):
    raise StepError(message)


def _found(value) -> str:
    return "it is missing" if value is None else f"found {type(value).__name__} {str(value)[:40]!r}"


def _result_of(name: str, entry) -> tuple:
    """``(Upstream or None, reason)``: ``None`` and ``""`` for a step that did not run (absent), ``None`` and its
    reason for a step that ended itself with ``step.skip()``."""
    where = f"the step context: upstream.{name}"
    if not isinstance(entry, dict) or entry.get("version") != VERSION:
        _fail(f"{where} is not a result at version {VERSION} ({_found(entry)}).")
    if entry.get("status") == "absent":
        return None, ""
    if entry.get("status") == "skipped":
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason:
            _fail(f"{where} is skipped and has no reason ({_found(reason)}).")
        return None, reason
    if entry.get("status") == "matrix":
        return _items_of(name, entry), ""
    if entry.get("status") != "ok":
        _fail(f"{where} has status {entry.get('status')!r}; a result is 'ok', 'skipped', 'matrix' or 'absent'.")
    if not isinstance(entry.get("values"), dict):
        _fail(f"{where} has no values ({_found(entry.get('values'))}).")
    try:
        part = lock.DataLock.parse({"version": lock.VERSION, "reads": entry.get("reads"),
                                    "writes": entry.get("writes")}, where)
    except LockError as exc:
        _fail(str(exc))
    return Upstream(name, entry["values"], tuple(part.reads), tuple(part.writes)), ""


def _scalar(value) -> bool:
    return isinstance(value, (str, bool, int, float))


def _items_of(name: str, entry: dict) -> list:
    """The entries of a step that has ``matrix=``: one ``UpstreamItem`` for each item, in index order."""
    where = f"the step context: upstream.{name}"
    items = entry.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MATRIX_MAX_ITEMS:
        _fail(f"{where} has no items ({_found(items)}); a step with matrix= has 1 to {MATRIX_MAX_ITEMS}.")
    out = []
    for i, item in enumerate(items):
        here = f"{where}.items[{i}]"
        if not isinstance(item, dict) or item.get("index") != i or isinstance(item.get("index"), bool):
            _fail(f"{here} must be the item with index {i}: the items are in index order ({_found(item)}).")
        if not isinstance(item.get("values"), dict):
            _fail(f"{here} has no matrix values ({_found(item.get('values'))}).")
        status = item.get("status")
        if status not in MATRIX_STATUSES:
            _fail(f"{here} has status {status!r}; an item is {', '.join(MATRIX_STATUSES)}.")
        if status == "skipped":
            if not isinstance(item.get("reason"), str) or not item["reason"]:
                _fail(f"{here} is skipped and has no reason ({_found(item.get('reason'))}).")
            out.append(UpstreamItem(name, i, item["values"], status, reason=item["reason"]))
        elif status == "failed":
            out.append(UpstreamItem(name, i, item["values"], status))
        else:
            got, _ = _result_of(f"{name}.items[{i}].result", item.get("result"))
            if got is None:
                _fail(f"{here}.result must be an 'ok' result ({_found(item.get('result'))}).")
            out.append(UpstreamItem(name, i, item["values"], status, got.values, got.reads, got.writes))
    return out


def _matrix_of(entry, params: dict) -> Optional[Matrix]:
    """The ``matrix`` field of the context, checked; None when the step has no ``matrix=``."""
    if entry is None:
        return None
    where = "the step context: matrix"
    if not isinstance(entry, dict):
        _fail(f"{where} is not an object ({_found(entry)}).")
    index, of, values = entry.get("index"), entry.get("of"), entry.get("values")
    if isinstance(of, bool) or not isinstance(of, int) or not 1 <= of <= MATRIX_MAX_ITEMS:
        _fail(f"{where} has of {of!r}; a step with matrix= has 1 to {MATRIX_MAX_ITEMS} items.")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < of:
        _fail(f"{where} has index {index!r}; it is a whole number from 0 to {of - 1}.")
    if not isinstance(values, dict) or not values or not all(isinstance(k, str) and _scalar(v) for k, v in values.items()):
        _fail(f"{where} has values that are not names with a number, a boolean or a text ({_found(values)}).")
    for axis in values:
        if axis in params:
            _fail(f"the name {axis!r} of matrix= is also a setting the step is given (params[{axis!r}]). Rename one "
                  f"of them: the step reads both as step.params[{axis!r}].")
    return Matrix(index, of, values)


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
        out.append(Produce(entry["name"], entry["type"], entry["repo"]))
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
    results = {name: _result_of(name, entry) for name, entry in data["upstream"].items()}
    matrix = _matrix_of(data.get("matrix"), data["params"])
    params = {**data["params"], **matrix.values} if matrix else data["params"]
    produces = _produces(data.get("produces"))
    if matrix and any(p.type == "dataset" for p in produces):
        _fail(f"step '{data['step']}' has matrix= and produces a dataset: a dataset has one writer and one version for "
              "each run. Produce a model or an artifact from the step with matrix=, and let the step after it write "
              "the dataset.")
    return Step(data["run"], data["app"], data["project"], data["step"], data["kind"], data["experiment"],
                params, ledger, produces,
                {name: found for name, (found, _) in results.items()},
                {name: reason for name, (found, reason) in results.items() if found is None}, matrix)


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
            for up in step.upstream.values() if isinstance(up, Upstream) for w in up.writes if w.type == "dataset"]
    return lock.DataLock(step.ledger.reads + made)


def _one_meaning(step: Step) -> None:
    """A name is an input or an output of a step, never both: the folder of an output would replace the input."""
    inputs = {r.name for r in step.ledger.reads} | {w.name for _, _, w in _entries(step)}
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


def _entries(step: Step):
    """``(step name, item index or None, write)`` for everything the steps before this one wrote."""
    for name, up in step.upstream.items():
        if isinstance(up, Upstream):
            for write in up.writes:
                yield name, None, write
        elif up:
            for item in up:
                for write in item.writes:
                    yield name, item.index, write


def input(name: str, optional: bool = False, writable: bool = False,  # noqa: A001
          item: Optional[int] = None) -> Optional[pathlib.Path]:
    """The folder holding the input ``name``: a dataset the run pinned (``inputs=``), or a dataset, model or
    artifact a step in ``needs=`` wrote. Downloaded once, or the copy staged beside an HPC (Slurm) job. Read-only.

    ``writable=True`` returns a private full copy of it that the step may write into (tools that write beside
    their inputs); the copy costs the input's size in disk and time, and is emptied and made again at each attempt.

    When the name is not there because a needed step did not run, this raises, naming the name and the steps;
    with ``optional=True`` it returns None instead.

    A model or an artifact of a step that has ``matrix=`` is written once for each item: ``item=2`` is the one of
    item 2 (``step.upstream(name)`` lists the items). ``item=`` is for those outputs only.
    """
    found = _find(name, optional, item)
    if found is None or not writable:
        return found
    run = _need()
    key = name if item is None else f"{name}.{item}"
    if key not in run.copies:      # a real copy: a tool may rewrite a file, so no link may reach the staged one
        run.copies[key] = _fresh(_work(WORK) / "kaos" / "inputs" / key, f"input '{name}'")
        shutil.copytree(found, run.copies[key], symlinks=True, dirs_exist_ok=True)
    return run.copies[key]


def _of_item(step: Step, name: str, item: int, matches: list):
    """The write of ``name`` by item ``item`` of a step with ``matrix=``, or a refusal that says why there is none."""
    producer = matches[0][0]
    if isinstance(item, bool) or not isinstance(item, int):
        _fail(f"item= of input('{name}') is {item!r}; it is the index of an item, a whole number from 0.")
    items = step.upstream[producer]
    if not 0 <= item < len(items):
        _fail(f"step '{producer}' has the items 0 to {len(items) - 1}; there is no item {item}. Use "
              f"step.upstream('{producer}') to see them.")
    for _, index, write in matches:
        if index == item:
            return write
    _fail(f"item {item} of step '{producer}' has status {items[item].status!r}, so it wrote no '{name}'. "
          f"Choose an item whose status is 'ok' (step.upstream('{producer}') lists them).")


def _find(name: str, optional: bool, item: Optional[int] = None) -> Optional[pathlib.Path]:
    from . import datasets
    run = _need()
    step = run.step
    read = _pinned(step).named(name)
    matches = [] if read else [m for m in _entries(step) if m[2].name == name]
    fanned = [m for m in matches if m[1] is not None]
    if item is not None and read is not None:
        _fail(f"input('{name}', item={item}): '{name}' is a dataset input of step '{step.step}', not the output of a "
              f"step with matrix=. Remove item=.")
    if item is not None and matches and not fanned:
        _fail(f"input('{name}', item={item}): '{name}' is written by step '{matches[0][0]}', which has no matrix=. "
              f"Remove item=.")
    if fanned and item is None:
        producer = fanned[0][0]
        _fail(f"input '{name}' of step '{step.step}' is written by each of the {len(step.upstream[producer])} items of "
              f"step '{producer}'. Say which: step.input('{name}', item=N), N from 0. step.upstream('{producer}') "
              "lists the items and what each handed on.")
    write = _of_item(step, name, item, fanned) if fanned else (matches[0][2] if matches else None)
    if read is None and write is None:
        absent = [s for s, up in step.upstream.items() if up is None]     # did not run, or skipped itself
        if absent and optional:
            return None
        if item is not None:
            lists = [s for s, up in step.upstream.items() if isinstance(up, list)]
            _fail(f"input('{name}', item={item}): no step in needs= wrote '{name}' for an item"
                  + (f"; the steps with matrix= are {_names(lists)}, and none of their items wrote it." if lists
                     else ", and none of the steps this one needs has matrix=. Remove item=."))
        known = [r.name for r in _pinned(step).reads] + [w.name for _, _, w in _entries(step)]
        if absent:
            _fail(f"input '{name}' of step '{step.step}' is not there, and {_names(absent)} did not run or was skipped: "
                  f"a step that did not run produced nothing. Use input('{name}', optional=True) if this step can run "
                  f"without it. What is there: {_names(known)}.")
        _fail(f"'{name}' is not an input of step '{step.step}'. Its inputs are: {_names(known)}. "
              "Add it to inputs=[...] in pipeline.py.")
    try:
        if read is not None:
            return _dataset(run, datasets, name, read)
        return _artifact(run, name, write, item)
    except NotFoundError:
        entry = read or write
        _fail(f"input '{name}': commit {entry.commit} of {entry.repo} does not exist any more.")
    except EmptyDataset as exc:
        if read is None:
            _fail(str(exc))
        _fail(f"input '{name}': {read.repo} holds no files at the version this run read ({read.ref}). Push data to "
              f"it with `kaosctl dataset push <folder> {read.repo}`, or choose another dataset for '{name}' on "
              "the run form.")


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


def _item_prefix(prefix: str, index: Optional[int]) -> str:
    """Where an output lives in its repository: ``prefix``, and below it the item's index for a step with ``matrix=``."""
    return prefix if index is None else f"{prefix}{index}/"


def _artifact(run: _Running, name: str, write: lock.Write, item: Optional[int] = None) -> pathlib.Path:
    """A model or an artifact of this run: ``<name>/<experiment>/<run>/`` of its repository (``.../<index>/`` for an
    item of a step with ``matrix=``), at the written commit."""
    from .outputs import run_prefix
    step = run.step
    staged = local.staged_dir(write.commit, repo=write.repo)
    if staged:
        return staged
    prefix = _item_prefix(run_prefix(step.experiment, step.run, name), item)
    target = local.cache_dir(write.repo, write.commit, prefix)
    if not local.marker_matches(target, write.repo, write.commit, prefix):
        local.fetch(run.client, write.repo, write.commit, [prefix], target, prefix, strip=prefix,
                    empty_message=f"input '{name}': {write.repo} holds no files under {prefix} at {write.commit}.")
    return target


def upstream(step: str, optional: bool = False):
    """The result of the earlier step ``step`` (a step named in ``needs=``): an ``Upstream`` with ``values``,
    ``reads`` and ``writes``; after a step with ``matrix=``, a list with one ``UpstreamItem`` for each item, in
    index order (``index``, ``matrix``, ``status``, ``values``, ``reads``, ``writes``, ``reason``). A failed item
    is in the list with the status "failed".

    A step that did not run (its ``when=`` was false) or ended itself with ``step.skip()`` left no result: that
    raises, naming it (and the reason it gave). With ``optional=True`` it returns None instead, for a step that can
    work without it. ``step.skipped(name)`` tells which: the reason it gave, or None.
    """
    mine = _need().step
    if step not in mine.upstream:
        _fail(f"step '{step}' is not upstream of '{mine.step}'. Add needs=['{step}'] in pipeline.py.")
    found = mine.upstream[step]
    if found is None and not optional:
        why = f"was skipped ({mine.skipped[step]})" if mine.skipped.get(step) else "did not run"
        _fail(f"step '{step}' {why}, so it left no result, and '{mine.step}' needs it. "
              f"Use upstream('{step}', optional=True) if this step can run without it.")
    return found


def skipped(step: str) -> Optional[str]:
    """The reason the earlier step ``step`` (named in ``needs=``) gave to ``step.skip()``; ``""`` when it did not
    run at all (its ``when=`` was false); None when it ran and left a result."""
    mine = _need().step
    if step not in mine.upstream:
        _fail(f"step '{step}' is not upstream of '{mine.step}'. Add needs=['{step}'] in pipeline.py.")
    return mine.skipped.get(step) if mine.upstream[step] is None else None


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


def _keep_locally(produce: Produce, folder: pathlib.Path, root: pathlib.Path,
                  item: Optional[int] = None) -> str:
    """A local run (``kaosctl step run``) uploads nothing: the output is kept in ``root/<name>`` (``root/<name>.<index>``
    for an item of a step with ``matrix=``), marked as a whole copy so that the next local step finds it as its input.
    The commit is a hash of the content."""
    from .transfer import fingerprint
    commit = fingerprint(folder)
    target = root / (produce.name if item is None else f"{produce.name}.{item}")
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(folder, target)
    local.staged_marker(target).write_text(json.dumps(
        {"repo": produce.repo, "commit": commit, "full": True, "layout": "raw", **local.stamp(target)}))
    return commit


def _seal(run: _Running, produce: Produce) -> writer.Sealed:
    from .outputs import run_prefix
    step, dataset = run.step, produce.type == "dataset"
    item = step.matrix.index if step.matrix else None
    meta = {"kaos.run": step.run, "kaos.app": step.app, "kaos.step": step.step,
            **{f"kaos.read.{r.name}": r.commit for r in lock.current().reads}}
    if step.matrix:       # the version of this item says which item it is: index and every value
        meta.update({"kaos.matrix.index": item, **{f"kaos.matrix.{axis}": str(v).lower() if isinstance(v, bool) else v
                                            for axis, v in step.matrix.values.items()}})
    if not dataset:       # what the model panel and the outputs repository have always had on a commit
        meta.update(app=step.app, experiment=step.experiment, run=step.run, kind=produce.name)
        frameworks = sys.modules.get("kaos_lib.frameworks")      # only a step that used MLflow has a run
        mlflow_run = frameworks.mlflow_run_id() if frameworks is not None else None
        if mlflow_run:                                            # the model panel links the commit to it
            meta["mlflow_run_id"] = mlflow_run
    return writer.seal(
        run.client, produce.repo, run.outputs[produce.name], name=produce.name,
        prefix="" if dataset else _item_prefix(run_prefix(step.experiment, step.run, produce.name), item),
        branch=writer.run_branch(step.run, step.step, produce.name if item is None else f"{produce.name}-{item}"),
        tag_prefix=writer.keep_prefix(step.run, step.step) if dataset else None,
        message=f"{produce.name}: {step.experiment}/{step.run}" + ("" if item is None else f"/{item}"), meta=meta)


def _save(run: _Running) -> list:
    """Save every output; returns their ledger writes. Seal all of them first, promote only then: a step that
    fails while writing moves no ``main``. A dataset is only sealed, never promoted here: its ``latest`` moves
    once, when the whole run has ended well (the platform's final task of the run, which the run form's
    ``promote-<name>`` choice controls). A model or an artifact is merged into ``main`` of the outputs repository
    under its run-unique path; nothing refers to it before this step's result does."""
    if os.environ.get(LOCAL_WORK_ENV):
        root = pathlib.Path(os.environ[local.STAGED_ENV])
        item = run.step.matrix.index if run.step.matrix else None
        return [lock.Write(p.name, p.type, p.repo, _keep_locally(p, run.outputs[p.name], root, item))
                for p in run.step.produces]
    sealed, writes, repo = [], [], ""
    try:
        for produce in run.step.produces:
            repo = produce.repo
            sealed.append((produce, _seal(run, produce)))
        for produce, s in sealed:
            repo = produce.repo
            commit = s.commit if produce.type == "dataset" else writer.promote(s)
            writer.report(s, commit)
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


def _max_item_values(items: int) -> int:
    """What the ``values`` of one item's result may cost: its share of ``MATRIX_VALUES_CAP``, never more than a
    result."""
    return min(RESULT_CAP, MATRIX_VALUES_CAP // max(items, 1))


def _exact(key: str, value) -> None:
    """A whole number of an item's result that the next step would get changed: the workflow system writes the
    results of a step's items as floats, which keep a whole number exactly up to 2 to the power 53."""
    if isinstance(value, bool):
        return
    if isinstance(value, int) and abs(value) > MATRIX_INT_LIMIT:
        _fail(f"result value '{key}' is the number {value}, which is beyond {MATRIX_INT_LIMIT} (2 to the power 53): the "
              f"step after a step with matrix= would get it changed. Write it as text, for example \"{value}\".")
    for part in (value.values() if isinstance(value, dict) else value if isinstance(value, (list, tuple)) else ()):
        _exact(key, part)


def _values_sized(values: dict, matrix: Matrix) -> None:
    """The ``values`` of an item of a step with ``matrix=`` may cost only its share of ``MATRIX_VALUES_CAP``."""
    cap, cost = _max_item_values(matrix.of), lock.cost(lock.wire(values))
    if cost > cap:
        sizes = {k: lock.cost(lock.wire(v)) for k, v in values.items()}
        big = max(sizes, key=sizes.get)
        _fail(f"the values of this result cost {cost}; the limit for one item is {cap}. The {matrix.of} items of a step "
              f"with matrix= share {MATRIX_VALUES_CAP} for their values: the smaller of {RESULT_CAP} and "
              f"{MATRIX_VALUES_CAP} divided by {matrix.of}. The largest value is '{big}' ({sizes[big]}). Hand on a few "
              "small values: log metrics to MLflow, or write the rest into an artifact with step.output().")


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
    if run.step.matrix:
        for key, value in values.items():
            _exact(key, value)
        _values_sized(values, run.step.matrix)
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


def skip(reason: str) -> None:
    """End the step as skipped: it hands on no result values and saves nothing, and the process ends with exit code
    0 (it is not a failure). ``reason`` (text, at most 300 characters) is what the run shows and what the steps that
    need this one are told. Steps that need it still run; they find it with ``step.skipped(name)`` or
    ``step.upstream(name, optional=True)``. A dataset this step produces gets no new version, so it is not promoted."""
    run = _need()
    if run.done:
        _fail("step.result() or step.skip() was already called.")
    if not isinstance(reason, str) or not reason.strip():
        _fail("step.skip() needs the reason, as text, for example step.skip('the verdict is not good enough to publish').")
    if len(reason) > SKIP_REASON_MAX:
        _fail(f"the reason of step.skip() has {len(reason)} characters; the limit is {SKIP_REASON_MAX}. Say it shorter.")
    text = lock.wire({"version": VERSION, "status": "skipped", "reason": reason})
    target = _work(RESULT_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_text(text, encoding="ascii")
    os.replace(partial, target)
    run.done = True
    print(f"step '{run.step.step}' skipped: {reason}", flush=True)
    sys.exit(0)


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

    def hook(kind, exc, trace):
        run.raised = True
        if isinstance(exc, KaosLibError):    # its message says what happened and what to do: one line, no traceback
            print(f"ERROR: {exc}{_where(trace)}", file=sys.stderr, flush=True)
        else:
            real_hook(kind, exc, trace)

    def register(func, *args, **kwargs):
        run.late.append(func)
        return real_register(func, *args, **kwargs)

    run.undo = (real_exit, real_hook, real_register)
    sys.exit, sys.excepthook, atexit.register = exit_, hook, register
    real_register(_at_exit, run)


def _where(trace) -> str:
    """The line of the step's own code the failure came from: the last frame outside kaos-lib, or ''."""
    own = os.path.dirname(os.path.abspath(__file__))
    for frame in reversed(traceback.extract_tb(trace)):
        if not os.path.abspath(frame.filename).startswith(own):
            return f"\n  at {frame.filename}:{frame.lineno}, in {frame.name}"
    return ""


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
