"""The ledger: the exact commit of every dataset a run read and of everything it wrote, replayable.

It is the data lock at version 2. Every ``datasets.resolve`` (and so every ``materialize`` and ``step.input``)
records a read in the process's ledger, ``current()``; ``step.result`` records what the step wrote. The same
shape travels in three places: the step context (what the platform pinned for the step), each step's result
(what the step read and wrote) and the run's ledger (the union of the results)::

    {"version": 2,
     "reads":  [{"name", "repo", "owner", "ref", "commit"}, ...],
     "writes": [{"name", "type", "repo", "commit"}, ...]}

On an MLflow run a step leaves its own part as the artifact ``ledger/<step>.json`` and the tags
``kaos_lib.data.<repo>.commit`` (``write_step``). ``load(run_id)`` reads a run's ledger back: the union of its
``ledger/*.json``, or the ``data.lock.json`` of a run made before version 2 (read only; nothing writes version 1).

``DataLock.replay(lock)`` makes later resolves of the locked repositories return the locked commits;
``kaosctl run --lock <run-id> -- <command>`` hands the ledger to a child process as ``$KAOS_LIB_LOCK``. Inside a
pipeline step (``step.start()``) the pinned commits come from the step context and a dataset the run did not
pin is refused (``strict``).

Replay matches a resolve on (owner, repo, ref) first, then on (owner, repo) when the lock holds a single commit for
that repository. A commit pinned by the caller (``ref.commit`` or ``commit=``) is used as given and recorded.

``wire(value)`` is the form in which a context or a result crosses a process boundary: JSON with no whitespace,
ASCII only, and ``{`` and ``}`` inside strings written as ``\\u007b`` and ``\\u007d``. ``cost(text)`` is what such a
text counts against a size cap.
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

VERSION = 2
ARTIFACT_DIR = "ledger"            # ledger/<step>.json: one file per step, written by that step only
OLD_ARTIFACT = "data.lock.json"    # version 1, on runs made before the ledger: read only
TAG_PREFIX = "kaos_lib.data."
ENV = "KAOS_LIB_LOCK"
RUN_ID_ENV = "MLFLOW_RUN_ID"
WRITE_TYPES = ("model", "artifact", "dataset")
DATASET_PREFIX = "dataset-"


def wire(value) -> str:
    """The wire form of a JSON value (see the module text); TypeError for what JSON cannot hold."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=True).replace("{", "\\u007b").replace("}", "\\u007d")
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(value, allow_nan=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(wire(v) for v in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"object keys must be strings, got {key!r}")
        return "{" + ",".join(wire(k) + ":" + wire(v) for k, v in value.items()) + "}"
    raise TypeError(f"not a JSON value: {value!r}")


def cost(wire_text: str) -> int:
    """What a value in wire form costs against its cap: its length as a JSON string, where each quote and each
    backslash counts twice. That is the room it takes where the platform carries it."""
    return len(wire_text) + wire_text.count('"') + wire_text.count("\\")


def _default_name(repo: str) -> str:
    return repo[len(DATASET_PREFIX):] if repo.startswith(DATASET_PREFIX) and len(repo) > len(DATASET_PREFIX) else repo


@dataclass(frozen=True)
class Read:
    """One read: ``repo`` at ``ref`` was ``commit``; ``owner`` is the sharing project, None for the own one.

    ``name`` is the input's name in the pipeline (default: the repository's name without ``dataset-``). ``line``
    is reserved for a dataset stored as a branch of its source; it is kept when present and never set here.
    """
    repo: str
    ref: str
    commit: str
    owner: Optional[str] = None
    name: Optional[str] = None
    line: Optional[str] = None

    def __post_init__(self):
        if not self.name:
            object.__setattr__(self, "name", _default_name(self.repo))

    def as_dict(self) -> dict:
        out = {"name": self.name, "repo": self.repo, "owner": self.owner,
               "ref": self.ref, "commit": self.commit}
        if self.line:
            out["line"] = self.line
        return out


@dataclass(frozen=True)
class Write:
    """One write: the model, artifact or dataset ``name`` is held by ``commit`` of ``repo``."""
    name: str
    type: str
    repo: str
    commit: str
    line: Optional[str] = None

    def as_dict(self) -> dict:
        out = {"name": self.name, "type": self.type, "repo": self.repo, "commit": self.commit}
        if self.line:
            out["line"] = self.line
        return out


def _text(entry: dict, keys: tuple, where: str) -> None:
    bad = [k for k in keys if not isinstance(entry.get(k), str) or not entry[k]]
    if bad:
        raise LockError(f"{where} needs a non-empty string {', '.join(bad)}.")
    if entry.get("line") is not None and not isinstance(entry["line"], str):
        raise LockError(f"{where}.line must be text.")


def parse_read(entry, where: str, named: bool = True) -> Read:
    """A read from its JSON object; ``named`` False accepts a version 1 entry, which has no name."""
    if not isinstance(entry, dict):
        raise LockError(f"{where} is not an object.")
    _text(entry, ("name", "repo", "ref", "commit") if named else ("repo", "ref", "commit"), where)
    if entry.get("owner") is not None and not isinstance(entry["owner"], str):
        raise LockError(f"{where}.owner must be a project name or null.")
    return Read(entry["repo"], entry["ref"], entry["commit"], entry.get("owner") or None,
                entry.get("name") or None, entry.get("line") or None)


def parse_write(entry, where: str) -> Write:
    if not isinstance(entry, dict):
        raise LockError(f"{where} is not an object.")
    _text(entry, ("name", "type", "repo", "commit"), where)
    if entry["type"] not in WRITE_TYPES:
        raise LockError(f"{where}.type is {entry['type']!r}; it is one of {', '.join(WRITE_TYPES)}.")
    return Write(entry["name"], entry["type"], entry["repo"], entry["commit"], entry.get("line") or None)


class DataLock:
    """The reads and writes of one run or one step, in the order they happened (duplicates dropped)."""

    def __init__(self, reads: Iterable[Read] = (), writes: Iterable[Write] = ()):
        self._reads: list = []
        self._writes: list = []
        self._guard = threading.Lock()
        for read in reads:
            self._add(read)
        for write in writes:
            self.wrote(write)

    def _add(self, read: Read) -> Read:
        with self._guard:
            if read not in self._reads:
                self._reads.append(read)
        return read

    @property
    def reads(self) -> list:
        with self._guard:
            return list(self._reads)

    @property
    def writes(self) -> list:
        with self._guard:
            return list(self._writes)

    def record(self, repo: str, ref: str, commit: str, owner: Optional[str] = None,
               name: Optional[str] = None) -> Read:
        """Add a read (a no-op when it is already there)."""
        return self._add(Read(repo, ref, commit, owner or None, name or None))

    def wrote(self, write: Write) -> Write:
        """Add a write (a no-op when it is already there)."""
        with self._guard:
            if write not in self._writes:
                self._writes.append(write)
        return write

    def pinned(self, repo: str, ref: str, owner: Optional[str] = None) -> Optional[str]:
        """The locked commit for this read, or None when the lock does not cover it."""
        owner = owner or None
        same_repo = [r for r in self.reads if r.repo == repo and r.owner == owner]
        exact = [r.commit for r in same_repo if r.ref == ref]
        if exact:
            return exact[0]
        commits = {r.commit for r in same_repo}
        return commits.pop() if len(commits) == 1 else None

    def named(self, name: str) -> Optional[Read]:
        """The read called ``name``, or None."""
        return next((r for r in self.reads if r.name == name), None)

    def to_dict(self) -> dict:
        return {"version": VERSION, "reads": [r.as_dict() for r in self.reads],
                "writes": [w.as_dict() for w in self.writes]}

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def parse(cls, data: Union[str, bytes, dict], source: str = "the ledger") -> "DataLock":
        """A ledger from its JSON (text or already parsed); LockError saying what is wrong.

        Version 2 is the ledger. Version 1 (reads without names, no writes) is accepted so that a run made before
        the ledger can be replayed; it is never written.
        """
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except ValueError as exc:
                raise LockError(f"{source} is not JSON ({exc}).") from None
        if not isinstance(data, dict):
            raise LockError(f'{source} must be a JSON object {{"version": {VERSION}, "reads": [...], "writes": [...]}}.')
        version = data.get("version")
        if version not in (1, VERSION) or isinstance(version, bool):
            raise LockError(f"{source} has version {version!r}; this kaos-lib reads version {VERSION} "
                            "(a newer kaos-lib may have written it: upgrade).")
        reads = data.get("reads")
        if not isinstance(reads, list):
            raise LockError(f"{source} has no reads list.")
        writes = data.get("writes", []) if version == VERSION else []
        if not isinstance(writes, list):
            raise LockError(f"{source}: writes is not a list.")
        return cls([parse_read(e, f"{source}: reads[{i}]", named=version == VERSION) for i, e in enumerate(reads)],
                   [parse_write(e, f"{source}: writes[{i}]") for i, e in enumerate(writes)])

    def merged(self, other: "DataLock") -> "DataLock":
        """This ledger followed by ``other``'s entries."""
        return DataLock(self.reads + other.reads, self.writes + other.writes)

    def tags(self) -> dict:
        """The MLflow tags of this ledger: ``kaos_lib.data.<repo>.commit`` and, for shared reads, ``.owner``."""
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

    def write_step(self, step: str, run_id: Optional[str] = None, client=None) -> "DataLock":
        """Put this ledger on the MLflow run as ``ledger/<step>.json`` and set its tags; returns this ledger.

        ``step`` names the file, so each step writes its own and none rewrites another's. The run is ``run_id``,
        else the active MLflow run, else ``$MLFLOW_RUN_ID``.
        """
        run = _run_id(run_id)
        c = client or _client()
        try:
            for key, value in self.tags().items():
                c.set_tag(run, key, value)
            c.log_text(run, self.to_json(indent=2), f"{ARTIFACT_DIR}/{step}.json")
        except Exception as exc:  # noqa: BLE001 - any MLflow failure becomes one clear message
            raise LockError(f"cannot write the ledger to MLflow run {run} ({exc.__class__.__name__}: {exc}).") from None
        return self

    @staticmethod
    def replay(lock: Union["DataLock", str, bytes, dict, None]) -> Optional["DataLock"]:
        """From now on, resolves of the locked repositories return the locked commits (None stops replaying)."""
        global _replay
        _replay = lock if isinstance(lock, DataLock) or lock is None else DataLock.parse(lock)
        return _replay


_current = DataLock()
_replay: Optional[DataLock] = None
_strict: Optional[str] = None
_env_lock: tuple = (None, None)   # (the $KAOS_LIB_LOCK text, its parsed lock)


def current() -> DataLock:
    """The lock recording this process's reads."""
    return _current


def record(repo: str, ref: str, commit: str, owner: Optional[str] = None, name: Optional[str] = None) -> Read:
    """Record a read that did not go through ``datasets.resolve`` (e.g. a stream from the S3 gateway)."""
    return _current.record(repo, ref, commit, owner, name)


def write_step(step: str, run_id: Optional[str] = None, client=None) -> DataLock:
    """Write this process's ledger to the MLflow run as ``ledger/<step>.json`` (see ``DataLock.write_step``)."""
    return _current.write_step(step, run_id, client)


def load(run_id: str, client=None) -> DataLock:
    """The ledger of MLflow run ``run_id``: its ``ledger/*.json`` together, else its version 1 ``data.lock.json``."""
    lock = _download(client or _client(), run_id)
    if lock is None:
        raise LockError(f"MLflow run {run_id} has no {ARTIFACT_DIR}/ and no {OLD_ARTIFACT}: the run did not record "
                        "its data reads.")
    return lock


def strict(step: Optional[str]) -> None:
    """Inside pipeline step ``step`` a resolve the replayed ledger does not cover is refused (None: allowed again)."""
    global _strict
    _strict = step


def refusing() -> Optional[str]:
    """The step whose unpinned reads are refused, or None."""
    return _strict


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


def name_of(repo: str, commit: str, owner: Optional[str] = None) -> Optional[str]:
    """The name the replayed ledger gives the read of ``repo`` at ``commit``, or None."""
    lock = replaying()
    owner = owner or None
    return next((r.name for r in lock.reads if (r.repo, r.commit, r.owner) == (repo, commit, owner)), None) \
        if lock else None


def reset() -> None:
    """Forget the recorded reads and stop replaying (tests; long-lived processes between runs)."""
    global _current, _replay, _env_lock, _strict
    _current, _replay, _env_lock, _strict = DataLock(), None, (None, None), None


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


def _text_of(client, run_id: str, path: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        return pathlib.Path(client.download_artifacts(run_id, path, tmp)).read_text()


def _download(client, run_id: str) -> Optional[DataLock]:
    """The run's ledger, or None when it holds neither ``ledger/*.json`` nor a version 1 ``data.lock.json``."""
    try:
        top = {f.path for f in client.list_artifacts(run_id)}
        parts = sorted(f.path for f in client.list_artifacts(run_id, ARTIFACT_DIR)) if ARTIFACT_DIR in top else []
        parts = [p for p in parts if p.endswith(".json")]
        if not parts and OLD_ARTIFACT not in top:
            return None
        texts = [(p, _text_of(client, run_id, p)) for p in parts or [OLD_ARTIFACT]]
    except Exception as exc:  # noqa: BLE001 - any MLflow failure becomes one clear message
        raise LockError(f"cannot read the ledger of MLflow run {run_id} ({exc.__class__.__name__}: {exc}).") from None
    lock = DataLock()
    for path, text in texts:
        lock = lock.merged(DataLock.parse(text, f"{path} of MLflow run {run_id}"))
    return lock
