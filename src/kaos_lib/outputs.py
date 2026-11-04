"""Run outputs: each ML app writes its results to its own ``outputs-<app>`` repository.

One commit on ``main`` per step per run (a merge from the run's own branch), under
``<kind>/<experiment>/<run>/`` (kind is ``checkpoints`` by default). Pipelines never write to a ``dataset-*`` repository.
The repository is declared and created by the platform, never here.

Saved on the stop signal: while a run writer is open, a step that gets ``SIGUSR1`` (sent by the platform about
10 minutes before a Slurm time limit) uploads again everything it already passed to ``save`` and every
``autosave`` path, commits on the run branch, and exits with ``CHECKPOINT_EXIT_CODE``. The platform then
continues the run in a new job, where ``latest`` finds the checkpoint. Step code adds nothing.
"""
from __future__ import annotations

import os
import pathlib
import re
import signal
import sys
import tempfile
import threading
from typing import Optional

from .errors import DatasetError, LakeFSError, NotFoundError
from .lakefs import LakeFS
from .transfer import upload_files, upload_tree

OUTPUTS_PREFIX = "outputs-"
MAIN = "main"
STOP_SIGNAL = signal.SIGUSR1
CHECKPOINT_EXIT_CODE = 85   # "saved, continue me": the platform resubmits the run instead of failing it
_APP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]*$")


def outputs_repo(app: str) -> str:
    """``outputs-<app>`` for an app name (a name already prefixed is returned as is)."""
    short = app[len(OUTPUTS_PREFIX):] if app.startswith(OUTPUTS_PREFIX) else app
    if not _APP_RE.match(short):
        raise DatasetError(f"invalid app name {app!r}: use lowercase letters, digits and '-'.")
    return OUTPUTS_PREFIX + short


def _segment(label: str, value: str) -> str:
    if not _SEGMENT_RE.match(value or "") or ".." in value:
        raise DatasetError(f"invalid {label} {value!r}: use letters, digits, '.', '_', '-' and '=' (no '/').")
    return value


def run_prefix(experiment: str, run: str, kind: str = "checkpoints") -> str:
    """Repository path under which a run's results of ``kind`` live: ``<kind>/<experiment>/<run>/``."""
    return f"{_segment('kind', kind)}/{_segment('experiment', experiment)}/{_segment('run', run)}/"


def run_branch(run: str, kind: str = "checkpoints") -> str:
    """Branch one step of a run writes on: ``run-<run>-<kind>`` with unsafe characters replaced."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", f"run-{run}-{kind}")


def _files_of(source) -> dict:
    """``{name: Path}`` for a list of files (placed by base name)."""
    out = {}
    for item in source:
        path = pathlib.Path(item)
        if not path.is_file():
            raise DatasetError(f"{path} is not a file.")
        if path.name in out:
            raise DatasetError(f"two files are both called {path.name!r}; save a folder instead.")
        out[path.name] = path
    return out


class RunWriter:
    """Durable, idempotent writer of one step's outputs (one kind) of one run.

    Everything is saved and committed on the run's own branch ``run-<run>-<kind>`` (created from main,
    or REUSED when it exists, so a retry or a preempted pod resumes). ``finish`` merges the branch into
    main (exactly one new commit on main per step per run) and deletes it. An exception inside the
    ``with`` block neither merges nor deletes. Needs write rights on ``outputs-<app>`` only.
    """

    def __init__(self, app: str, experiment: str, run: str, kind: str = "checkpoints",
                 client: Optional[LakeFS] = None, autosave=None):
        self.app, self.experiment, self.run, self.kind = app, experiment, run, kind
        self.repo, self.prefix = outputs_repo(app), run_prefix(experiment, run, kind)
        self.branch = run_branch(run, kind)
        self.client = client or LakeFS.connect()
        self._finished: Optional[str] = None
        # Saved again on the stop signal: these paths, and every source passed to ``save``.
        self.autosave = [autosave] if isinstance(autosave, (str, pathlib.Path)) else list(autosave or [])
        self._saved: list = []

    @property
    def metadata(self) -> dict:
        return {"app": self.app, "experiment": self.experiment, "run": self.run, "kind": self.kind}

    def open(self) -> "RunWriter":
        """Make sure the run branch exists (never deletes an existing one).

        When it already exists (a continued or retried run), the ``autosave`` files it holds are put back where
        they were (see ``restore``).
        """
        c = self.client
        try:
            c.branch_commit(self.repo, MAIN)
        except NotFoundError as exc:
            raise DatasetError(f"{self.repo} does not exist: the platform creates it for each ML app. "
                               "Check the app name.") from exc
        if c.branch_exists(self.repo, self.branch):
            self.restore()
        else:
            try:
                c.create_branch(self.repo, self.branch, MAIN)
            except LakeFSError as exc:
                if exc.status != 409:  # 409: a parallel attempt created it first, which is fine
                    raise
        _watch(self)
        return self

    def __enter__(self) -> "RunWriter":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None and self._finished is None:
                self.finish()
        finally:
            _unwatch(self)
        return False  # on an exception: no merge, no delete; the retry resumes from the branch

    def save(self, source, message: Optional[str] = None) -> str:
        """Upload a folder, a file or a list of files under the run's prefix and commit ON THE RUN BRANCH.

        Durable as soon as it returns. Saving identical content again is a success and returns the
        existing commit. Returns the commit id.
        """
        if isinstance(source, (str, pathlib.Path)) and pathlib.Path(source).is_dir():
            count = upload_tree(self.client, self.repo, self.branch, pathlib.Path(source), self.prefix)
        else:
            items = [source] if isinstance(source, (str, pathlib.Path)) else list(source)
            files = {self.prefix + name: p for name, p in _files_of(items).items()}
            count = upload_files(self.client, self.repo, self.branch, files)
        if count == 0:
            raise DatasetError(f"{source} has no files to save.")
        if not any(source is s or source == s for s in self._saved):
            self._saved.append(source)
        return self.client.commit(self.repo, self.branch, message or f"{self.kind}: {self.experiment}/{self.run}",
                                  self.metadata, tolerate_empty=True)

    def latest(self, path_prefix: str = "", dest=None) -> Optional[pathlib.Path]:
        """Download what the run branch already holds so training can resume; None when there is nothing.

        ``path_prefix`` is relative to the run's prefix. If it is empty or ends with ``/`` the whole
        folder is downloaded and its local path returned; otherwise the most recently written object
        whose path starts with it is downloaded and its local file path returned.
        """
        c, base = self.client, self.prefix + path_prefix
        objs = list(c.list_objects(self.repo, self.branch, base))
        if not objs:
            return None
        root = pathlib.Path(dest) if dest else pathlib.Path(tempfile.gettempdir()) / "kubecore-runs" / self.repo / self.branch
        if path_prefix == "" or path_prefix.endswith("/"):
            for o in objs:
                c.download_object(self.repo, self.branch, o["path"], root / o["path"][len(self.prefix):])
            return root / path_prefix
        newest = max(objs, key=lambda o: (o.get("mtime", 0), o["path"]))
        target = root / newest["path"][len(self.prefix):]
        c.download_object(self.repo, self.branch, newest["path"], target)
        return target

    def finish(self, metadata: Optional[dict] = None) -> str:
        """Merge the run branch into main (one commit) and delete the branch; returns the main commit.

        The merge commit carries ``{app, experiment, run, kind, **metadata}`` (dataset ref/commit,
        MLflow run id, ...). Nothing to merge counts as success and returns main's head. Idempotent.
        """
        if self._finished is not None:
            return self._finished
        c = self.client
        commit = c.merge(self.repo, self.branch, MAIN, f"{self.kind}: {self.experiment}/{self.run}",
                         {**self.metadata, **(metadata or {})}, tolerate_empty=True)
        c.delete_branch(self.repo, self.branch)
        self._finished = commit
        _unwatch(self)
        return commit

    def restore(self) -> list:
        """Put each ``autosave`` file the run branch holds back at its local path; returns the paths restored.

        A file is saved under its name (``save``), so the object ``<prefix><name>`` is the file of ``<.../name>``.
        Skipped: a path that already exists locally (never overwritten), a name the branch does not hold, and
        folders (their files are saved without the folder's name; use ``latest("folder/")``). The download goes
        to a temporary name first, so a failed one leaves nothing half-written, and raises: a run that cannot get
        its checkpoint back must not quietly start over.
        """
        restored = []
        for item in self.autosave:
            local = pathlib.Path(item)
            if str(item).endswith(("/", "\\")) or local.exists():
                continue
            remote = self.prefix + local.name
            if not any(o["path"] == remote for o in self.client.list_objects(self.repo, self.branch, remote)):
                continue
            part = local.with_name(local.name + ".kaos-restore")
            try:
                self.client.download_object(self.repo, self.branch, remote, part)
                os.replace(part, local)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            print(f"kaos-lib: restored {local} from the run branch", file=sys.stderr, flush=True)
            restored.append(local)
        return restored

    def save_on_stop(self) -> int:
        """Upload again what ``save`` wrote and the ``autosave`` paths that exist now; returns how many were saved.

        Called by the stop-signal handler. A path that is gone or empty is skipped, and a failed upload is reported
        and skipped, so one bad path cannot cost the others.
        """
        saved = 0
        for source in [*self.autosave, *self._saved]:
            items = [source] if isinstance(source, (str, pathlib.Path)) else list(source)
            present = [p for p in items if pathlib.Path(p).exists()]
            if not present:
                continue
            try:
                self.save(present[0] if len(present) == 1 and isinstance(source, (str, pathlib.Path)) else present,
                          message=f"{self.kind}: {self.experiment}/{self.run} (saved on the stop signal)")
                saved += 1
            except Exception as exc:   # noqa: BLE001 - keep saving the others, the step is stopping anyway
                print(f"kaos-lib: could not save {source} on the stop signal: {exc}", file=sys.stderr, flush=True)
        return saved


# Run writers open in this process, and the stop-signal handler they share (installed by the first one).
_WATCHED: list = []
_HANDLER = {"pid": None, "previous": None, "stopping": False}


def _on_stop_signal(signum, frame):
    """Save every open run writer, then exit with CHECKPOINT_EXIT_CODE so the platform continues the run.

    Only the process that installed the handler acts: forked workers (DataLoader) inherit it and ignore it.
    """
    if os.getpid() != _HANDLER["pid"] or _HANDLER["stopping"]:
        return
    _HANDLER["stopping"] = True
    print("kaos-lib: stop signal - saving progress before the time limit", file=sys.stderr, flush=True)
    saved = sum(w.save_on_stop() for w in list(_WATCHED))
    print(f"kaos-lib: saved {saved} path(s); exiting {CHECKPOINT_EXIT_CODE} so the run continues in a new job",
          file=sys.stderr, flush=True)
    raise SystemExit(CHECKPOINT_EXIT_CODE)   # no merge: the run branch stays for the continued run


def _watch(writer: RunWriter) -> None:
    if writer in _WATCHED:
        return
    _WATCHED.append(writer)
    if _HANDLER["pid"] != os.getpid() and threading.current_thread() is threading.main_thread():
        _HANDLER["previous"] = signal.signal(STOP_SIGNAL, _on_stop_signal)
        _HANDLER["pid"], _HANDLER["stopping"] = os.getpid(), False


def _unwatch(writer: RunWriter) -> None:
    if writer in _WATCHED:
        _WATCHED.remove(writer)
    if not _WATCHED and _HANDLER["pid"] == os.getpid() and threading.current_thread() is threading.main_thread():
        signal.signal(STOP_SIGNAL, _HANDLER["previous"] or signal.SIG_DFL)
        _HANDLER["pid"], _HANDLER["previous"] = None, None


def run(app: str, experiment: str, run: str, kind: str = "checkpoints",
        client: Optional[LakeFS] = None, autosave=None) -> RunWriter:
    """``with outputs.run(app, experiment, run, kind) as r:`` ... see ``RunWriter``.

    ``autosave``: a path or a list of paths (for example the folder a framework writes its checkpoints to) uploaded
    on the stop signal even if the step never passed them to ``save``.
    """
    return RunWriter(app, experiment, run, kind, client, autosave)


def write_run(app: str, experiment: str, run: str, local_dir, kind: str = "checkpoints",
              client: Optional[LakeFS] = None, metadata: Optional[dict] = None) -> str:
    """Open the run writer, save ``local_dir`` once, finish; returns the merge commit on main."""
    if not pathlib.Path(local_dir).is_dir():
        raise DatasetError(f"{local_dir} is not a directory.")
    with RunWriter(app, experiment, run, kind, client) as r:
        r.save(local_dir)
        return r.finish(metadata)
