"""A sibling marker counts only for the folder it was written for: a folder the engineer deleted and re-created is
neither overwritten nor read as a copy."""
import json
import shutil

import pytest

from kaos_lib import datasets
from kaos_lib.errors import DatasetError
from kaos_lib.layouts import local


@pytest.fixture
def lake(fake):
    fake.add_repo("dataset-m1", metadata={"kaos.kind": "dataset"}, files={"a.txt": b"A"})
    fake.add_repo("dataset-m2", metadata={"kaos.kind": "dataset"}, files={"b.txt": b"B"})
    return fake


def _materialize(client, repo, dest):
    return datasets.materialize(datasets.DatasetRef(repo, "latest"), dest, layout="raw", client=client)


def test_stale_marker_next_to_recreated_folder_is_overwritten(lake, client, tmp_path):
    dest = tmp_path / "mine"
    _materialize(client, "dataset-m1", dest)
    shutil.rmtree(dest)
    dest.mkdir()
    (dest / "my_precious.txt").write_text("engineer's own file")
    with pytest.raises(DatasetError, match="not a kaos-lib dataset copy"):
        _materialize(client, "dataset-m2", dest)
    assert (dest / "my_precious.txt").read_text() == "engineer's own file" and not (dest / "b.txt").exists()


def test_a_recreated_folder_is_not_read_as_a_copy(lake, client, tmp_path):
    dest = tmp_path / "mine"
    _materialize(client, "dataset-m1", dest)
    ref = datasets.DatasetRef("dataset-m1", "latest")
    commit = datasets.resolve(ref, client, None)
    assert local.marker_matches(dest, "dataset-m1", commit)
    shutil.rmtree(dest)
    dest.mkdir()
    (dest / "a.txt").write_bytes(b"A")                  # even with a file of the same name and size
    (dest / "other.txt").write_bytes(b"x")
    assert not local.marker_matches(dest, "dataset-m1", commit)
    with pytest.raises(DatasetError):
        _materialize(client, "dataset-m1", dest)


def test_a_marker_next_to_a_folder_that_changed_is_not_a_marker(lake, client, tmp_path):
    dest = tmp_path / "mine"
    _materialize(client, "dataset-m1", dest)
    (dest / "extra.txt").write_text("added later")
    assert not local._marker_belongs(dest)


def test_staged_marker_of_kaos_lib_is_bound_to_its_folder_but_the_platform_s_is_not(tmp_path, monkeypatch):
    root = tmp_path / "staged"
    mine = root / "clean"
    mine.mkdir(parents=True)
    (mine / "f").write_bytes(b"1")
    monkeypatch.setenv(local.STAGED_ENV, str(root))
    record = {"repo": "dataset-x", "commit": "c1", "full": True}
    local.staged_marker(mine).write_text(json.dumps({**record, **local.stamp(mine)}))      # a local run's
    assert local.staged_dir("c1", repo="dataset-x") == mine
    shutil.rmtree(mine)
    mine.mkdir()
    (mine / "g").write_bytes(b"22")                       # re-created by the engineer
    assert local.staged_dir("c1", repo="dataset-x") is None
    local.staged_marker(mine).write_text(json.dumps(record))                              # the platform's: no stamp
    assert local.staged_dir("c1", repo="dataset-x") == mine
