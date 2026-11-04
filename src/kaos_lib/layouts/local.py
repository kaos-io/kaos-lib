"""Local copies of dataset versions, shared by every layout: cache, staged dir, atomic download.

A copy is keyed by (owner, repo, commit[, prefix]) through a marker file, so a second call is free; a
dataset another project shares lives under ``<cache>/<owner>/<repo>/<commit>``, apart from the own ones
(``<cache>/<repo>/<commit>``). A staged copy (``$KAOS_STAGED_DIR``, e.g. Slurm staging) that holds
the commit of the same repository and owner is used in place.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import tempfile
from typing import Optional

from .. import _env
from ..errors import DatasetError, EmptyDataset
from ..lakefs import LakeFS
from ..transfer import download_prefixes

MARKER = ".kaos-dataset.json"
LEGACY_MARKER = ".kubecore-dataset.json"  # copies materialized before the rename
STAGED_COMMIT_FILES = (".kaos-commit", ".kaos-ready")  # Slurm stager markers that may hold the commit


def _marker_path(directory: pathlib.Path) -> pathlib.Path:
    """The marker file of a copy: the current name, else the pre-rename one."""
    return directory / MARKER if (directory / MARKER).is_file() else directory / LEGACY_MARKER


def cache_root() -> pathlib.Path:
    """Default home of materialized datasets (``$KAOS_CACHE_DIR``)."""
    override = _env.get("CACHE_DIR")
    if override:
        return pathlib.Path(override)
    new, old = pathlib.Path.home() / ".cache" / "kaos" / "datasets", pathlib.Path.home() / ".cache" / "kubecore" / "datasets"
    return old if old.exists() and not new.exists() else new  # an existing older cache keeps being used


def cache_dir(repo: str, commit: str, prefix: Optional[str] = None, owner: Optional[str] = None) -> pathlib.Path:
    """Default folder for (owner, repo, commit, prefix); ``owner`` None is the own project."""
    base = cache_root() / owner / repo if owner else cache_root() / repo
    if not prefix:
        return base / commit
    clean = prefix.strip("/")
    tag = re.sub(r"[^A-Za-z0-9_.-]", "_", clean)[:40] + "-" + hashlib.sha1(clean.encode()).hexdigest()[:8]
    return base / f"{commit}@{tag}"


def marker_matches(directory: pathlib.Path, repo: str, commit: str, prefix: Optional[str] = None,
                   required: Optional[str] = None, owner: Optional[str] = None,
                   include: Optional[list] = None) -> bool:
    """True when ``directory`` is a finished copy of exactly (owner, repo, commit, prefix, include)."""
    try:
        m = json.loads(_marker_path(directory).read_text())
    except (OSError, ValueError):
        return False
    same = m.get("repo") == repo and m.get("commit") == commit and (m.get("prefix") or None) == (prefix or None)
    same = same and (m.get("owner") or None) == (owner or None)
    same = same and (m.get("include") or None) == (list(include) if include else None)
    return same and (required is None or (directory / required).is_file())


def _staged_info(staged: pathlib.Path) -> dict:
    """The stager's ``.kaos-ready`` record (``repo``, ``commit``, ``owner`` ...), or {} when it has none."""
    try:
        info = json.loads((staged / STAGED_COMMIT_FILES[1]).read_text())
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def staged_dir(commit: str, required: Optional[str] = None, *, repo: Optional[str] = None,
               owner: Optional[str] = None) -> Optional[pathlib.Path]:
    """The staged copy when ``$KAOS_STAGED_DIR`` holds ``commit`` (and the ``required`` file), else None.

    A stager record naming another repository or another owner disqualifies it; a shared dataset
    (``owner`` set) is used only from a copy whose record names that owner.
    """
    raw = _env.get("STAGED_DIR")
    if not raw:
        return None
    staged = pathlib.Path(raw)
    if not staged.is_dir() or (required and not (staged / required).is_file()):
        return None
    holders = [staged.name] + [(staged / f).read_text() for f in STAGED_COMMIT_FILES if (staged / f).is_file()]
    if not any(commit in h for h in holders):
        return None
    info = _staged_info(staged)
    if repo and info.get("repo") and info["repo"] != repo:
        return None
    return staged if (info.get("owner") or None) == (owner or None) else None


def fetch(client: LakeFS, repo: str, commit: str, prefixes, target: pathlib.Path, prefix: Optional[str] = None,
          strip: str = "", finalize=None, empty_message: str = "", owner: Optional[str] = None,
          include: Optional[list] = None, keep=None) -> None:
    """Download ``prefixes`` at ``commit`` into ``target`` atomically and write the marker.

    ``strip`` is removed from the start of every path; ``keep(path)``, when given, picks the objects;
    ``finalize(tmp_dir)`` may adjust the copy before it is published. Refuses to overwrite a non-empty
    folder that is not a kaos-lib copy. The marker records ``owner`` (None for the own project) and the
    layout's ``include`` patterns (None: the whole tree).
    """
    if target.exists() and any(target.iterdir()) and not _marker_path(target).is_file():
        raise DatasetError(f"{target} is not empty and is not a kaos-lib dataset copy; pick another folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=target.name + ".part-", dir=target.parent))
    try:
        if download_prefixes(client, repo, commit, prefixes, tmp, strip, keep) == 0 and empty_message:
            raise EmptyDataset(empty_message)
        if finalize:
            finalize(tmp)
        marker = {"repo": repo, "commit": commit, "prefix": prefix, "owner": owner}
        if include:
            marker["include"] = list(include)
        (tmp / MARKER).write_text(json.dumps(marker))
        shutil.rmtree(target, ignore_errors=True)
        os.replace(tmp, target)  # atomic: a half-downloaded copy is never visible as complete
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
