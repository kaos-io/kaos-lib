"""The durable record of a run: what each of its steps handed on, kept so that a later run can start from a step.

A step that ends (``step.result()`` or ``step.skip()``) saves exactly the result it hands on as
``kaos-runs/<run>/<step>.json`` on ``main`` of the app's ``outputs-<app>`` repository. The platform saves the run's
plan beside them as ``kaos-runs/<run>/plan.json`` when the run starts. A later run that starts from a step reads these
files instead of running the earlier steps again (docs: Re-running).

Each step writes on its own branch, ``run-<run>-<step>-record``, created from ``main`` and merged into it: the same
way a model or an artifact is saved, and no step touches another step's file. Saving is best effort for the step
(``step.save``): the caller of ``write`` decides what a failure means.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
from typing import Optional

from . import writer
from .errors import DatasetError, NotFoundError
from .outputs import MAIN, _segment, outputs_repo
from .transfer import upload

DIR = "kaos-runs"
PLAN = "plan"           # the platform's file of the run: kaos-runs/<run>/plan.json
BRANCH_KIND = "record"


def path(run: str, name: str) -> str:
    """Where the record ``name`` (a step's name, or ``plan``) of ``run`` lives in ``outputs-<app>``."""
    return f"{DIR}/{_segment('run', run)}/{_segment('name', name)}.json"


def branch(run: str, name: str) -> str:
    """The branch the record ``name`` of ``run`` is written on."""
    return writer.run_branch(run, name, BRANCH_KIND)


def write(client, app: str, run: str, name: str, text: str) -> str:
    """Save ``text`` as the record ``name`` of ``run``; returns the commit on ``main``.

    One commit on ``main``. A retry starts the branch again, so it saves the same file once. Raises what the
    lake raises (``KaosLibError`` or a connection error); a missing ``outputs-<app>`` is a ``DatasetError``.
    """
    repo, target, on = outputs_repo(app), path(run, name), branch(run, name)
    try:
        client.branch_commit(repo, MAIN)
    except NotFoundError as exc:
        raise DatasetError(f"{repo} does not exist: the platform creates it for each ML app.") from exc
    message = f"record: {run}/{name}"
    meta = {"kaos.run": run, "kaos.app": app, "kaos.record": name}
    try:
        client.delete_branch(repo, on)            # an earlier attempt's
        client.create_branch(repo, on, MAIN)
        with tempfile.TemporaryDirectory() as tmp:
            local = pathlib.Path(tmp) / f"{name}.json"
            local.write_text(text, encoding="utf-8")
            upload(client, repo, on, target, local)
        client.commit(repo, on, message, meta, tolerate_empty=True)
        return client.merge(repo, on, MAIN, message, meta, tolerate_empty=True)
    finally:
        try:
            client.delete_branch(repo, on)
        except Exception:  # noqa: BLE001 - a branch that stays is harmless: the next attempt starts it again
            pass


def read(client, app: str, run: str, name: str) -> Optional[dict]:
    """The record ``name`` of ``run`` as it is on ``main`` now, or None when there is none."""
    repo = outputs_repo(app)
    with tempfile.TemporaryDirectory() as tmp:
        local = pathlib.Path(tmp) / f"{name}.json"
        try:
            client.download_object(repo, MAIN, path(run, name), local)
        except NotFoundError:
            return None
        return json.loads(local.read_text(encoding="utf-8"))
