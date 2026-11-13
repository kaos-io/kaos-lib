"""Test a step in your own test suite, in the same process, with no cluster and no login.

``running`` prepares what the platform hands a step (the step context, the folders of its inputs, the results of
the steps before it), lets you call the step's ``main()``, and gives back what it handed on::

    from kaos_lib import testing
    from app import entry

    def test_the_step_counts_the_files(tmp_path):
        data = tmp_path / "data"; data.mkdir(); (data / "a.txt").write_text("a")
        with testing.running(tmp_path, kind="evaluate", inputs={"dataset": data}) as run:
            entry.main()
        assert run.result["values"] == {"files": 1}

Nothing is uploaded: an output stays on disk (``run.output(name)``) and the result is read from the file
``step.result()`` writes. The step's environment is put back when the block ends. ``kaosctl step run`` builds the
same context for a whole pipeline of steps on your machine.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import shutil
from typing import Optional

from . import datasets, lock, step
from .layouts import local
from .transfer import fingerprint

ABSENT = {"version": 1, "status": "absent"}     # what a step gets for a needed step that did not run
ITEM_STATUSES = ("ok", "failed", "skipped")


def _matrix_entry(staged: pathlib.Path, app: str, up: str, items) -> dict:
    """What a step gets for a needed step that has ``matrix=``: one entry for each item of ``items``, a list of
    ``{"matrix": {...}, "values": {...}, "writes": {name: folder}, "reads": {...}, "status": ..., "reason": ...}``
    (everything optional; the status is "ok" unless given; the index is the position in the list)."""
    out = []
    for index, item in enumerate(items):
        unknown = set(item) - {"matrix", "values", "writes", "reads", "status", "reason"}
        status = item.get("status", "ok")
        if unknown or status not in ITEM_STATUSES:
            raise ValueError(f"upstream_matrix {up!r} item {index}: use matrix, values, writes, reads, status "
                             f"({' | '.join(ITEM_STATUSES)}) and reason, got {item}")
        entry = {"index": index, "values": dict(item.get("matrix", {})), "status": status}
        if status == "skipped":
            entry["reason"] = item.get("reason") or "skipped"
        elif status == "ok":
            entry["result"] = {
                "version": 1, "status": "ok", "values": item.get("values", {}),
                "reads": [_upstream_read(n, spec) for n, spec in (item.get("reads") or {}).items()],
                "writes": [_upstream_write(staged, app, n, spec, into=f"{n}.{up}.{index}")
                           for n, spec in (item.get("writes") or {}).items()]}
        out.append(entry)
    return {"version": 1, "status": "matrix", "items": out}


def mark(folder: pathlib.Path, repo: str, ref: str = "local", layout: str = "raw") -> dict:
    """Record that ``folder`` is a whole staged copy of ``repo`` and return the ledger read that names it."""
    commit = fingerprint(folder)
    local.staged_marker(folder).write_text(json.dumps({"repo": repo, "commit": commit, "full": True, "layout": layout,
                                                         **local.stamp(folder)}),
                                           encoding="utf-8")
    return {"name": folder.name, "repo": repo, "owner": None, "ref": ref, "commit": commit}


def stage_input(staged: pathlib.Path, name: str, folder, repo: Optional[str] = None, ref: str = "local") -> dict:
    """Copy ``folder`` to ``staged/<name>`` as the input ``name`` and return its ledger read."""
    target = staged / name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(folder, target)
    return mark(target, repo or datasets.dataset_repo(name), ref)


def local_context(*, run: str, app: str, step_name: str, kind: str, experiment: str, params: dict, reads: list,
                  produces: list, upstream: dict, matrix: Optional[dict] = None) -> dict:
    """The step context of a run on this machine, in the contract's field order. ``produces`` is a list of
    ``(type, name)``; ``matrix`` is ``{"index", "of", "values"}`` for an item of a step with ``matrix=``."""
    context = {"version": 1, "run": run, "app": app, "project": "local", "step": step_name, "kind": kind,
               "experiment": experiment, "params": params, "ledger": {"version": 2, "reads": reads, "writes": []},
               "produces": [{"name": name, "type": kind_,
                             "repo": datasets.produced_repo(app, name) if kind_ == "dataset" else f"outputs-{app}"}
                            for kind_, name in produces],
               "upstream": upstream}
    if matrix is not None:
        from .lint.matrix import value_problem
        for axis, value in matrix["values"].items():
            problem = value_problem(f"matrix value {value!r} of {axis!r}", value)
            if problem:
                raise ValueError(problem)
        context["matrix"] = {"index": matrix["index"], "of": matrix["of"], "values": dict(matrix["values"])}
    return context


WRITE_TYPES = ("model", "artifact", "dataset")


def _upstream_write(staged: pathlib.Path, app: str, name: str, spec, into: Optional[str] = None) -> dict:
    """The ledger write of an upstream step. ``spec`` is a folder, or ``{"folder": ..., "type": ..., "commit": ...}``
    (each part optional but a folder or a commit; the type defaults to "artifact"). ``into`` is the name of the
    staged folder when it is not ``name``."""
    spec = dict(spec) if isinstance(spec, dict) else {"folder": spec}
    unknown = set(spec) - {"folder", "type", "commit"}
    kind_ = spec.get("type", "artifact")
    if unknown or kind_ not in WRITE_TYPES:
        raise ValueError(f"upstream write {name!r}: use folder, type ({' | '.join(WRITE_TYPES)}) and commit, got {spec}")
    if spec.get("folder") is None and not spec.get("commit"):
        raise ValueError(f"upstream write {name!r} needs a folder or a commit")
    repo = datasets.produced_repo(app, name) if kind_ == "dataset" else f"outputs-{app}"
    commit = stage_input(staged, into or name, spec["folder"], repo=repo)["commit"] \
        if spec.get("folder") is not None else None
    return {"name": name, "type": kind_, "repo": repo, "commit": spec.get("commit") or commit}


def _upstream_read(name: str, spec) -> dict:
    """The ledger read of an upstream step. ``spec`` is ``"<repository>@<version>"`` or
    ``{"repo": ..., "ref": ..., "commit": ...}``; without a commit one is computed from the repository and version."""
    spec = dict(spec) if isinstance(spec, dict) else dict(zip(("repo", "ref"), str(spec).partition("@")[::2]))
    if not spec.get("repo") or not spec.get("ref") or set(spec) - {"repo", "ref", "commit"}:
        raise ValueError(f"upstream read {name!r}: write it as repository@version, e.g. 'dataset-raw@v2', "
                         f"or as {{repo, ref, commit}}; got {spec}")
    commit = spec.get("commit") or hashlib.sha256(f"{spec['repo']}@{spec['ref']}".encode()).hexdigest()
    return {"name": name, "repo": spec["repo"], "owner": None, "ref": spec["ref"], "commit": commit}


class Run:
    """What a step did inside ``running``."""

    def __init__(self, work: pathlib.Path, staged: pathlib.Path):
        self.work, self.staged = work, staged

    def output(self, name: str, item: Optional[int] = None) -> pathlib.Path:
        """The folder holding what the step saved as the output ``name`` (after ``step.result()``); for an item of
        a step with ``matrix=``, the folder of that item (``matrix_index`` of ``running``)."""
        return self.staged / (name if item is None else f"{name}.{item}")

    @property
    def result(self) -> Optional[dict]:
        """The result the step handed on, or None when it wrote none."""
        file = self.work / "output" / "kaos-result.json"
        return json.loads(file.read_text()) if file.is_file() else None


@contextlib.contextmanager
def running(tmp_path, *, kind: str = "train", name: str = "step", app: str = "app", experiment: str = "test",
            params: Optional[dict] = None, inputs: Optional[dict] = None, upstream: Optional[dict] = None,
            upstream_writes: Optional[dict] = None, upstream_reads: Optional[dict] = None,
            upstream_skipped: Optional[dict] = None, upstream_matrix: Optional[dict] = None,
            matrix: Optional[dict] = None, matrix_index: int = 0, matrix_of: Optional[int] = None, produces=()):
    """Prepare a step's world in ``tmp_path`` for the length of the block.

    ``params`` is what ``step.start().params`` holds; ``inputs`` maps an input's name to a folder of files;
    ``upstream`` maps a step's name to the values it handed on, or to None for a step that did not run;
    ``upstream_writes`` maps a step's name to what it wrote, ``{"train": {"checkpoints": <folder>}}``: the step
    then reads ``step.input("checkpoints")`` from that folder and ``step.upstream("train").writes`` names it.
    A write may be a mapping instead of a folder, ``{"folder": folder, "type": "dataset", "commit": "..."}``: the
    type is "model", "artifact" (the default) or "dataset" (its repository is then ``dataset-<app>-<name>``), the
    commit is computed from the folder unless you give it, and a commit alone (no folder) is enough;
    ``upstream_reads`` maps a step's name to what that step read, ``{"prepare-data": {"dataset": "dataset-raw@v2"}}``:
    ``step.upstream("prepare-data").reads`` then names that repository, version and a commit (computed from the two
    unless you write the read as ``{"repo": ..., "ref": ..., "commit": ...}``);
    ``upstream_skipped`` maps a step's name to the reason that step gave to ``step.skip()``;
    ``upstream_matrix`` maps the name of a step that has ``matrix=`` to the list of its items, in index order, each
    ``{"matrix": {"lr": 0.01}, "values": {...}, "writes": {...}, "reads": {...}, "status": "ok" | "failed" |
    "skipped", "reason": "..."}`` with every part optional: ``step.upstream("train")`` is then that list;
    ``matrix`` is the values of this step's own item, ``{"lr": 0.01}``: the step reads them as ``params["lr"]``
    (``matrix_index``, and ``matrix_of`` the number of items, say which item it is: its output is then
    ``run.output(name, item=matrix_index)``);
    ``produces`` is a list of ``("model" | "artifact" | "dataset", name)``.
    """
    tmp_path = pathlib.Path(tmp_path)
    work, staged = tmp_path / "work", tmp_path / "staged"
    staged.mkdir(parents=True, exist_ok=True)
    reads = [stage_input(staged, input_name, folder) for input_name, folder in (inputs or {}).items()]
    written = {up: [_upstream_write(staged, app, n, spec) for n, spec in files.items()]
               for up, files in (upstream_writes or {}).items()}
    read = {up: [_upstream_read(n, spec) for n, spec in found.items()] for up, found in (upstream_reads or {}).items()}
    results = {up: ABSENT if values is None else
               {"version": 1, "status": "ok", "values": values, "reads": read.get(up, []), "writes": written.get(up, [])}
               for up, values in {**{u: {} for u in (*written, *read)}, **(upstream or {})}.items()}
    results.update({up: {"version": 1, "status": "skipped", "reason": reason}
                    for up, reason in (upstream_skipped or {}).items()})
    results.update({up: _matrix_entry(staged, app, up, items) for up, items in (upstream_matrix or {}).items()})
    context = local_context(run="test-run", app=app, step_name=name, kind=kind, experiment=experiment,
                            params=params or {}, reads=reads, produces=list(produces), upstream=results,
                            matrix=None if matrix is None else {"index": matrix_index, "of": matrix_of or matrix_index + 1,
                                                  "values": matrix})
    env = {step.ENV: lock.wire(context), step.LOCAL_WORK_ENV: str(work), local.STAGED_ENV: str(staged)}
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    step.stop()
    lock.reset()
    try:
        yield Run(work, staged)
    finally:
        step.stop()
        lock.reset()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
