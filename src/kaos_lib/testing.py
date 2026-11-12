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
import json
import os
import pathlib
import shutil
from typing import Optional

from . import datasets, lock, step
from .layouts import local
from .transfer import fingerprint

ABSENT = {"version": 1, "status": "absent"}     # what a step gets for a needed step that did not run


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
                  produces: list, upstream: dict) -> dict:
    """The step context of a run on this machine, in the contract's field order. ``produces`` is a list of
    ``(type, name)``."""
    return {"version": 1, "run": run, "app": app, "project": "local", "step": step_name, "kind": kind,
            "experiment": experiment, "params": params, "ledger": {"version": 2, "reads": reads, "writes": []},
            "produces": [{"name": name, "type": kind_,
                          "repo": datasets.produced_repo(app, name) if kind_ == "dataset" else f"outputs-{app}"}
                         for kind_, name in produces],
            "upstream": upstream}


class Run:
    """What a step did inside ``running``."""

    def __init__(self, work: pathlib.Path, staged: pathlib.Path):
        self.work, self.staged = work, staged

    def output(self, name: str) -> pathlib.Path:
        """The folder holding what the step saved as the output ``name`` (after ``step.result()``)."""
        return self.staged / name

    @property
    def result(self) -> Optional[dict]:
        """The result the step handed on, or None when it wrote none."""
        file = self.work / "output" / "kaos-result.json"
        return json.loads(file.read_text()) if file.is_file() else None


@contextlib.contextmanager
def running(tmp_path, *, kind: str = "train", name: str = "step", app: str = "app", experiment: str = "test",
            params: Optional[dict] = None, inputs: Optional[dict] = None, upstream: Optional[dict] = None,
            upstream_writes: Optional[dict] = None, produces=()):
    """Prepare a step's world in ``tmp_path`` for the length of the block.

    ``params`` is what ``step.start().params`` holds; ``inputs`` maps an input's name to a folder of files;
    ``upstream`` maps a step's name to the values it handed on, or to None for a step that did not run;
    ``upstream_writes`` maps a step's name to what it wrote, ``{"train": {"checkpoints": <folder>}}``: the step
    then reads ``step.input("checkpoints")`` from that folder and ``step.upstream("train").writes`` names it;
    ``produces`` is a list of ``("model" | "artifact" | "dataset", name)``.
    """
    tmp_path = pathlib.Path(tmp_path)
    work, staged = tmp_path / "work", tmp_path / "staged"
    staged.mkdir(parents=True, exist_ok=True)
    reads = [stage_input(staged, input_name, folder) for input_name, folder in (inputs or {}).items()]
    written = {up: [{"name": n, "type": "artifact", "repo": f"outputs-{app}",
                     "commit": stage_input(staged, n, f, repo=f"outputs-{app}")["commit"]} for n, f in files.items()]
               for up, files in (upstream_writes or {}).items()}
    results = {up: ABSENT if values is None else
               {"version": 1, "status": "ok", "values": values, "reads": [], "writes": written.get(up, [])}
               for up, values in {**{u: {} for u in written}, **(upstream or {})}.items()}
    context = local_context(run="test-run", app=app, step_name=name, kind=kind, experiment=experiment,
                            params=params or {}, reads=reads, produces=list(produces), upstream=results)
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
