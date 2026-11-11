"""Local copies of dataset versions, shared by every layout: cache, staged dir, atomic download.

A copy is keyed by (owner, repo, commit[, prefix]) through a marker file, so a second call is free; a
dataset another project shares lives under ``<cache>/<owner>/<repo>/<commit>``, apart from the own ones
(``<cache>/<repo>/<commit>``). A staged copy (a folder under ``$KAOS_STAGED_ROOT``, HPC (Slurm) staging) that holds
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

from ..errors import DatasetError, EmptyDataset
from ..lakefs import LakeFS
from ..transfer import download_prefixes

MARKER = ".kubecore-dataset.json"
STAGED_ENV, CACHE_ENV = "KAOS_STAGED_ROOT", "KUBECORE_CACHE_DIR"
STAGED_MARKER = ".kaos-ready"      # written last by whoever staged the folder: {"repo", "commit", "owner", "full"}


def cache_root() -> pathlib.Path:
    """Default home of materialized datasets (``$KUBECORE_CACHE_DIR``)."""
    return pathlib.Path(os.environ.get(CACHE_ENV) or pathlib.Path.home() / ".cache" / "kubecore" / "datasets")


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
        m = json.loads((directory / MARKER).read_text())
    except (OSError, ValueError):
        return False
    same = m.get("repo") == repo and m.get("commit") == commit and (m.get("prefix") or None) == (prefix or None)
    same = same and (m.get("owner") or None) == (owner or None)
    same = same and (m.get("include") or None) == (list(include) if include else None)
    return same and (required is None or (directory / required).is_file())


def staged_info(staged: pathlib.Path) -> dict:
    """The folder's ``.kaos-ready`` record, or {} when it has none or it is not a JSON object."""
    try:
        info = json.loads((staged / STAGED_MARKER).read_text())
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def staged_dir(commit: str, required: Optional[str] = None, *, repo: str,
               owner: Optional[str] = None) -> Optional[pathlib.Path]:
    """The staged copy of ``repo`` at ``commit`` (holding the ``required`` file), else None.

    On an HPC (Slurm) site the inputs of a step are copied next to the job before it starts: one folder per
    input under ``$KAOS_STAGED_ROOT``, named after the input. A folder is used only when its ``.kaos-ready``
    record names this repository, this commit and this owner (absent or null for the own project) and says
    ``"full": true``, the whole tree of the commit. Anything else (another commit, a partial copy, no record)
    is not used, and the caller downloads. The record may also name the dataset's ``layout``; a step then reads
    the copy without asking lakeFS for it.
    """
    raw = os.environ.get(STAGED_ENV)
    if not raw or not pathlib.Path(raw).is_dir():
        return None
    for staged in sorted(p for p in pathlib.Path(raw).iterdir() if p.is_dir()):
        info = staged_info(staged)
        if (info.get("repo"), info.get("commit"), info.get("owner") or None) != (repo, commit, owner or None):
            continue
        if info.get("full") is True and (not required or (staged / required).is_file()):
            return staged
    return None


def fetch(client: LakeFS, repo: str, commit: str, prefixes, target: pathlib.Path, prefix: Optional[str] = None,
          strip: str = "", finalize=None, empty_message: str = "", owner: Optional[str] = None,
          include: Optional[list] = None, keep=None) -> None:
    """Download ``prefixes`` at ``commit`` into ``target`` atomically and write the marker.

    ``strip`` is removed from the start of every path; ``keep(path)``, when given, picks the objects;
    ``finalize(tmp_dir)`` may adjust the copy before it is published. Refuses to overwrite a non-empty
    folder that is not a kaos-lib copy. The marker records ``owner`` (None for the own project) and the
    layout's ``include`` patterns (None: the whole tree).
    """
    if target.exists() and any(target.iterdir()) and not (target / MARKER).is_file():
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
