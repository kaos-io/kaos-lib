"""Data lock (PRD kaos#1147 D-13, F-18): the exact commit of every dataset a run reads, kept in MLflow, replayable.

Every ``datasets.resolve`` (and so every ``materialize``) records ``(owner, repo, ref) -> commit`` in the process's
lock, ``current()``. Reads that bypass kaos-lib (an S3-gateway stream, say) are added with ``record``. At the end
of a step, ``write()`` puts the lock on the MLflow run:

- tags ``kaos_lib.data.<repo>.commit`` (the commits read, comma-separated in read order) and, for a dataset another
  project shares, ``kaos_lib.data.<repo>.owner``;
- the artifact ``data.lock.json``: ``{"version": 1, "reads": [{"repo", "owner", "ref", "commit"}, ...]}``, merged
  with the one already on the run, so several steps logging to one run add up.

``load(run_id)`` reads a lock back. ``DataLock.replay(lock)`` makes later resolves of the locked repositories return
the locked commits; ``kaos-cli run --lock <run-id> -- <command>`` hands the lock to a child process as
``$KAOS_LIB_LOCK`` (the JSON), which this module honours the same way.

Replay matches a resolve on (owner, repo, ref) first, then on (owner, repo) when the lock holds a single commit for
that repository. A commit pinned by the caller (``ref.commit`` or ``commit=``) is used as given and recorded.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import Iterable, Optional, Union

from .errors import LockError

VERSION = 1
ARTIFACT = "data.lock.json"
TAG_PREFIX = "kaos_lib.data."
ENV = "KAOS_LIB_LOCK"
RUN_ID_ENV = "MLFLOW_RUN_ID"


@dataclass(frozen=True)
class Read:
    """One read: ``repo`` at ``ref`` was ``commit``; ``owner`` is the sharing project, None for the own one."""
    repo: str
    ref: str
    commit: str
    owner: Optional[str] = None

    def as_dict(self) -> dict:
        return {"repo": self.repo, "owner": self.owner, "ref": self.ref, "commit": self.commit}


class DataLock:
    """The reads of one run, in the order they happened (duplicates dropped)."""

    def __init__(self, reads: Iterable[Read] = ()):
        self._reads: list = []
        self._guard = threading.Lock()
        for read in reads:
            self._add(read)

    def _add(self, read: Read) -> Read:
        with self._guard:
            if read not in self._reads:
                self._reads.append(read)
        return read

    @property
    def reads(self) -> list:
        with self._guard:
            return list(self._reads)

    def record(self, repo: str, ref: str, commit: str, owner: Optional[str] = None) -> Read:
        """Add a read (a no-op when it is already there)."""
        return self._add(Read(repo, ref, commit, owner or None))

    def pinned(self, repo: str, ref: str, owner: Optional[str] = None) -> Optional[str]:
        """The locked commit for this read, or None when the lock does not cover it."""
        owner = owner or None
        same_repo = [r for r in self.reads if r.repo == repo and r.owner == owner]
        exact = [r.commit for r in same_repo if r.ref == ref]
        if exact:
            return exact[0]
        commits = {r.commit for r in same_repo}
        return commits.pop() if len(commits) == 1 else None

    def to_dict(self) -> dict:
        return {"version": VERSION, "reads": [r.as_dict() for r in self.reads]}

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def parse(cls, data: Union[str, bytes, dict], source: str = "the data lock") -> "DataLock":
        """A lock from its JSON (text or already parsed); LockError saying what is wrong."""
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except ValueError as exc:
                raise LockError(f"{source} is not JSON ({exc}).") from None
        if not isinstance(data, dict):
            raise LockError(f'{source} must be a JSON object {{"version": {VERSION}, "reads": [...]}}.')
        if data.get("version") != VERSION:
            raise LockError(f"{source} has version {data.get('version')!r}; this kaos-lib reads version {VERSION} "
                            "(a newer kaos-lib may have written it: upgrade).")
        reads = data.get("reads")
        if not isinstance(reads, list):
            raise LockError(f"{source} has no reads list.")
        out = []
        for i, entry in enumerate(reads):
            if not isinstance(entry, dict):
                raise LockError(f"{source}: reads[{i}] is not an object.")
            bad = [k for k in ("repo", "ref", "commit") if not isinstance(entry.get(k), str) or not entry[k]]
            if bad:
                raise LockError(f"{source}: reads[{i}] needs a non-empty string {', '.join(bad)}.")
            if entry.get("owner") is not None and not isinstance(entry["owner"], str):
                raise LockError(f"{source}: reads[{i}].owner must be a project name or null.")
            out.append(Read(entry["repo"], entry["ref"], entry["commit"], entry.get("owner") or None))
        return cls(out)

    def tags(self) -> dict:
        """The MLflow tags of this lock: ``kaos_lib.data.<repo>.commit`` and, for shared reads, ``.owner``."""
        commits: dict = {}
        owners: dict = {}
        for r in self.reads:
            commits.setdefault(r.repo, [])
            if r.commit not in commits[r.repo]:
                commits[r.repo].append(r.commit)
            if r.owner and r.owner not in owners.setdefault(r.repo, []):
                owners[r.repo].append(r.owner)
        tags = {f"{TAG_PREFIX}{repo}.commit": ",".join(c) for repo, c in commits.items()}
        tags.update({f"{TAG_PREFIX}{repo}.owner": ",".join(o) for repo, o in owners.items() if o})
        return tags

    def write(self, run_id: Optional[str] = None, client=None) -> "DataLock":
        """Merge this lock into the MLflow run's ``data.lock.json`` and set its tags; returns the merged lock.

        The run is ``run_id``, else the active MLflow run, else ``$MLFLOW_RUN_ID``.
        """
        run = _run_id(run_id)
        c = client or _client()
        existing = _download(c, run)
        merged = DataLock((existing.reads if existing else []) + self.reads)
        try:
            for key, value in merged.tags().items():
                c.set_tag(run, key, value)
            c.log_text(run, merged.to_json(indent=2), ARTIFACT)
        except Exception as exc:  # noqa: BLE001 - any MLflow failure becomes one clear message
            raise LockError(f"cannot write the data lock to MLflow run {run} ({exc.__class__.__name__}: {exc}).") from None
        return merged

    @staticmethod
    def replay(lock: Union["DataLock", str, bytes, dict, None]) -> Optional["DataLock"]:
        """From now on, resolves of the locked repositories return the locked commits (None stops replaying)."""
        global _replay
        _replay = lock if isinstance(lock, DataLock) or lock is None else DataLock.parse(lock)
        return _replay


_current = DataLock()
_replay: Optional[DataLock] = None
_env_lock: tuple = (None, None)   # (the $KAOS_LIB_LOCK text, its parsed lock)


def current() -> DataLock:
    """The lock recording this process's reads."""
    return _current


def record(repo: str, ref: str, commit: str, owner: Optional[str] = None) -> Read:
    """Record a read that did not go through ``datasets.resolve`` (e.g. a stream from the S3 gateway)."""
    return _current.record(repo, ref, commit, owner)


def write(run_id: Optional[str] = None, client=None) -> DataLock:
    """Write this process's reads to the MLflow run (see ``DataLock.write``)."""
    return _current.write(run_id, client)


def load(run_id: str, client=None) -> DataLock:
    """The data lock of MLflow run ``run_id``; LockError when it has none."""
    lock = _download(client or _client(), run_id)
    if lock is None:
        raise LockError(f"MLflow run {run_id} has no {ARTIFACT}: the run did not record its data reads "
                        "(kaos_lib.lock.write() was not called).")
    return lock


def replaying() -> Optional[DataLock]:
    """The lock being replayed: ``DataLock.replay``'s, else ``$KAOS_LIB_LOCK``'s, else None."""
    global _env_lock
    if _replay is not None:
        return _replay
    raw = os.environ.get(ENV)
    if not raw:
        return None
    if _env_lock[0] != raw:
        _env_lock = (raw, DataLock.parse(raw, f"${ENV}"))
    return _env_lock[1]


def pinned(repo: str, ref: str, owner: Optional[str] = None) -> Optional[str]:
    """The replayed commit for a read, or None when nothing is replayed or the lock does not cover it."""
    lock = replaying()
    return lock.pinned(repo, ref, owner) if lock else None


def reset() -> None:
    """Forget the recorded reads and stop replaying (tests; long-lived processes between runs)."""
    global _current, _replay, _env_lock
    _current, _replay, _env_lock = DataLock(), None, (None, None)


def _run_id(run_id: Optional[str]) -> str:
    if run_id:
        return run_id
    mlflow = sys.modules.get("mlflow")
    active = mlflow.active_run() if mlflow is not None and hasattr(mlflow, "active_run") else None
    if active is not None:
        return active.info.run_id
    if os.environ.get(RUN_ID_ENV):
        return os.environ[RUN_ID_ENV]
    raise LockError(f"no MLflow run to write the data lock to: pass run_id=, start a run, or set ${RUN_ID_ENV}.")


def _client():
    from .mlflow import _import_mlflow
    _import_mlflow()
    from mlflow.tracking import MlflowClient
    return MlflowClient()


def _download(client, run_id: str) -> Optional[DataLock]:
    """The run's lock, or None when it has no ``data.lock.json``."""
    try:
        names = {f.path for f in client.list_artifacts(run_id)}
        if ARTIFACT not in names:
            return None
        with tempfile.TemporaryDirectory() as tmp:
            text = pathlib.Path(client.download_artifacts(run_id, ARTIFACT, tmp)).read_text()
    except Exception as exc:  # noqa: BLE001 - any MLflow failure becomes one clear message
        raise LockError(f"cannot read the data lock of MLflow run {run_id} ({exc.__class__.__name__}: {exc}).") from None
    return DataLock.parse(text, f"{ARTIFACT} of MLflow run {run_id}")
