"""The dataset writer: stage from the last version, mirror, check, seal, verify, keep, promote on an expected head."""
import json
import pathlib

import pytest

from kaos_lib import dataset_writer, lock, step, transfer
from kaos_lib.dataset_writer import keep_tag, run_branch, write_version
from kaos_lib.errors import AuthError, LakeFSError, StepError

REPO = "dataset-clean"
FIXTURES = pathlib.Path(__file__).with_name("contract_fixtures")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(transfer, "RETRY_PAUSE_S", 0)


@pytest.fixture
def lake(fake):
    fake.add_repo(REPO, metadata={"kaos.kind": "dataset"})
    return fake


def folder(tmp_path, files, name="out"):
    root = tmp_path / name
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    return root


def write(client, root, run="run-1", promote=False, **kw):
    return write_version(client, REPO, root, name="clean", run=run, step="prepare", app="myapp", promote=promote,
                         echo=lambda *a, **k: None, **kw)


def uploads(fake):
    return sorted(path for kind, _, _, path in fake.writes if kind == "POST")


ONE = {"a/1.bin": b"one", "a/2.bin": b"two", "b/3.bin": b"three"}


def test_a_promoting_run_makes_main_hold_exactly_the_folder(lake, client, tmp_path):
    first = lake.head(REPO)
    version = write(client, folder(tmp_path, ONE), promote=True)
    assert version == lake.head(REPO) != first
    assert lake.tree(REPO, version) == ONE
    assert set(lake.repos[REPO]["branches"]) == {"main"}                    # the run branch is gone
    assert all(branch == "run-run-1-prepare" for _, _, branch, _ in lake.writes)   # nothing was written to main
    sealed = lake.repos[REPO]["tags"]["k-run-1-prepare"]
    assert lake.tree(REPO, sealed) == ONE and sealed != version              # the sealed commit is kept too


def test_a_run_that_does_not_promote_seals_a_version_and_leaves_latest_alone(lake, client, tmp_path):
    first = lake.head(REPO)
    version = write(client, folder(tmp_path, ONE))
    assert lake.head(REPO) == first and lake.tree(REPO, "main") == {}
    assert lake.repos[REPO]["tags"] == {"k-run-1-prepare": version} and lake.tree(REPO, version) == ONE
    assert set(lake.repos[REPO]["branches"]) == {"main"}


def test_the_commit_says_which_run_made_it_and_what_it_read(lake, client, tmp_path):
    version = write(client, folder(tmp_path, ONE), metadata={"kaos.read.raw": "c1"})
    message, meta = lake.commit_meta(REPO, version)
    assert message == "clean: myapp run-1 prepare"
    assert meta == {"kaos.run": "run-1", "kaos.app": "myapp", "kaos.step": "prepare", "kaos.read.raw": "c1",
                    "kaos.manifest": dataset_writer.digest(dataset_writer.manifest(tmp_path / "out"))}


def test_a_second_run_with_one_changed_file_uploads_one_file(lake, client, tmp_path):
    write(client, folder(tmp_path, ONE), promote=True)
    lake.writes.clear()
    changed = {**ONE, "a/2.bin": b"two, changed"}
    version = write(client, folder(tmp_path, changed, "second"), run="run-2", promote=True)
    assert uploads(lake) == ["a/2.bin"]
    assert lake.tree(REPO, version) == changed


def test_a_file_that_is_gone_from_the_folder_is_gone_from_the_version(lake, client, tmp_path):
    write(client, folder(tmp_path, ONE), promote=True)
    lake.writes.clear()
    fewer = {k: v for k, v in ONE.items() if k != "b/3.bin"}
    version = write(client, folder(tmp_path, fewer, "second"), run="run-2", promote=True)
    assert lake.writes == [("DELETE", REPO, "run-run-2-prepare", "b/3.bin")]
    assert lake.tree(REPO, version) == fewer


def test_the_same_content_makes_no_new_version(lake, client, tmp_path):
    first = write(client, folder(tmp_path, ONE), promote=True)
    lake.writes.clear()
    again = write(client, folder(tmp_path, ONE, "same"), run="run-2", promote=True)
    assert again == first == lake.head(REPO) and lake.writes == []
    assert "k-run-2-prepare" not in lake.repos[REPO]["tags"] and set(lake.repos[REPO]["branches"]) == {"main"}


def test_two_promoting_runs_the_second_is_refused_restages_and_main_is_never_a_mix(lake, client, tmp_path):
    """Run B staged from the first head; run A promotes before B merges. B's merge is refused (412), B starts
    again from A's version and promotes: main holds B's files only."""
    a = folder(tmp_path, {"only-a.bin": b"a", "shared.bin": b"from a"}, "a")
    b = folder(tmp_path, {"only-b.bin": b"b", "shared.bin": b"from b"}, "b")
    real, seen = client.merge, []

    def merge(repo, source, destination, message, metadata=None, tolerate_empty=False, expected_head=None):
        if not seen:                                  # B is about to merge: A gets in first
            seen.append("a")
            write(lake.client(), a, run="run-a", promote=True)
        try:
            return real(repo, source, destination, message, metadata, tolerate_empty, expected_head)
        except LakeFSError as exc:
            seen.append(exc.status)
            raise

    client.merge = merge
    lines = []
    version = write_version(client, REPO, b, name="clean", run="run-b", step="prepare", app="myapp", promote=True,
                            echo=lambda text, **k: lines.append(text))
    assert seen == ["a", 412]
    assert lake.tree(REPO, "main") == {"only-b.bin": b"b", "shared.bin": b"from b"} and version == lake.head(REPO)
    assert any("changed while this step was writing it; starting again from its new version (attempt 2 of 3)" in t
               for t in lines)
    assert lake.tree(REPO, lake.repos[REPO]["tags"]["k-run-a-prepare"]) == {"only-a.bin": b"a", "shared.bin": b"from a"}


def test_a_dataset_that_keeps_moving_fails_after_three_tries_and_the_sealed_version_is_kept(lake, client, tmp_path):
    client.merge = lambda *a, **k: (_ for _ in ()).throw(LakeFSError("main moved", 412))
    with pytest.raises(StepError, match=r"output 'clean': dataset-clean changed 3 times while this step was "
                                        r"promoting it. Another run is writing the same dataset. The sealed "
                                        r"version is kept as k-run-1-prepare \("):
        write(client, folder(tmp_path, ONE), promote=True)
    assert lake.tree(REPO, "main") == {} and set(lake.repos[REPO]["branches"]) == {"main"}
    assert lake.tree(REPO, lake.repos[REPO]["tags"]["k-run-1-prepare"]) == ONE


def test_a_merge_always_carries_the_head_it_expects(lake, client, tmp_path):
    first, bodies = lake.head(REPO), []
    real = lake._merge
    lake._merge = lambda r, source, dest, body: bodies.append(body) or real(r, source, dest, body)
    write(client, folder(tmp_path, ONE), promote=True)
    assert [b["expected_head"] for b in bodies] == [first]


def test_a_step_killed_while_uploading_leaves_no_version_and_the_retry_seals_once(lake, client, tmp_path):
    first, real, count = lake.head(REPO), client.upload_object, []

    def dies(repo, branch, path, local):
        count.append(path)
        if len(count) == 2:
            raise KeyboardInterrupt("killed")
        return real(repo, branch, path, local)

    client.upload_object, client.concurrency = dies, 1
    with pytest.raises(KeyboardInterrupt):
        write(client, folder(tmp_path, ONE), promote=True)
    assert lake.head(REPO) == first and lake.repos[REPO]["tags"] == {}          # no version, nothing kept
    assert lake.repos[REPO].get("commit_log", []) == []
    client.upload_object = real
    version = write(client, folder(tmp_path, ONE), promote=True)
    assert lake.tree(REPO, version) == ONE
    assert [c for branch, c, *_ in lake.repos[REPO]["commit_log"] if branch == "main"] == [version]   # promoted once
    assert list(lake.repos[REPO]["tags"]) == ["k-run-1-prepare"]                                        # sealed once


def test_an_upload_that_fails_in_passing_is_tried_again(lake, client, tmp_path):
    lake.upload_answers = [503, 502, 500]
    client.concurrency = 1
    version = write(client, folder(tmp_path, {"only.bin": b"x"}), promote=True)
    assert lake.tree(REPO, version) == {"only.bin": b"x"} and lake.upload_answers == []


def test_an_upload_that_keeps_failing_fails_the_step_and_seals_nothing(lake, client, tmp_path):
    lake.upload_answers = [503] * 4
    with pytest.raises(LakeFSError, match="HTTP 503"):
        write(client, folder(tmp_path, {"only.bin": b"x"}), promote=True)
    assert lake.repos[REPO].get("commit_log", []) == [] and lake.repos[REPO]["tags"] == {}


def test_a_refused_upload_is_not_tried_again(lake, client, tmp_path):
    lake.upload_answers = [403, 201]
    with pytest.raises(AuthError):
        write(client, folder(tmp_path, {"only.bin": b"x"}))
    assert lake.upload_answers == [201]


def test_a_branch_that_does_not_hold_what_the_step_wrote_is_not_sealed(lake, client, tmp_path):
    real = client.upload_object
    client.upload_object = lambda repo, branch, path, local: None if path == "a/2.bin" else real(repo, branch, path, local)
    with pytest.raises(StepError, match=r"output 'clean': 1 files differ between what the step wrote and what "
                                        r"lakeFS holds \(first: a/2.bin\). Nothing was sealed."):
        write(client, folder(tmp_path, ONE), promote=True)
    assert lake.repos[REPO].get("commit_log", []) == [] and lake.tree(REPO, "main") == {}


def test_a_sealed_version_that_is_not_what_the_step_wrote_is_not_promoted(lake, client, tmp_path):
    real = client.list_objects

    def listing(repo, ref, prefix=""):
        for o in real(repo, ref, prefix):
            yield dict(o, checksum="0" * 32) if ref not in ("main", "run-run-1-prepare") and o["path"] == "b/3.bin" else o

    client.list_objects = listing
    with pytest.raises(StepError, match=r"is not what the step wrote \(1 files differ, first: b/3.bin\). "
                                        r"It was not promoted."):
        write(client, folder(tmp_path, ONE), promote=True)
    assert lake.tree(REPO, "main") == {}


def test_a_dataset_the_platform_has_not_created_yet(client, tmp_path):
    with pytest.raises(StepError, match="the dataset dataset-ghost does not exist. The platform creates a dataset "
                                        "when a step declares it"):
        write_version(client, "dataset-ghost", folder(tmp_path, ONE), name="ghost", run="r", step="s", app="a")


def test_a_second_attempt_of_a_run_that_sealed_other_content_gets_its_own_tag(lake, client, tmp_path):
    one = write(client, folder(tmp_path, ONE))
    two = write(client, folder(tmp_path, {"other.bin": b"o"}, "second"))
    again = write(client, folder(tmp_path, {"other.bin": b"o"}, "third"))
    assert lake.repos[REPO]["tags"] == {"k-run-1-prepare": one, "k-run-1-prepare-2": two, "k-run-1-prepare-3": again}
    assert lake.tree(REPO, again) == {"other.bin": b"o"}


def test_names_of_the_branch_and_the_tag():
    assert run_branch("run 7/x", "prep.data") == "run-run-7-x-prep-data"
    assert keep_tag("hera-demo-x7k2p", "prepare") == "k-hera-demo-x7k2p-prepare"


# ----------------------------------------------------------------------------------- through the step API
@pytest.fixture
def started(lake, monkeypatch, tmp_path):
    lake.add_repo("dataset-raw-images", metadata={"kaos.kind": "dataset"}, files={"x.bin": b"x"})
    lake.add_repo("dataset-embeddings", metadata={"kaos.kind": "dataset"})
    monkeypatch.setattr(step, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(step, "RESULT_FILE", str(tmp_path / "work" / "output" / "kaos-result.json"))
    monkeypatch.setattr(step, "_connect", lambda: lake.client())
    import sys
    monkeypatch.setattr(sys, "exit", sys.exit)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)

    def start(name):
        text = (FIXTURES / f"{name}.json").read_text().replace("1" * 64, lake.head("dataset-raw-images"))
        monkeypatch.setenv(step.ENV, lock.wire(json.loads(text)))
        return step.start()

    yield start
    step.stop()


@pytest.mark.parametrize("context,promoted", [("context-no-upstream", False), ("context-promote", True)])
def test_a_step_that_produces_a_dataset_seals_it_and_promotes_only_when_the_run_asks(started, lake, tmp_path,
                                                                                      context, promoted):
    first = lake.head("dataset-embeddings")
    started(context)
    step.input("raw")
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    step.result(rows=1)
    result = json.loads(pathlib.Path(step.RESULT_FILE).read_text())
    commit = result["writes"][0]["commit"]
    assert result["writes"] == [{"name": "embeddings", "type": "dataset", "repo": "dataset-embeddings",
                                 "commit": commit}]
    assert lake.tree("dataset-embeddings", commit) == {"e.npy": b"emb"}
    assert (lake.head("dataset-embeddings") == commit) is promoted
    assert (lake.head("dataset-embeddings") == first) is not promoted
    _, meta = lake.commit_meta("dataset-embeddings", commit)
    assert meta["kaos.read.raw"] == lake.head("dataset-raw-images") and meta["kaos.step"] == "prepare"


def test_the_next_step_reads_exactly_what_the_step_before_wrote(started, lake, monkeypatch):
    started("context-no-upstream")
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    step.result()
    written = json.loads(pathlib.Path(step.RESULT_FILE).read_text())
    step.stop()
    lock.reset()
    context = json.loads((FIXTURES / "context-one-upstream.json").read_text())
    context["ledger"]["reads"] = []
    context["upstream"]["prepare"] = written
    monkeypatch.setenv(step.ENV, lock.wire(context))
    step.start()
    assert (step.input("embeddings") / "e.npy").read_bytes() == b"emb"
    assert [r.as_dict() for r in lock.current().reads] == [
        {"name": "embeddings", "repo": "dataset-embeddings", "owner": None,
         "ref": written["writes"][0]["commit"], "commit": written["writes"][0]["commit"]}]


def test_an_app_that_may_not_write_the_dataset_is_told_which(started, lake):
    started("context-no-upstream")
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    lake.deny = 401
    with pytest.raises(StepError, match="this app may not write dataset-embeddings: only what the step declares"):
        step.result()
