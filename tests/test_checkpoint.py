"""kaos_lib.checkpoint: save at a safe point after the stop signal, end with 85, resume from the handed-over folder
(PRD-HPC-1461 D-44 as amended 2026-11-05)."""
import ast
import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

from kaos_lib import checkpoint

SRC = pathlib.Path(checkpoint.__file__)


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    checkpoint._state["requested"] = False
    checkpoint._state.pop("polled", None)
    checkpoint._reg = None
    monkeypatch.setenv(checkpoint.OUTPUT_DIR_ENV, str(tmp_path / "output"))
    monkeypatch.delenv(checkpoint.RESUME_PATH_ENV, raising=False)
    monkeypatch.delenv(checkpoint.CHECKPOINT_DIR_ENV, raising=False)
    signal.signal(checkpoint.STOP_SIGNAL, checkpoint._on_stop_signal)
    yield
    checkpoint._state["requested"] = False
    checkpoint._state.pop("polled", None)
    checkpoint._reg = None
    checkpoint._clock = __import__("time").monotonic


def write(name, data):
    def fn(path):
        (path / name).write_bytes(data)
    return fn


def test_without_a_signal_nothing_happens(tmp_path):
    assert not checkpoint.stop_requested() and not checkpoint.is_resume()
    assert checkpoint.save(write("s.pt", b"x")) is False
    assert not (tmp_path / "output").exists()


def test_the_signal_only_records_the_request():
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    assert checkpoint.stop_requested()


def test_save_writes_the_checkpoint_into_the_output_folder_and_exits_85(tmp_path):
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    with pytest.raises(SystemExit) as stopped:
        checkpoint.save(write("state.pt", b"epoch-7"))
    assert stopped.value.code == checkpoint.CONTINUE_EXIT_CODE == 85
    out = tmp_path / "output"
    assert (out / "checkpoint" / "state.pt").read_bytes() == b"epoch-7"
    assert [p.name for p in out.iterdir()] == ["checkpoint"], "no temporary folder is left behind"


def test_a_failing_save_leaves_no_checkpoint_and_raises(tmp_path):
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)

    def broken(path):
        (path / "half.pt").write_bytes(b"half")
        raise OSError("disk full")

    with pytest.raises(OSError):
        checkpoint.save(broken)
    assert list((tmp_path / "output").iterdir()) == []


def test_a_save_that_writes_nothing_is_an_error(tmp_path):
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    with pytest.raises(RuntimeError):
        checkpoint.save(lambda path: None)
    assert list((tmp_path / "output").iterdir()) == []


def test_a_newer_checkpoint_replaces_the_previous_one(tmp_path):
    old = tmp_path / "output" / "checkpoint"
    old.mkdir(parents=True)
    (old / "state.pt").write_bytes(b"old")
    (old / "extra").write_bytes(b"stale")
    os.kill(os.getpid(), checkpoint.STOP_SIGNAL)
    with pytest.raises(SystemExit):
        checkpoint.save(write("state.pt", b"new"))
    assert sorted(p.name for p in old.iterdir()) == ["manifest.json", "state.pt"]
    assert (old / "state.pt").read_bytes() == b"new"
    assert [p.name for p in (tmp_path / "output").iterdir()] == ["checkpoint"]


def test_a_continued_step_finds_its_checkpoint(tmp_path, monkeypatch):
    resume = tmp_path / "resume"
    resume.mkdir()
    (resume / "state.pt").write_bytes(b"epoch-7")
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(resume))
    assert checkpoint.is_resume() and checkpoint.resume_path() == resume


def test_a_resume_path_that_does_not_exist_is_a_first_run(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.RESUME_PATH_ENV, str(tmp_path / "missing"))
    assert not checkpoint.is_resume() and checkpoint.resume_path() is None


def test_standard_library_only():
    imported = set()
    for node in ast.walk(ast.parse(SRC.read_text())):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


STEP = """
import pathlib, sys, time
sys.path.insert(0, sys.argv[1])
from kaos_lib import checkpoint
pathlib.Path("ready").write_text("1")
epoch = 0
while epoch < 600:                      # a training loop that checks at the end of each "epoch"
    time.sleep(0.05)
    epoch += 1
    if checkpoint.stop_requested():
        checkpoint.save(lambda p: (p / "epoch").write_text(str(epoch)))
sys.exit(3)                             # not reached: the stop ends the step first
"""


def test_end_to_end_through_a_shell_that_ignores_the_signal(tmp_path):
    """As the batch script runs it: sh ignores USR1, the step (kaos_lib imported) handles it, saves at a safe point,
    and 85 comes back through sh."""
    (tmp_path / "step.py").write_text(STEP)
    env = dict(os.environ, **{checkpoint.OUTPUT_DIR_ENV: str(tmp_path / "output")})
    src = str(SRC.parents[1])
    p = subprocess.Popen(["sh", "-c", f"trap '' USR1; {sys.executable} step.py {src}; exit $?"],
                         cwd=tmp_path, env=env, start_new_session=True)
    for _ in range(200):
        if (tmp_path / "ready").exists():
            break
        time.sleep(0.05)
    time.sleep(0.2)
    for pid in _children(p.pid):
        os.kill(pid, signal.SIGUSR1)    # only the processes that handle it, as the batch script does
    assert p.wait(timeout=30) == 85
    assert int((tmp_path / "output" / "checkpoint" / "epoch").read_text()) > 0


def _children(pid):
    """The other processes of pid's process group, read from /proc (no procps in the CI image)."""
    group, found = os.getpgid(pid), []
    for entry in pathlib.Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == pid:
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[2]) == group:      # after the command: state, ppid, pgrp
            found.append(int(entry.name))
    return found
