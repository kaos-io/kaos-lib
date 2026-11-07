"""kaos_lib.checkpoint, registered save/load: atomic versioned writes, manifest verification, progress,
periodic interval, resume (PRD-HPC-1461 D-74, D-75)."""
import json
import os
import pathlib
import signal

import pytest

from kaos_lib import checkpoint


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    checkpoint._state["requested"] = False
    checkpoint._reg = None
    clock = Clock()
    monkeypatch.setattr(checkpoint, "_clock", clock)
    monkeypatch.setenv(checkpoint.OUTPUT_DIR_ENV, str(tmp_path / "output"))
    for name in (checkpoint.RESUME_PATH_ENV, checkpoint.CHECKPOINT_DIR_ENV):
        monkeypatch.delenv(name, raising=False)
    signal.signal(checkpoint.STOP_SIGNAL, checkpoint._on_stop_signal)
    yield clock
    checkpoint._state["requested"] = False
    checkpoint._reg = None


class Model:
    """A stand-in for a client's state: one counter, saved as a file."""

    def __init__(self, epoch=0):
        self.epoch = epoch
        self.loaded = []

    def save(self, path):
        (path / "state.txt").write_text(str(self.epoch))
        return {"epoch": self.epoch, "step": self.epoch * 100}

    def load(self, path):
        self.epoch = int((path / "state.txt").read_text())
        self.loaded.append(path)


def versions(tmp_path):
    root = tmp_path / "output" / "checkpoint"
    return sorted(p.name for p in root.iterdir() if p.name.startswith("ckpt-")) if root.is_dir() else []


# ----------------------------------------------------------------------------------------------- writing

def test_a_periodic_checkpoint_has_a_manifest_with_checksums_and_progress(tmp_path, clean):
    m = Model(4)
    checkpoint.register(save=m.save, load=m.load, checkpoint_every=10)
    assert checkpoint.tick() is False
    clean.now += 601
    assert checkpoint.tick() is True
    [name] = versions(tmp_path)
    folder = tmp_path / "output" / "checkpoint" / name
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["progress"] == {"epoch": 4, "step": 400} and manifest["progress_values"] == [4, 400]
    assert manifest["progress_text"] == "epoch=4 step=400"
    assert manifest["files"]["state.txt"]["size"] == 1 and len(manifest["files"]["state.txt"]["sha256"]) == 64
    assert checkpoint.verify(folder) == (True, "")
    assert not [p for p in (tmp_path / "output" / "checkpoint").iterdir() if p.name.startswith(".")]


def test_a_failing_periodic_save_leaves_nothing_and_does_not_stop_the_run(tmp_path, clean, capsys):
    def save_state(path):
        (path / "half").write_text("x")
        raise OSError("quota")

    checkpoint.register(save=save_state, load=lambda p: None, checkpoint_every=1)
    clean.now += 61
    assert checkpoint.tick() is False
    assert versions(tmp_path) == [] and "periodic checkpoint failed" in capsys.readouterr().err
    assert list((tmp_path / "output" / "checkpoint").iterdir()) == []


def test_only_the_last_two_checkpoints_are_kept(tmp_path, clean):
    m = Model()
    checkpoint.register(save=m.save, load=m.load, checkpoint_every=1)
    for epoch in range(1, 5):
        m.epoch = epoch
        clean.now += 61
        assert checkpoint.tick()
    assert versions(tmp_path) == ["ckpt-000003", "ckpt-000004"]


def test_a_stop_request_saves_and_ends_with_85(tmp_path):
    m = Model(7)
    checkpoint.register(save=m.save, load=m.load, checkpoint_every=False)
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    with pytest.raises(SystemExit) as stopped:
        checkpoint.tick()
    assert stopped.value.code == 85
    [name] = versions(tmp_path)
    assert (tmp_path / "output" / "checkpoint" / name / "state.txt").read_text() == "7"


def test_a_failing_save_on_stop_propagates(tmp_path):
    def save_state(path):
        raise OSError("disk full")

    checkpoint.register(save=save_state, load=lambda p: None)
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    with pytest.raises(OSError):
        checkpoint.tick()


def test_save_without_arguments_uses_the_registered_function(tmp_path):
    m = Model(2)
    checkpoint.register(save=m.save, load=m.load)
    assert checkpoint.save() is False
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    with pytest.raises(SystemExit):
        checkpoint.save()
    assert len(versions(tmp_path)) == 1


def test_tick_needs_a_registration():
    with pytest.raises(RuntimeError):
        checkpoint.tick()


def test_the_module_can_be_called_like_register(tmp_path):
    m = Model()
    assert checkpoint(save=m.save, load=m.load, checkpoint_every=False) is None
    assert checkpoint._reg is not None and checkpoint._reg.every is False


# ----------------------------------------------------------------------------------------------- interval

@pytest.mark.parametrize("save_seconds,expected", [
    (1, checkpoint.MIN_EVERY_SECONDS),                 # fast saves: not more often than every 5 min
    (60, 600),                                         # a minute to save: every 10 min keeps it near 10 %
    (120, 1200),
    (1000, checkpoint.MAX_EVERY_SECONDS),              # very slow saves: capped at an hour
])
def test_the_interval_follows_the_measured_save_time(tmp_path, clean, save_seconds, expected):
    m = Model()

    def save_state(path):
        clean.now += save_seconds
        return m.save(path)

    checkpoint.register(save=save_state, load=m.load)
    assert checkpoint._reg.interval_seconds() == checkpoint.DEFAULT_EVERY_SECONDS   # nothing measured yet
    clean.now += checkpoint.DEFAULT_EVERY_SECONDS
    assert checkpoint.tick()
    assert checkpoint._reg.interval_seconds() == expected


def test_an_explicit_interval_wins_and_false_turns_it_off(tmp_path, clean):
    checkpoint.register(save=Model().save, load=Model().load, checkpoint_every=20)
    assert checkpoint._reg.interval_seconds() == 1200
    checkpoint.register(save=Model().save, load=Model().load, checkpoint_every=False)
    clean.now += 10 ** 6
    assert checkpoint._reg.interval_seconds() is None and checkpoint.tick() is False


def test_a_bad_interval_is_refused():
    with pytest.raises(ValueError):
        checkpoint.register(save=Model().save, load=Model().load, checkpoint_every="often")


# ----------------------------------------------------------------------------------------------- resume

def write_ckpt(root, name, epoch, corrupt=False):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "state.txt").write_text(str(epoch))
    checkpoint._write_manifest(folder, {"epoch": epoch}, 0.1, int(name.split("-")[1]))
    if corrupt:
        (folder / "state.txt").write_text("X")        # same size, other content: the checksum catches it
    return folder


def test_resume_loads_the_newest_checkpoint_and_returns_its_progress(tmp_path, monkeypatch):
    root = tmp_path / "resume"
    write_ckpt(root, "ckpt-000001", 1)
    write_ckpt(root, "ckpt-000002", 2)
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(root))
    m = Model()
    assert checkpoint.register(save=m.save, load=m.load) == {"epoch": 2}
    assert m.epoch == 2


def test_resume_skips_a_corrupted_newest_checkpoint_for_the_previous_good_one(tmp_path, monkeypatch, capsys):
    root = tmp_path / "resume"
    write_ckpt(root, "ckpt-000001", 1)
    write_ckpt(root, "ckpt-000002", 2, corrupt=True)
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(root))
    m = Model()
    assert checkpoint.register(save=m.save, load=m.load) == {"epoch": 1}
    assert m.epoch == 1 and "does not match its checksum" in capsys.readouterr().err


def test_resume_skips_a_checkpoint_with_a_missing_file_or_an_unreadable_manifest(tmp_path, monkeypatch):
    root = tmp_path / "resume"
    write_ckpt(root, "ckpt-000001", 1)
    write_ckpt(root, "ckpt-000002", 2).joinpath("state.txt").unlink()
    broken = write_ckpt(root, "ckpt-000003", 3)
    (broken / "manifest.json").write_text("{not json")
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(root))
    assert checkpoint.newest_valid(root).name == "ckpt-000001"


def test_resume_tries_the_previous_checkpoint_when_load_rejects_the_newest(tmp_path, monkeypatch):
    root = tmp_path / "resume"
    write_ckpt(root, "ckpt-000001", 1)
    write_ckpt(root, "ckpt-000002", 2)
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(root))
    m = Model()

    def load_state(path):
        if path.name == "ckpt-000002":
            raise ValueError("incompatible")
        m.load(path)

    assert checkpoint.register(save=m.save, load=load_state) == {"epoch": 1}


def test_resume_with_no_verifying_checkpoint_is_an_error_never_a_silent_fresh_start(tmp_path, monkeypatch):
    root = tmp_path / "resume"
    write_ckpt(root, "ckpt-000001", 1, corrupt=True)
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(root))
    with pytest.raises(RuntimeError, match="no checkpoint there verifies"):
        checkpoint.register(save=Model().save, load=Model().load)


def test_resume_accepts_a_lone_checkpoint_without_a_manifest_from_an_older_layout(tmp_path, monkeypatch):
    root = tmp_path / "resume"
    root.mkdir()
    (root / "state.txt").write_text("5")
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(root))
    m = Model()
    assert checkpoint.register(save=m.save, load=m.load) is None
    assert m.epoch == 5


def flat_save(path):
    (path / "state.txt").write_text("6")
    return 6


def test_a_flat_checkpoint_from_save_fn_resumes_with_its_manifest(tmp_path, monkeypatch):
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    with pytest.raises(SystemExit):
        checkpoint.save(flat_save)
    flat = tmp_path / "output" / "checkpoint"
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(flat))
    checkpoint._state["requested"] = False
    m = Model()
    assert checkpoint.register(save=m.save, load=m.load) == 6 and m.epoch == 6


def test_progress_values_compare_dicts_in_key_order():
    assert checkpoint.progress_values({"epoch": 3, "step": 1200}) == [3, 1200]
    assert checkpoint.progress_values(7) == [7] and checkpoint.progress_values(None) == []
    for bad in (True, "x", {"epoch": "3"}, [1]):
        with pytest.raises(TypeError):
            checkpoint.progress_values(bad)


def test_a_newer_checkpoint_after_resume_continues_the_numbering(tmp_path, monkeypatch, clean):
    out = tmp_path / "output" / "checkpoint"
    write_ckpt(out, "ckpt-000004", 4)
    m = Model(5)
    checkpoint.register(save=m.save, load=m.load, checkpoint_every=1)
    clean.now += 61
    assert checkpoint.tick()
    assert versions(tmp_path) == ["ckpt-000004", "ckpt-000005"]


def test_the_platform_folder_receives_the_checkpoints_and_is_where_a_continuation_finds_them(tmp_path, monkeypatch, clean):
    folder = tmp_path / "ckptdir"
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(folder))
    m = Model(3)
    checkpoint.register(save=m.save, load=m.load, checkpoint_every=1)
    clean.now += 61
    assert checkpoint.tick()
    assert [p.name for p in folder.iterdir()] == ["ckpt-000001"] and not (tmp_path / "output").exists()
    # the platform restores the same folder and points KAOS_RESUME_PATH at it
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(folder))
    other = Model()
    assert checkpoint.register(save=other.save, load=other.load) == {"epoch": 3, "step": 300}
    assert other.epoch == 3
