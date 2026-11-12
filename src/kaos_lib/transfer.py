"""Moving file trees to and from a lakeFS ref: plan a mirror, upload, download.

Used by the layouts and by ``outputs``. Parallel, no layout knowledge.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import pathlib
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import requests

from .errors import LakeFSError, NotFoundError
from .lakefs import LakeFS

UPLOAD_ATTEMPTS = 4                               # one upload is tried this often
RETRY_STATUSES = (408, 429, 500, 502, 503, 504)   # answers that can pass
RETRY_PAUSE_S = 1.0                               # before the second try; doubled each time

# layouts.local.MARKER: a pulled copy's marker never goes back up when the folder is pushed.
IGNORED_NAMES = {".DS_Store", "Thumbs.db", ".kubecore-dataset.json", ".kaos-ready"}


@dataclass
class MirrorPlan:
    """What making a ref's tree equal a local directory takes."""
    add: list = field(default_factory=list)      # (local Path, repo path): new or changed
    delete: list = field(default_factory=list)   # repo paths absent locally
    unchanged: int = 0

    @property
    def empty(self) -> bool:
        return not self.add and not self.delete


def _md5(path: pathlib.Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def local_files(root: pathlib.Path, prefix: str = "") -> dict:
    """repo path -> local Path for every regular file under ``root``."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in IGNORED_NAMES and ".git" not in p.relative_to(root).parts:
            rel = p.relative_to(root).as_posix()
            out[f"{prefix}{rel}"] = p
    return out


def plan_mirror(client: LakeFS, repo: str, ref: str, root: pathlib.Path) -> MirrorPlan:
    """Diff ``root`` against ``ref``'s whole tree (checksum compare)."""
    remote = {o["path"]: o.get("checksum", "") for o in client.list_objects(repo, ref)}
    plan = MirrorPlan()
    local = local_files(root)
    for path, p in local.items():
        if remote.get(path) == _md5(p):
            plan.unchanged += 1
        else:
            plan.add.append((p, path))
    plan.delete = sorted(set(remote) - set(local))
    return plan


def _parallel(client: LakeFS, items: Iterable, fn) -> None:
    items = list(items)
    with cf.ThreadPoolExecutor(max_workers=min(client.concurrency, max(1, len(items)))) as ex:
        for fut in [ex.submit(fn, i) for i in items]:
            fut.result()  # re-raises the first failure


def upload(client: LakeFS, repo: str, branch: str, path: str, local: pathlib.Path) -> None:
    """Upload one file, again after a failure that can pass (the connection, a busy or restarting server).

    An upload replaces the object at its path, so repeating it is safe. A refusal (not allowed, not found, a bad
    request) is raised at once; so is the last of ``UPLOAD_ATTEMPTS`` failures.
    """
    for attempt in range(UPLOAD_ATTEMPTS):
        try:
            return client.upload_object(repo, branch, path, local)
        except (LakeFSError, requests.RequestException) as exc:
            passing = not isinstance(exc, LakeFSError) or exc.status in RETRY_STATUSES
            if not passing or isinstance(exc, NotFoundError) or attempt == UPLOAD_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_PAUSE_S * 2 ** attempt)


def apply_plan(client: LakeFS, repo: str, branch: str, plan: MirrorPlan) -> None:
    """Stage the plan's uploads and deletes on ``branch`` (the caller commits)."""
    _parallel(client, plan.add, lambda a: upload(client, repo, branch, a[1], a[0]))
    _parallel(client, plan.delete, lambda path: client.delete_object(repo, branch, path))


def upload_files(client: LakeFS, repo: str, branch: str, files: dict) -> int:
    """Upload ``{repo path: local Path}`` to ``branch``; returns the file count."""
    _parallel(client, files.items(), lambda kv: upload(client, repo, branch, kv[0], kv[1]))
    return len(files)


def upload_tree(client: LakeFS, repo: str, branch: str, root: pathlib.Path, prefix: str = "") -> int:
    """Upload every file under ``root`` to ``branch`` below ``prefix``; returns the file count."""
    return upload_files(client, repo, branch, local_files(root, prefix))


def download_prefixes(client: LakeFS, repo: str, commit: str, prefixes: Iterable, dest: pathlib.Path,
                      strip: str = "", keep: Optional[Callable[[str], bool]] = None) -> int:
    """Download every object under any of ``prefixes`` at ``commit`` into ``dest``; returns the count.

    ``strip`` is removed from the start of each path before it is written below ``dest``; ``keep(path)``,
    when given, chooses which of the listed objects to download. An object under two prefixes is fetched once.
    """
    listed = dict.fromkeys(o["path"] for pre in prefixes for o in client.list_objects(repo, commit, pre))
    paths = [p for p in listed if keep is None or keep(p)]
    _parallel(client, paths, lambda p: client.download_object(repo, commit, p, dest / p[len(strip):]))
    return len(paths)
