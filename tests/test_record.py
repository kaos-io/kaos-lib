"""record: what a step handed on, kept as kaos-runs/<run>/<step>.json of outputs-<app> (PRD kaos#1911, re-running)."""
import json

import pytest

from kaos_lib import record
from kaos_lib.errors import DatasetError, NotFoundError

RESULT = '{"version":1,"status":"ok","values":{"accuracy":0.93},"reads":[],"writes":[]}'


def main_commits(fake):
    return [e for e in fake.repos["outputs-myapp"]["commit_log"] if e[0] == "main"]


def test_the_record_of_a_step_is_a_file_named_after_run_and_step():
    assert record.path("myapp-x7k2p", "train") == "kaos-runs/myapp-x7k2p/train.json"
    assert record.path("myapp-x7k2p", record.PLAN) == "kaos-runs/myapp-x7k2p/plan.json"
    assert record.branch("myapp-x7k2p", "train") == "run-myapp-x7k2p-train-record"


@pytest.mark.parametrize("run, name", [("../x", "train"), ("a/b", "train"), ("run", "../train"), ("", "train"), ("run", "")])
def test_a_name_that_could_leave_the_folder_is_refused(run, name):
    with pytest.raises(DatasetError):
        record.path(run, name)


def test_a_record_is_written_to_main_in_one_commit_and_read_back(fake, client):
    commit = record.write(client, "myapp", "run-7", "train", RESULT)
    assert fake.head("outputs-myapp") == commit and [c for _, c, *_ in main_commits(fake)] == [commit]
    assert set(fake.tree("outputs-myapp", commit)) == {"kaos-runs/run-7/train.json"}
    assert record.read(client, "myapp", "run-7", "train") == json.loads(RESULT)
    assert set(fake.repos["outputs-myapp"]["branches"]) == {"main"}, "the step's branch is gone"


def test_every_step_writes_its_own_branch_and_no_step_changes_another_steps_file(fake, client):
    record.write(client, "myapp", "run-7", "prepare", '{"version":1,"status":"ok","values":{"n":1},"reads":[],"writes":[]}')
    record.write(client, "myapp", "run-7", "train", RESULT)
    assert fake.writes and {branch for _, _, branch, _ in fake.writes} == {"run-run-7-prepare-record", "run-run-7-train-record"}
    assert set(fake.tree("outputs-myapp", fake.head("outputs-myapp"))) == {"kaos-runs/run-7/prepare.json",
                                                                            "kaos-runs/run-7/train.json"}
    assert record.read(client, "myapp", "run-7", "prepare")["values"] == {"n": 1}


def test_a_retry_of_a_step_replaces_its_record_and_leaves_one_file(fake, client):
    record.write(client, "myapp", "run-7", "train", RESULT)
    again = RESULT.replace("0.93", "0.95")
    record.write(client, "myapp", "run-7", "train", again)
    assert record.read(client, "myapp", "run-7", "train")["values"] == {"accuracy": 0.95}
    assert set(fake.tree("outputs-myapp", fake.head("outputs-myapp"))) == {"kaos-runs/run-7/train.json"}


def test_a_run_that_has_no_record_reads_as_none(client):
    assert record.read(client, "myapp", "run-7", "train") is None


def test_the_records_of_two_runs_do_not_meet(fake, client):
    record.write(client, "myapp", "run-7", "train", RESULT)
    assert record.read(client, "myapp", "run-8", "train") is None


def test_an_app_with_no_outputs_repository_says_so(client):
    with pytest.raises(DatasetError, match="outputs-nothere does not exist"):
        record.write(client, "nothere", "run-7", "train", RESULT)
    with pytest.raises(NotFoundError):
        client.branch_commit("outputs-nothere", "main")


def test_a_failing_write_leaves_no_branch_behind(fake, client, monkeypatch):
    monkeypatch.setattr(client, "merge", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the lake went away")))
    with pytest.raises(RuntimeError, match="went away"):
        record.write(client, "myapp", "run-7", "train", RESULT)
    assert set(fake.repos["outputs-myapp"]["branches"]) == {"main"}
