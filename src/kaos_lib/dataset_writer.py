"""Write one version of a dataset a pipeline step produces.

A step that declares ``produces=[dataset("clean")]`` fills a local folder; ``step.result()`` hands it to
``write_version``, which makes the dataset's repository hold exactly that folder as one new commit:

1. **Stage.** Read the head of ``main`` (the last version) and branch ``run-<run>-<step>`` from it, so every file
   that did not change is shared with the last version and costs nothing.
2. **Mirror.** Upload what is new or changed, delete what is gone (``transfer.plan_mirror``). A second run with one
   changed file uploads one file.
3. **Check.** The branch must list exactly the files of the folder, with their sizes and checksums.
4. **Seal.** Commit. Identical content makes no commit: the last version is the answer.
5. **Verify.** The sealed commit must list exactly the files of the folder.
6. **Keep.** Tag the sealed commit ``k-<run>-<step>``, so it outlives its branch.
7. **Promote**, only when the run asks: merge into ``main`` on the condition that ``main`` is still at the head
   read in step 1. When it moved (another run promoted first), start again from the new head: a merge onto a
   moved ``main`` would mix the files of two runs.

Nothing is ever written to ``main`` directly. A step that is killed half-way leaves uncommitted uploads on its
branch and no version; the next attempt starts the branch again and seals once.
"""
from __future__ import annotations

import hashlib
import pathlib
import re

from .errors import LakeFSError, NotFoundError, StepError
from .lakefs import LakeFS
from .transfer import _md5, apply_plan, local_files, plan_mirror

MAIN = "main"
PROMOTE_ATTEMPTS = 3
HEAD_MOVED = 412          # kaos-lake: the merge's expected head is not the branch's head any more
TAG_TRIES = 5


def _name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", text)


def run_branch(run: str, step: str) -> str:
    """The branch one step of one run writes on: ``run-<run>-<step>``."""
    return _name(f"run-{run}-{step}")


def keep_tag(run: str, step: str) -> str:
    """The tag that keeps what one step of one run sealed: ``k-<run>-<step>``."""
    return _name(f"k-{run}-{step}")


def manifest(folder: pathlib.Path) -> dict:
    """``{path: (size, md5)}`` of every file of ``folder``: what the version must hold, and nothing about the run."""
    return {path: (p.stat().st_size, _md5(p)) for path, p in local_files(folder).items()}


def digest(files: dict) -> str:
    """One hash for a manifest: two folders with the same files have the same one."""
    text = "".join(f"{path}\t{size}\t{md5}\n" for path, (size, md5) in sorted(files.items()))
    return hashlib.sha256(text.encode()).hexdigest()


def _differences(client: LakeFS, repo: str, ref: str, files: dict) -> list:
    """The paths where ``ref`` and the manifest differ (missing, extra, another size or checksum)."""
    held = {o["path"]: (o.get("size_bytes"), o.get("checksum", "")) for o in client.list_objects(repo, ref)}
    return sorted(p for p in set(held) | set(files) if held.get(p) != files.get(p))


def _stage(client: LakeFS, repo: str, branch: str) -> str:
    """A fresh run branch at the head of main; returns that head."""
    try:
        head = client.branch_commit(repo, MAIN)
    except NotFoundError:
        raise StepError(f"the dataset {repo} does not exist. The platform creates a dataset when a step declares "
                        "it in produces=[...] in pipeline.py; it is there shortly after that change is merged.") \
            from None
    client.delete_branch(repo, branch)            # an earlier attempt's: its base may not be this head
    client.create_branch(repo, branch, head)
    return head


def _keep(client: LakeFS, repo: str, tag: str, commit: str) -> str:
    """Tag ``commit``; an earlier attempt of the same step that sealed other content keeps its own tag."""
    for n in range(1, TAG_TRIES + 1):
        name = tag if n == 1 else f"{tag}-{n}"
        try:
            client.create_tag(repo, name, commit)
            return name
        except LakeFSError as exc:
            if exc.status != 409:
                raise
            if client.tag_commit(repo, name) == commit:
                return name
    raise StepError(f"{repo}: the tags {tag} to {tag}-{TAG_TRIES} are all taken by other versions of this run.")


def write_version(client: LakeFS, repo: str, folder: pathlib.Path, *, name: str, run: str, step: str, app: str,
                  promote: bool = False, metadata: dict = None, echo=print) -> str:
    """Make ``folder`` one version of dataset ``repo``; returns the commit that is the version.

    That is the merge commit on ``main`` when the run promotes, the sealed commit (kept by its ``k-`` tag)
    when it does not, and the head of ``main`` when the folder equals the last version.
    """
    files = manifest(pathlib.Path(folder))
    branch, tag = run_branch(run, step), keep_tag(run, step)
    meta = {"kaos.run": run, "kaos.app": app, "kaos.step": step, "kaos.manifest": digest(files), **(metadata or {})}
    message = f"{name}: {app} {run} {step}"
    sealed = None
    for attempt in range(PROMOTE_ATTEMPTS):
        head = _stage(client, repo, branch)
        plan = plan_mirror(client, repo, branch, pathlib.Path(folder))
        echo(f"output '{name}': {len(plan.add)} file(s) to upload, {len(plan.delete)} to delete, "
             f"{plan.unchanged} unchanged since the last version of {repo}.", flush=True)
        apply_plan(client, repo, branch, plan)
        differing = _differences(client, repo, branch, files)
        if differing:
            raise StepError(f"output '{name}': {len(differing)} files differ between what the step wrote and what "
                            f"lakeFS holds (first: {differing[0]}). Nothing was sealed.")
        sealed = client.commit(repo, branch, message, meta, tolerate_empty=True)
        if sealed == head:
            client.delete_branch(repo, branch)
            echo(f"output '{name}': the same content as the last version of {repo} ({head[:12]}); no new version.",
                 flush=True)
            return head
        _verify(client, repo, sealed, files, name, "It was not promoted.")
        kept = _keep(client, repo, tag, sealed)
        if not promote:
            client.delete_branch(repo, branch)
            echo(f"output '{name}': sealed {repo} at {sealed[:12]} (kept as {kept}); latest was not moved.",
                 flush=True)
            return sealed
        try:
            merged = client.merge(repo, branch, MAIN, message, meta, expected_head=head)
        except LakeFSError as exc:
            if exc.status != HEAD_MOVED:
                raise
            echo(f"output '{name}': {repo} changed while this step was writing it; starting again from its new "
                 f"version (attempt {attempt + 2} of {PROMOTE_ATTEMPTS}).", flush=True)
            continue
        _verify(client, repo, merged, files, name, "It is now the latest version: tell the platform team.")
        client.delete_branch(repo, branch)
        echo(f"output '{name}': {repo} is now at {merged[:12]} (latest).", flush=True)
        return merged
    client.delete_branch(repo, branch)
    raise StepError(f"output '{name}': {repo} changed {PROMOTE_ATTEMPTS} times while this step was promoting it. "
                    f"Another run is writing the same dataset. The sealed version is kept as {tag} ({sealed[:12]}).")


def _verify(client: LakeFS, repo: str, commit: str, files: dict, name: str, then: str) -> None:
    differing = _differences(client, repo, commit, files)
    if differing:
        raise StepError(f"output '{name}': the version {commit} of {repo} is not what the step wrote "
                        f"({len(differing)} files differ, first: {differing[0]}). {then}")
