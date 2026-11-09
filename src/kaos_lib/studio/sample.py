"""A small local sample of a dataset, through the same lakeFS client `kaosctl dataset pull` uses.

Why: a step that reads a dataset should be tried on a few files, not the whole dataset (PRD D-16). The sample is chosen
deterministically (small files first, spread across the dataset's top-level folders) and capped by a size, so two runs
see the same files. It needs the user's own sign-in (`kaosctl login`): nothing platform-internal is read.
"""
from __future__ import annotations

import pathlib
from typing import Optional

from .. import datasets
from ..errors import KaosLibError
from ..lakefs import LakeFS


def choose(objects: list, max_bytes: int) -> list:
    """The objects to download: root files first, then round-robin over the top-level folders, smallest first,
    until `max_bytes` is reached. `objects` are lakeFS listings with `path` and `size_bytes`."""
    groups: dict = {}
    for o in sorted(objects, key=lambda o: (o.get("size_bytes", 0), o["path"])):
        top = o["path"].split("/", 1)[0] if "/" in o["path"] else ""
        groups.setdefault(top, []).append(o)
    order, picked, used = [""] + sorted(k for k in groups if k), [], 0
    while any(groups.get(k) for k in order):
        for key in order:
            queue = groups.get(key) or []
            if queue:
                nxt = queue.pop(0)
                if used + nxt.get("size_bytes", 0) <= max_bytes:
                    picked.append(nxt)
                    used += nxt.get("size_bytes", 0)
    return picked


def pull_sample(ref_text: str, dest: pathlib.Path, max_mb: int, client: Optional[LakeFS] = None) -> tuple:
    """Download a sample of `<repository>@<ref>` into `dest`. Returns (files, bytes)."""
    ref = datasets.DatasetRef.parse(ref_text)
    c = client or LakeFS.connect()
    ref, c = datasets.source(ref, c)
    commit = ref.commit or datasets.resolve(ref, c)
    listed = list(c.list_objects(ref.repo, commit, ""))
    if not listed:
        raise KaosLibError(f"{ref_text} holds no files yet: push some with `kaosctl dataset push`.")
    chosen = choose(listed, max_mb * 1024 * 1024)
    if not chosen:
        raise KaosLibError(f"every file of {ref_text} is larger than the {max_mb} MB sample: raise --sample-mb.")
    for o in chosen:
        c.download_object(ref.repo, commit, o["path"], dest / o["path"])
    return len(chosen), sum(o.get("size_bytes", 0) for o in chosen)
