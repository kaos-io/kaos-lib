"""What only a real server answers: the fake has no conflicts and no branch protection.

Run with ``KAOS_LIB_TEST_LAKEFS=real`` (or ``both``); skipped otherwise, and when docker is not available.
"""
import pytest

import real_lakefs
from kaos_lib import dataset_writer
from kaos_lib.errors import AuthError, LakeFSError, StepError

REPO = "outputs-myapp"


@pytest.fixture
def real(fake):
    if not isinstance(fake, real_lakefs.RealLakeFS):
        pytest.skip(f"needs a real server: set ${real_lakefs.MODE_ENV}=real")
    return fake


def _commit_on(client, branch, path, content, tmp_path):
    local = tmp_path / f"{branch}.bin"
    local.write_bytes(content)
    client.create_branch(REPO, branch, "main")
    client.upload_object(REPO, branch, path, local)
    return client.commit(REPO, branch, f"write {path}")


def test_a_second_merge_that_changes_the_same_file_is_refused(real, client, tmp_path):
    _commit_on(client, "run-a", "data/part.bin", b"from a", tmp_path)
    _commit_on(client, "run-b", "data/part.bin", b"from b", tmp_path)
    client.merge(REPO, "run-a", "main", "a")
    with pytest.raises(LakeFSError) as err:
        client.merge(REPO, "run-b", "main", "b")
    assert err.value.status == 409
    assert real.tree(REPO, "main") == {"data/part.bin": b"from a"}


def test_two_merges_of_different_files_both_land_and_main_holds_a_mix(real, client, tmp_path):
    """Why promotion needs an expected head (PRD kaos#1911 D-05): the second merge is not refused."""
    _commit_on(client, "run-a", "data/only-a.bin", b"a", tmp_path)
    _commit_on(client, "run-b", "data/only-b.bin", b"b", tmp_path)
    client.merge(REPO, "run-a", "main", "a")
    client.merge(REPO, "run-b", "main", "b")
    assert set(real.tree(REPO, "main")) == {"data/only-a.bin", "data/only-b.bin"}


def test_a_protected_branch_refuses_a_direct_write_and_accepts_a_merge(real, client, tmp_path):
    real.server.api("PUT", f"/repositories/{real.on_server(REPO)}/settings/branch_protection",
                    json=[{"pattern": "main", "blocked_actions": ["staging_write", "commit"]}])
    local = tmp_path / "f.bin"
    local.write_bytes(b"x")
    with pytest.raises(AuthError, match="protected branch"):
        client.upload_object(REPO, "main", "direct.bin", local)
    _commit_on(client, "run-a", "data/part.bin", b"a", tmp_path)
    assert client.merge(REPO, "run-a", "main", "a") == real.head(REPO)


# ---------------------------------------------------------------- kaos-lake: a dataset an app produces (D-04, D-05)
@pytest.fixture
def lake(real):
    if not real.server.is_kaos_lake:
        pytest.skip("needs kaos-lake: upstream lakeFS has no dataset rights per app and no expected-head merge")
    return real.server


def folder(tmp_path, files, name="out"):
    root = tmp_path / name
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    return root


def tree(client, repo, ref):
    return sorted(o["path"] for o in client.list_objects(repo, ref))


def write(client, repo, root, run, promote=True):
    return dataset_writer.write_version(client, repo, root, name="out", run=run, step="prepare", app="writer",
                                        promote=promote, echo=lambda *a, **k: None)


def test_an_app_seals_and_promotes_the_dataset_it_declares_and_a_second_run_uploads_one_file(lake, tmp_path):
    client = lake.wait_for_dataset("writer", "dataset-written-1")
    files = {"a/1.bin": b"one", "a/2.bin": b"two", "b/3.bin": b"three"}
    first = write(client, "dataset-written-1", folder(tmp_path, files), "run-1")
    assert first == client.branch_commit("dataset-written-1", "main") and tree(client, "dataset-written-1", first) == sorted(files)
    sent, real_upload = [], client.upload_object
    client.upload_object = lambda repo, branch, path, local: sent.append(path) or real_upload(repo, branch, path, local)
    second = write(client, "dataset-written-1", folder(tmp_path, {**files, "a/2.bin": b"two, changed"}, "second"), "run-2")
    assert sent == ["a/2.bin"] and second == client.branch_commit("dataset-written-1", "main") != first
    assert write(client, "dataset-written-1", folder(tmp_path, {**files, "a/2.bin": b"two, changed"}, "same"), "run-3") == second
    assert not client.branch_exists("dataset-written-1", "run-run-2-prepare")
    assert client.tag_commit("dataset-written-1", "k-run-2-prepare")


def test_a_run_that_does_not_promote_leaves_latest_where_it_was(lake, tmp_path):
    client = lake.wait_for_dataset("writer", "dataset-written-2")
    head = client.branch_commit("dataset-written-2", "main")
    sealed = write(client, "dataset-written-2", folder(tmp_path, {"x.bin": b"x"}), "run-1", promote=False)
    assert client.branch_commit("dataset-written-2", "main") == head != sealed
    assert tree(client, "dataset-written-2", sealed) == ["x.bin"] and client.tag_commit("dataset-written-2", "k-run-1-prepare") == sealed


def test_the_server_refuses_a_merge_without_an_expected_head_and_one_onto_a_moved_head(lake, tmp_path):
    client = lake.wait_for_dataset("writer", "dataset-written-3")
    head = client.branch_commit("dataset-written-3", "main")
    for branch, content in (("run-a", b"a"), ("run-b", b"b")):
        client.create_branch("dataset-written-3", branch, head)
        (tmp_path / branch).write_bytes(content)
        client.upload_object("dataset-written-3", branch, f"only-{branch}.bin", tmp_path / branch)
        client.commit("dataset-written-3", branch, branch)
    with pytest.raises(LakeFSError) as err:
        client.merge("dataset-written-3", "run-a", "main", "no head")
    assert err.value.status == 400
    client.merge("dataset-written-3", "run-a", "main", "a", expected_head=head)
    with pytest.raises(LakeFSError) as err:
        client.merge("dataset-written-3", "run-b", "main", "b", expected_head=head)       # the mix the fake would allow
    assert err.value.status == dataset_writer.HEAD_MOVED
    assert tree(client, "dataset-written-3", "main") == ["only-run-a.bin"]


def test_two_promoting_runs_the_second_restages_and_main_is_never_a_mix(lake, tmp_path):
    client, other = lake.wait_for_dataset("writer", "dataset-written-4"), lake.app_client("writer")
    a = folder(tmp_path, {"only-a.bin": b"a", "shared.bin": b"from a"}, "a")
    b = folder(tmp_path, {"only-b.bin": b"b", "shared.bin": b"from b"}, "b")
    real_merge, seen = client.merge, []

    def merge(*args, **kw):
        if not seen:
            seen.append("a")
            write(other, "dataset-written-4", a, "run-a")                                 # run A promotes first
        try:
            return real_merge(*args, **kw)
        except LakeFSError as exc:
            seen.append(exc.status)
            raise

    client.merge = merge
    version = write(client, "dataset-written-4", b, "run-b")
    assert seen == ["a", 412] and version == client.branch_commit("dataset-written-4", "main")
    assert tree(client, "dataset-written-4", "main") == ["only-b.bin", "shared.bin"]


def test_an_app_cannot_write_a_dataset_another_app_declares(lake, tmp_path):
    lake.wait_for_dataset("other", "dataset-others-1")
    with pytest.raises(AuthError):
        write(lake.app_client("writer"), "dataset-others-1", folder(tmp_path, {"x.bin": b"x"}), "run-1")
    assert tree(lake.app_client("other"), "dataset-others-1", "main") == []


def test_a_dataset_nobody_declared_does_not_exist_for_the_writer(lake, tmp_path):
    with pytest.raises((StepError, AuthError)):
        write(lake.app_client("writer"), "dataset-undeclared", folder(tmp_path, {"x.bin": b"x"}), "run-1")
