"""kaos_lib.lock: reads recorded through datasets, MLflow tags and data.lock.json, load, replay, $KAOS_LIB_LOCK."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from conftest import write_dataset
from fake_lakefs import FakeLakeFS
from fake_mlflow import FakeMlflowClient
from kaos_lib import cli, datasets, lock
from kaos_lib.errors import LockError

OWN_BASE = "http://b-lakefs.ml-b.svc.cluster.local"
A_ENDPOINT = "http://a-lakefs.ml-a.svc.cluster.local"
PEERS = {"project": "b", "peers": [{"project": "a", "endpoint": A_ENDPOINT, "url": "https://lakefs-a.example"}]}
YOLO = {"kaos.kind": "dataset", "kaos.template": "ultralytics"}


def tree_of(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def advance(fake, repo, files):
    """A new commit on main of ``repo`` holding ``files``; returns its id."""
    cid, _ = fake._new_commit(repo, files)
    fake.repos[repo]["branches"]["main"]["commit"] = cid
    return cid


@pytest.fixture
def lakes(mesh, monkeypatch, zitadel_env, tmp_path):
    """Project b (own: dataset-default, dataset-raw) and project a (shares dataset-x), as a pipeline step of b."""
    own, owner = FakeLakeFS(OWN_BASE), FakeLakeFS(A_ENDPOINT)
    own.kaos["/kaos/v1/peers"] = (200, PEERS)
    own.add_repo("dataset-default", metadata=YOLO, files=tree_of(write_dataset(tmp_path / "d")))
    own.add_repo("dataset-raw", files={"a.txt": b"one"})
    owner.add_repo("dataset-x", metadata=YOLO, files=tree_of(write_dataset(tmp_path / "x", images=("s",))))
    own.tag("dataset-default", "v1")
    owner.tag("dataset-x", "v1")
    mesh.update({OWN_BASE: own, A_ENDPOINT: owner})
    monkeypatch.setenv("LAKEFS_ENDPOINT", OWN_BASE)
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    return own, owner


def reads():
    return [r.as_dict() for r in lock.current().reads]


# ------------------------------------------------------------------ recording
def test_resolve_and_materialize_record_every_read_including_shared(lakes):
    own, owner = lakes
    v1 = datasets.resolve(datasets.DatasetRef.parse("dataset-default@v1"))
    datasets.materialize(datasets.DatasetRef.parse("dataset-raw@latest"))
    datasets.materialize(datasets.DatasetRef.parse("a/dataset-x@v1"))
    assert reads() == [
        {"repo": "dataset-default", "owner": None, "ref": "v1", "commit": v1},
        {"repo": "dataset-raw", "owner": None, "ref": "latest", "commit": own.head("dataset-raw")},
        {"repo": "dataset-x", "owner": "a", "ref": "v1", "commit": owner.head("dataset-x")},
    ]


def test_a_repeated_read_is_recorded_once_and_pinned_reads_count(lakes):
    ref = datasets.DatasetRef.parse("dataset-default@v1")
    first = datasets.resolve(ref)
    datasets.resolve(ref)
    datasets.resolve(ref.with_commit("c9999pinned"))
    assert [(r["ref"], r["commit"]) for r in reads()] == [("v1", first), ("v1", "c9999pinned")]


def test_own_project_owner_is_recorded_as_the_own_project(lakes):
    datasets.materialize(datasets.DatasetRef("dataset-raw", "latest", owner="b"))   # b is this project (peers)
    assert reads()[0]["owner"] is None


def test_record_adds_a_read_that_bypassed_kaos_lib():
    lock.record("dataset-default", "v2", "c0042", None)
    lock.record("dataset-x", "v1", "c0007", "a")
    assert reads() == [{"repo": "dataset-default", "owner": None, "ref": "v2", "commit": "c0042"},
                       {"repo": "dataset-x", "owner": "a", "ref": "v1", "commit": "c0007"}]


# ------------------------------------------------------------------ write
def test_write_sets_tags_and_the_artifact():
    lock.record("dataset-default", "v2", "c0042")
    lock.record("dataset-raw", "latest", "c0100")
    lock.record("dataset-x", "v1", "c0007", "a")
    client = FakeMlflowClient()
    lock.write("run-1", client)
    assert client.tags["run-1"] == {
        "kaos_lib.data.dataset-default.commit": "c0042",
        "kaos_lib.data.dataset-raw.commit": "c0100",
        "kaos_lib.data.dataset-x.commit": "c0007",
        "kaos_lib.data.dataset-x.owner": "a",
    }
    assert json.loads(client.artifacts["run-1"]["data.lock.json"]) == {"version": 1, "reads": [
        {"repo": "dataset-default", "owner": None, "ref": "v2", "commit": "c0042"},
        {"repo": "dataset-raw", "owner": None, "ref": "latest", "commit": "c0100"},
        {"repo": "dataset-x", "owner": "a", "ref": "v1", "commit": "c0007"}]}


def test_two_commits_of_one_repository_are_both_tagged():
    lock.record("dataset-default", "v1", "c0001")
    lock.record("dataset-default", "v2", "c0002")
    client = FakeMlflowClient()
    lock.write("run-1", client)
    assert client.tags["run-1"] == {"kaos_lib.data.dataset-default.commit": "c0001,c0002"}


def test_write_merges_with_the_lock_already_on_the_run():
    client = FakeMlflowClient()
    lock.DataLock([lock.Read("dataset-default", "v1", "c0001")]).write("run-1", client)   # an earlier step
    lock.record("dataset-raw", "main", "c0050")
    merged = lock.write("run-1", client)
    assert [r.repo for r in merged.reads] == ["dataset-default", "dataset-raw"]
    assert len(json.loads(client.artifacts["run-1"]["data.lock.json"])["reads"]) == 2
    assert set(client.tags["run-1"]) == {"kaos_lib.data.dataset-default.commit", "kaos_lib.data.dataset-raw.commit"}


def test_write_finds_the_run_from_mlflow_run_id(monkeypatch):
    monkeypatch.setenv("MLFLOW_RUN_ID", "env-run")
    client = FakeMlflowClient()
    lock.write(client=client)
    assert "data.lock.json" in client.artifacts["env-run"]


def test_write_finds_the_active_run(monkeypatch):
    import types
    module = types.SimpleNamespace(active_run=lambda: types.SimpleNamespace(info=types.SimpleNamespace(run_id="act")))
    monkeypatch.setitem(sys.modules, "mlflow", module)
    client = FakeMlflowClient()
    lock.write(client=client)
    assert "act" in client.artifacts


def test_write_without_a_run_says_how_to_name_one(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlflow", None)
    with pytest.raises(LockError, match="no MLflow run.*run_id=.*MLFLOW_RUN_ID"):
        lock.write(client=FakeMlflowClient())


def test_mlflow_failure_is_one_clear_error():
    client = FakeMlflowClient()
    client.fail = ConnectionError("mlflow down")
    with pytest.raises(LockError, match="cannot read the data lock of MLflow run run-1 \\(ConnectionError: mlflow down\\)"):
        lock.write("run-1", client)


# ------------------------------------------------------------------ load
def test_load_round_trip():
    lock.record("dataset-default", "v2", "c0042")
    lock.record("dataset-x", "v1", "c0007", "a")
    client = FakeMlflowClient()
    lock.write("run-1", client)
    loaded = lock.load("run-1", client)
    assert loaded.reads == lock.current().reads
    assert loaded.to_dict() == lock.current().to_dict()


def test_load_of_a_run_without_a_lock():
    with pytest.raises(LockError, match="MLflow run run-9 has no data.lock.json"):
        lock.load("run-9", FakeMlflowClient())


def test_load_of_a_malformed_artifact_names_the_run():
    client = FakeMlflowClient()
    client.artifacts["run-1"] = {"data.lock.json": "{not json"}
    with pytest.raises(LockError, match="data.lock.json of MLflow run run-1 is not JSON"):
        lock.load("run-1", client)


# ------------------------------------------------------------------ replay
def test_replay_pins_the_locked_commits(lakes):
    own, owner = lakes
    first = own.head("dataset-raw")
    shared_first = owner.head("dataset-x")
    locked = lock.DataLock([lock.Read("dataset-raw", "latest", first),
                            lock.Read("dataset-x", "v1", shared_first, "a")])
    advance(own, "dataset-raw", {"a.txt": b"two"})
    owner.tag("dataset-x", "v1", ref=advance(owner, "dataset-x", owner.tree("dataset-x", "main")))
    lock.DataLock.replay(locked)
    path = datasets.materialize(datasets.DatasetRef.parse("dataset-raw@latest"))
    assert (path / "a.txt").read_bytes() == b"one"
    assert datasets.resolve(datasets.DatasetRef.parse("a/dataset-x@v1")) == shared_first
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-default@v1")) == own.head("dataset-default")  # not locked
    assert [r["commit"] for r in reads()][:2] == [first, shared_first]   # replayed reads are recorded too


def test_replay_asks_lakefs_nothing_for_the_commit(lakes):
    own, _ = lakes
    lock.DataLock.replay({"version": 1, "reads": [{"repo": "dataset-raw", "owner": None, "ref": "latest",
                                                   "commit": "c7777locked"}]})
    own.calls.clear()
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-raw@latest")) == "c7777locked"
    assert own.calls == []


def test_replay_matches_a_single_locked_commit_of_the_repository_under_another_ref():
    locked = lock.DataLock([lock.Read("dataset-raw", "latest", "c1")])
    assert locked.pinned("dataset-raw", "main") == "c1"
    two = lock.DataLock([lock.Read("dataset-raw", "v1", "c1"), lock.Read("dataset-raw", "v2", "c2")])
    assert two.pinned("dataset-raw", "v2") == "c2"
    assert two.pinned("dataset-raw", "main") is None              # ambiguous: resolved live
    assert locked.pinned("dataset-raw", "latest", owner="a") is None   # another project's repository


def test_replay_none_stops_replaying(lakes):
    own, _ = lakes
    lock.DataLock.replay({"version": 1, "reads": [{"repo": "dataset-raw", "ref": "latest", "commit": "c7777"}]})
    lock.DataLock.replay(None)
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-raw@latest")) == own.head("dataset-raw")


def test_kaos_lib_lock_env_is_honoured(lakes, monkeypatch):
    own, _ = lakes
    first = own.head("dataset-raw")
    advance(own, "dataset-raw", {"a.txt": b"two"})
    monkeypatch.setenv("KAOS_LIB_LOCK", lock.DataLock([lock.Read("dataset-raw", "latest", first)]).to_json())
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-raw@latest")) == first
    monkeypatch.setenv("KAOS_LIB_LOCK", json.dumps({"version": 1, "reads": []}))   # a changed value is read again
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-raw@latest")) == own.head("dataset-raw")


@pytest.mark.parametrize("raw,fragment", [
    ("{oops", r"\$KAOS_LIB_LOCK is not JSON"),
    ("[1, 2]", r"\$KAOS_LIB_LOCK must be a JSON object"),
    ('{"version": 2, "reads": []}', r"has version 2; this kaos-lib reads version 1 .*upgrade"),
    ('{"version": 1}', "has no reads list"),
    ('{"version": 1, "reads": ["x"]}', r"reads\[0\] is not an object"),
    ('{"version": 1, "reads": [{"repo": "dataset-x", "ref": "v1"}]}', r"reads\[0\] needs a non-empty string commit"),
    ('{"version": 1, "reads": [{"repo": "", "ref": "", "commit": "c"}]}', r"needs a non-empty string repo, ref"),
    ('{"version": 1, "reads": [{"repo": "r", "ref": "v1", "commit": "c", "owner": 3}]}', r"owner must be a project"),
])
def test_malformed_lock_env_is_a_clear_error(lakes, monkeypatch, raw, fragment):
    monkeypatch.setenv("KAOS_LIB_LOCK", raw)
    with pytest.raises(LockError, match=fragment):
        datasets.resolve(datasets.DatasetRef.parse("dataset-raw@latest"))


def test_malformed_lock_is_reported_by_the_cli_in_one_line(lakes, monkeypatch, capsys):
    monkeypatch.setenv("KAOS_LIB_LOCK", "{oops")
    assert cli.main(["dataset", "pull", "dataset-raw@latest"]) == cli.EXIT_USER_ERROR
    err = capsys.readouterr().err
    assert err.startswith("ERROR: $KAOS_LIB_LOCK is not JSON") and "Traceback" not in err


# ------------------------------------------------------------------ kaos-cli run --lock
@pytest.fixture
def mlflow_with_lock(monkeypatch):
    client = FakeMlflowClient()
    lock.DataLock([lock.Read("dataset-raw", "latest", "c0001locked"),
                   lock.Read("dataset-x", "v1", "c0002locked", "a")]).write("run-1", client)
    from kaos_lib import mlflow as kmlflow
    monkeypatch.setattr(kmlflow, "mlflow", lambda *a, **k: client)
    return client


def child_env():
    import kaos_lib
    return str(pathlib.Path(kaos_lib.__file__).parent.parent)


def test_run_lock_exports_the_lock_and_the_child_replays_it(mlflow_with_lock, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PYTHONPATH", child_env())
    out = tmp_path / "child.json"
    code = ("import json, sys; from kaos_lib import lock; "
            "json.dump([lock.pinned('dataset-raw', 'latest'), lock.pinned('dataset-x', 'v1', 'a'), "
            "lock.pinned('dataset-default', 'v1')], open(sys.argv[1], 'w'))")
    assert cli.main(["run", "--lock", "run-1", "--", sys.executable, "-c", code, str(out)]) == 0
    assert json.loads(out.read_text()) == ["c0001locked", "c0002locked", None]
    err = capsys.readouterr().err
    assert "dataset-raw@latest -> c0001locked" in err and "a/dataset-x@v1 -> c0002locked" in err
    assert "KAOS_LIB_LOCK" not in os.environ   # only the child gets it


def test_run_lock_returns_the_command_exit_code(mlflow_with_lock):
    assert cli.main(["run", "--lock", "run-1", "--", sys.executable, "-c", "raise SystemExit(7)"]) == 7


def test_run_lock_needs_a_command(mlflow_with_lock, capsys):
    assert cli.main(["run", "--lock", "run-1"]) == cli.EXIT_USER_ERROR
    assert "nothing to run" in capsys.readouterr().err


def test_run_lock_of_a_run_without_a_lock(mlflow_with_lock, capsys):
    assert cli.main(["run", "--lock", "run-404", "--", "true"]) == cli.EXIT_USER_ERROR
    assert "MLflow run run-404 has no data.lock.json" in capsys.readouterr().err


def test_run_lock_with_a_missing_program(mlflow_with_lock, capsys):
    assert cli.main(["run", "--lock", "run-1", "--", "/no/such/program"]) == cli.EXIT_USER_ERROR
    assert "cannot run '/no/such/program'" in capsys.readouterr().err


# ------------------------------------------------------------------ real MLflow (mlflow-skinny installed)
def test_real_mlflow_round_trip(tmp_path, monkeypatch):
    mlflow = pytest.importorskip("mlflow")
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    mlflow.set_tracking_uri(f"file://{tmp_path / 'mlruns'}")
    from mlflow.tracking import MlflowClient
    client = MlflowClient()
    run = client.create_run(client.create_experiment("lock"))
    lock.record("dataset-default", "v2", "c0042")
    lock.record("dataset-x", "v1", "c0007", "a")
    lock.write(run.info.run_id, client)
    tags = client.get_run(run.info.run_id).data.tags
    assert tags["kaos_lib.data.dataset-default.commit"] == "c0042"
    assert tags["kaos_lib.data.dataset-x.owner"] == "a"
    assert lock.load(run.info.run_id, client).reads == lock.current().reads
