"""kaos_lib.checkpoint, the generic API: dir(), save/load of your own state, progress(), stop and exit (D-76)."""
import json
import os
import signal

import pytest

from kaos_lib import checkpoint


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    checkpoint._state["requested"] = False
    checkpoint._state.pop("polled", None)
    checkpoint._reg = None
    checkpoint._temp_dir = None
    monkeypatch.delenv(checkpoint.CHECKPOINT_DIR_ENV, raising=False)
    monkeypatch.delenv(checkpoint.RESUME_PATH_ENV, raising=False)
    monkeypatch.setenv(checkpoint.OUTPUT_DIR_ENV, str(tmp_path / "output"))
    yield
    checkpoint._state["requested"] = False
    checkpoint._state.pop("polled", None)
    checkpoint._temp_dir = None


def test_dir_is_the_platform_folder_when_set_and_created_if_missing(tmp_path, monkeypatch):
    target = tmp_path / "plat" / "ckpt"
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(target))
    assert checkpoint.dir() == target and target.is_dir()


def test_dir_is_a_fresh_temporary_folder_off_the_platform_and_stable_within_a_process():
    first = checkpoint.dir()
    assert first.is_dir() and first.name.startswith("kaos-checkpoint-")
    assert checkpoint.dir() == first
    checkpoint.save({"a": 1})
    checkpoint._temp_dir = None                       # a new process: nothing is restored locally
    assert checkpoint.load(default="fresh") == "fresh"


@pytest.mark.parametrize("value,ext", [
    ({"epoch": 3, "lr": 0.1}, ".json"), ([1, 2, 3], ".json"), (7, ".json"), ("text", ".json"),
    (b"\x00raw bytes", ".bin"), ({1, 2, 3}, ".pkl"), ({"t": (1, 2)}, ".json"),
])
def test_save_then_load_round_trips_json_bytes_and_pickled_objects(tmp_path, monkeypatch, value, ext):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    path = checkpoint.save(value)
    assert path.name == "state" + ext
    expected = {"t": [1, 2]} if value == {"t": (1, 2)} else value     # JSON turns a tuple into a list
    assert checkpoint.load() == expected


def test_a_named_state_is_separate_and_a_missing_one_gives_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    checkpoint.save({"epoch": 2}, name="trainer")
    checkpoint.save(b"weights", name="model")
    assert checkpoint.load("trainer") == {"epoch": 2} and checkpoint.load("model") == b"weights"
    assert checkpoint.load("nothing", default=0) == 0


def test_a_newer_save_of_another_kind_replaces_the_old_file(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    checkpoint.save({"a": 1})
    checkpoint.save({1, 2})
    assert sorted(p.name for p in (tmp_path / "f").iterdir()) == ["state.pkl"]
    assert checkpoint.load() == {1, 2}


def test_save_is_atomic_a_failing_write_leaves_the_previous_state(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    checkpoint.save({"epoch": 1})

    class Unpicklable:
        def __reduce__(self):
            raise RuntimeError("cannot pickle")

    with pytest.raises(RuntimeError):
        checkpoint.save(Unpicklable())
    assert checkpoint.load() == {"epoch": 1}
    assert [p.name for p in (tmp_path / "f").iterdir()] == ["state.json"], "no temporary file is left"


def test_a_corrupt_file_is_skipped_with_a_message_not_trusted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    checkpoint.dir().joinpath("state.json").write_text("{torn")
    assert checkpoint.load(default="d") == "d" and "cannot read" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["", "a/b", ".hidden"])
def test_names_must_be_plain_file_names(tmp_path, monkeypatch, bad):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    with pytest.raises(ValueError):
        checkpoint.save({"a": 1}, name=bad)


def test_progress_writes_values_for_the_platform(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    checkpoint.progress({"epoch": 3, "step": 1200})
    got = json.loads((tmp_path / "f" / checkpoint.PROGRESS_FILE).read_text())
    assert got == {"values": [3, 1200], "text": "epoch=3 step=1200"}
    checkpoint.progress(9)
    assert json.loads((tmp_path / "f" / checkpoint.PROGRESS_FILE).read_text())["values"] == [9]
    with pytest.raises(ValueError):
        checkpoint.progress(None)


def test_a_loop_saves_and_exits_for_restart_on_a_stop_request(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    signal.signal(checkpoint.STOP_SIGNAL, checkpoint._on_stop_signal)
    state = checkpoint.load(default={"epoch": 0})
    with pytest.raises(SystemExit) as ended:
        for epoch in range(state["epoch"], 10):
            if epoch == 4:
                os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
            if checkpoint.stop_requested():
                checkpoint.save({"epoch": epoch})
                checkpoint.exit_for_restart()
    assert ended.value.code == 85
    assert checkpoint.load() == {"epoch": 4}                     # the next run starts where this one stopped


def test_save_with_a_function_still_means_the_older_save_and_end_call(tmp_path):
    assert checkpoint.save(lambda path: (path / "f").write_text("x")) is False      # no stop requested: nothing
    assert not (tmp_path / "output").exists()


def test_sigterm_counts_as_a_stop_for_a_step_that_saves_through_the_hooks(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path / "f"))
    checkpoint.register(save=lambda p: (p / "x").write_text("1"), load=lambda p: None)
    checkpoint._on_terminate(signal.SIGTERM, None)
    assert checkpoint.stop_requested()


def test_sigterm_is_a_stop_request_once_a_loop_looks_for_it_and_the_default_before(tmp_path, monkeypatch):
    kills = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append(sig))
    checkpoint._state.pop("polled", None)
    checkpoint._on_terminate(signal.SIGTERM, None)
    assert kills == [signal.SIGTERM], "nobody polls: the process ends as it would without the library"
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    assert checkpoint.stop_requested() is False
    checkpoint._on_terminate(signal.SIGTERM, None)
    assert checkpoint.stop_requested() is True and kills == [signal.SIGTERM]
