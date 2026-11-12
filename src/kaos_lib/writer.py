"""Save what a step wrote: one version of a dataset, or the files of a model or an artifact.

``step.result()`` saves every output it declared in two phases, and the same code does all three kinds:

1. **Seal** (``seal``), for every output, moving no ``main``. Start a run branch from the head of ``main`` (the
   last version), upload what is new or changed and delete what is gone below the output's path (so a retry
   never leaves a file of an earlier attempt), check that the branch holds exactly the folder, commit, check the
   commit again, and keep a dataset's commit with a tag. Files that did not change are shared with the last
   version and cost nothing. Content that an earlier attempt of the same step already sealed is reused.
2. **Promote** (``promote``), only when everything is sealed. A model or an artifact is merged into ``main``. A
   dataset is merged only when the run asks, and on the condition that ``main`` is still where the seal started
   (``expected_head``); when it moved, another run promoted first, so seal again on the new head and retry.

Nothing is written to ``main`` directly. A step that dies half-way leaves uncommitted uploads on its branch and
no version. A failed step moves no dataset's ``latest``, with one exception that cannot be closed: promoting two
datasets is two merges in two repositories, and the second can fail after the first has moved.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field
from typing import Optional

from .errors import LakeFSError, NotFoundError, StepError
from .lakefs import LakeFS
from .transfer import apply_plan, local_manifest, plan_mirror

MAIN = "main"
PROMOTE_ATTEMPTS = 3
HEAD_MOVED = 412          # kaos-lake: the merge's expected head is not the branch's head any more


def _name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", text)


def run_branch(run: str, step: str, name: str) -> str:
    """The branch one output of one step of one run is written on."""
    return _name(f"run-{run}-{step}-{name}")


def keep_prefix(run: str, step: str) -> str:
    """What the tags that keep a step's sealed versions start with: ``k-<run>-<step>``."""
    return _name(f"k-{run}-{step}")


@dataclass
class Sealed:
    """One output that has been sealed. ``commit`` is what holds the folder; it is ``head`` when the folder is
    what ``main`` already holds."""
    client: LakeFS
    repo: str
    name: str
    folder: pathlib.Path
    prefix: str                  # where the output lives in the repository ("" for a dataset)
    branch: str                  # the run branch's name
    tag_prefix: Optional[str]    # datasets are kept by a tag; models and artifacts are merged and need none
    message: str
    meta: dict
    head: str = ""
    commit: str = ""
    tag: Optional[str] = None
    open: bool = False                             # whether the run branch exists
    files: dict = field(default_factory=dict)      # repository path -> (size, md5) of the folder

    @property
    def guarded(self) -> bool:
        """Whether the merge must name the head it expects: a dataset has one writer and one latest."""
        return self.tag_prefix is not None


def _differences(client: LakeFS, repo: str, ref: str, files: dict, prefix: str) -> list:
    """The paths where ``ref`` and the folder differ below ``prefix`` (missing, extra, another size or checksum)."""
    held = {o["path"]: (o.get("size_bytes"), o.get("checksum", "")) for o in client.list_objects(repo, ref, prefix)}
    return sorted(p for p in set(held) | set(files) if held.get(p) != files.get(p))


def _check(s: Sealed, ref: str, then: str) -> None:
    differing = _differences(s.client, s.repo, ref, s.files, s.prefix)
    if differing:
        raise StepError(f"output '{s.name}': {len(differing)} files differ between what the step wrote and what "
                        f"lakeFS holds in {s.repo} at {ref if ref == s.branch else ref[:12]} (first: {differing[0]}). "
                        f"{then}")


def discard(s: Sealed) -> None:
    """Delete the run branch. Best effort: it never hides the error that is being raised."""
    if s.open:
        s.open = False
        try:
            s.client.delete_branch(s.repo, s.branch)
        except Exception:  # noqa: BLE001 - a branch that stays is harmless: the next attempt starts it again
            pass


def _earlier(s: Sealed) -> Optional[dict]:
    """The tag of a commit an earlier attempt of this step sealed that holds exactly this folder and was staged on
    the head ``main`` has now (so promoting it cannot mix in what another run changed), or None.

    Run and step names have hyphens, so a tag name alone does not say whose it is. A tag is a candidate only when it
    is exactly ``<prefix>-<12 hex>``, those 12 characters start the commit it points at, and that commit's metadata
    names this very run and step."""
    own = re.compile(re.escape(s.tag_prefix) + "-([0-9a-f]{12})")
    for tag in s.client.tags(s.repo):
        found = own.fullmatch(tag["id"])
        commit = tag["commit_id"]
        if found and commit.startswith(found.group(1)):
            info = s.client.commit_info(s.repo, commit)
            meta = info.get("metadata") or {}
            if meta.get("kaos.run") == s.meta.get("kaos.run") and meta.get("kaos.step") == s.meta.get("kaos.step") \
                    and info.get("parents") == [s.head] \
                    and not _differences(s.client, s.repo, commit, s.files, s.prefix):
                return tag
    return None


def _keep(s: Sealed) -> None:
    """Tag the sealed commit ``k-<run>-<step>-<its first 12 characters>``: unique, so a retry never collides."""
    tag = f"{s.tag_prefix}-{s.commit[:12]}"
    try:
        s.client.create_tag(s.repo, tag, s.commit)
    except LakeFSError as exc:
        if exc.status != 409 or s.client.tag_commit(s.repo, tag) != s.commit:   # 409: this very commit is kept
            raise
    s.tag = tag


def seal(client: LakeFS, repo: str, folder: pathlib.Path, *, name: str, prefix: str = "", branch: str,
         tag_prefix: Optional[str] = None, message: str, meta: dict) -> Sealed:
    """Make ``repo`` hold ``folder`` (below ``prefix``) as one commit on ``branch``, without touching ``main``."""
    local = local_manifest(pathlib.Path(folder), prefix)
    try:
        head = client.branch_commit(repo, MAIN)
    except NotFoundError:
        raise StepError(f"{repo} does not exist. The platform creates the dataset or the outputs of an app when "
                        "its pipeline declares them in produces=[...]; it is there shortly after that change is "
                        "merged.") from None
    s = Sealed(client, repo, name, pathlib.Path(folder), prefix, branch, tag_prefix, message, meta, head, head,
               files={path: (size, md5) for path, (_, size, md5) in local.items()})
    if tag_prefix and (earlier := _earlier(s)):
        s.commit, s.tag = earlier["commit_id"], earlier["id"]
        return s
    try:
        client.delete_branch(repo, branch)            # an earlier attempt's: its base may not be this head
        client.create_branch(repo, branch, head)
        s.open = True
        apply_plan(client, repo, branch, plan_mirror(client, repo, branch, s.folder, prefix, local))
        _check(s, branch, "Nothing was sealed.")
        s.commit = client.commit(repo, branch, message, meta, tolerate_empty=True)
        if s.commit != head:
            _check(s, s.commit, "It was not promoted.")
            if tag_prefix:
                _keep(s)
    except Exception:
        discard(s)
        raise
    return s


def promote(s: Sealed) -> str:
    """Merge the sealed commit into ``main``; returns the commit that is now the version (the merge commit).

    A dataset's merge names the head it expects. When ``main`` moved (HTTP 412) the output is sealed again on the
    new head, at most ``PROMOTE_ATTEMPTS`` times.
    """
    for attempt in range(1, PROMOTE_ATTEMPTS + 1):
        if s.commit == s.head:                        # the folder is what main already holds
            discard(s)
            return s.head
        try:
            merged = s.client.merge(s.repo, s.commit, MAIN, s.message, s.meta, tolerate_empty=True,
                                    expected_head=s.head if s.guarded else None)
        except LakeFSError as exc:
            if exc.status != HEAD_MOVED:
                raise
            if attempt == PROMOTE_ATTEMPTS:
                raise StepError(f"output '{s.name}': {s.repo} changed {PROMOTE_ATTEMPTS} times while this step was "
                                f"promoting it. Another run is writing the same dataset. The sealed version "
                                f"{s.commit[:12]} is kept as {s.tag}.") from None
            discard(s)
            s.__dict__.update(seal(s.client, s.repo, s.folder, name=s.name, prefix=s.prefix, branch=s.branch,
                                   tag_prefix=s.tag_prefix, message=s.message, meta=s.meta).__dict__)
            continue
        _check(s, merged, "It is now the latest version: tell the platform team.")
        discard(s)
        return merged
    raise AssertionError("unreachable")
