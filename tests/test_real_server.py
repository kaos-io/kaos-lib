"""What only a real server answers: the fake has no conflicts and no branch protection.

Run with ``KAOS_LIB_TEST_LAKEFS=real`` (or ``both``); skipped otherwise, and when docker is not available.
"""
import pytest

import real_lakefs
from kaos_lib.errors import AuthError, DatasetError, LakeFSError
from kaos_lib import datasets

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


def test_a_deleted_repository_keeps_its_name_for_a_while(real, client):
    first = datasets.create_dataset("cats", "none", "", client)
    real.delete_repo(first)
    with pytest.raises(DatasetError, match="already exists"):
        datasets.create_dataset("cats", "none", "", client)
