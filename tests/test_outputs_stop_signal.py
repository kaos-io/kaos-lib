"""The stop signal (SIGUSR1 before a Slurm time limit): save progress, keep the run branch, exit 85."""
import os
import signal

import pytest

from kaos_lib import outputs


def branch_tree(fake, run="r1"):
    return fake.tree("outputs-myapp", f"run-{run}-checkpoints")


def test_stop_signal_saves_latest_contents_and_exits_85(fake, client, tmp_path):
    ckpt = tmp_path / "last.pt"
    ckpt.write_bytes(b"epoch-1")
    with pytest.raises(SystemExit) as stopped:
        with outputs.run("myapp", "e", "r1", client=client) as r:
            r.save(ckpt)
            ckpt.write_bytes(b"epoch-7")             # training went on after the last save
            os.kill(os.getpid(), outputs.STOP_SIGNAL)
    assert stopped.value.code == outputs.CHECKPOINT_EXIT_CODE == 85
    assert "run-r1-checkpoints" in fake.repos["outputs-myapp"]["branches"]   # kept for the continued run
    assert [e for e in fake.repos["outputs-myapp"]["commit_log"] if e[0] == "main"] == []   # no merge

    with outputs.run("myapp", "e", "r1", client=client) as r:   # the continued run
        assert r.latest("last.pt", dest=tmp_path / "resume").read_bytes() == b"epoch-7"


def test_autosave_folder_is_saved_without_any_save_call(fake, client, tmp_path):
    weights = tmp_path / "runs" / "train" / "weights"
    weights.mkdir(parents=True)
    (weights / "last.pt").write_bytes(b"w")
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=tmp_path / "runs"):
            os.kill(os.getpid(), outputs.STOP_SIGNAL)
    assert "checkpoints/e/r1/train/weights/last.pt" in branch_tree(fake)


def test_missing_or_empty_paths_are_skipped_and_others_still_saved(fake, client, tmp_path):
    (tmp_path / "empty").mkdir()
    good = tmp_path / "good.pt"
    good.write_bytes(b"g")
    with pytest.raises(SystemExit) as stopped:
        with outputs.run("myapp", "e", "r1", client=client,
                         autosave=[tmp_path / "gone", tmp_path / "empty", good]):
            os.kill(os.getpid(), outputs.STOP_SIGNAL)
    assert stopped.value.code == 85
    assert "checkpoints/e/r1/good.pt" in branch_tree(fake)


def test_a_forked_worker_ignores_the_signal(fake, client, tmp_path):
    f = tmp_path / "a.pt"
    f.write_bytes(b"a")
    with outputs.run("myapp", "e", "r1", client=client) as r:
        r.save(f)
        outputs._HANDLER["pid"] = os.getpid() + 1          # as seen from a DataLoader worker
        try:
            outputs._on_stop_signal(outputs.STOP_SIGNAL, None)   # returns, no exit
        finally:
            outputs._HANDLER["pid"] = os.getpid()


def test_handler_only_while_a_writer_is_open_and_previous_restored(fake, client):
    def mine(signum, frame):
        pass
    previous = signal.signal(outputs.STOP_SIGNAL, mine)
    try:
        with outputs.run("myapp", "e", "r1", client=client):
            assert signal.getsignal(outputs.STOP_SIGNAL) is outputs._on_stop_signal
        assert signal.getsignal(outputs.STOP_SIGNAL) is mine
    finally:
        signal.signal(outputs.STOP_SIGNAL, previous)


def test_finished_run_no_longer_reacts(fake, client, tmp_path):
    f = tmp_path / "a.pt"
    f.write_bytes(b"a")
    r = outputs.run("myapp", "e", "r1", client=client).open()
    r.save(f)
    r.finish()
    assert r not in outputs._WATCHED
    assert signal.getsignal(outputs.STOP_SIGNAL) is not outputs._on_stop_signal


CHILD = '''
import os, sys, time, pathlib
sys.path[:0] = [os.environ["SRC"], os.environ["TESTS"]]
from fake_lakefs import FakeLakeFS
from kaos_lib import outputs
fake = FakeLakeFS(); fake.add_repo("outputs-myapp")
f = pathlib.Path("last.pt"); f.write_bytes(b"x")
with outputs.run("myapp", "e", "r1", client=fake.client()) as r:
    r.save(f)
    pathlib.Path("ready").write_text("1")
    for _ in range(200):
        time.sleep(0.05)
sys.exit(3)   # not reached: the stop signal ends the step first
'''


def test_through_sh_that_ignores_the_signal_like_the_batch_script(tmp_path):
    """The Slurm batch script runs `sh -c "trap '' USR1; <step>"` in its own process group and signals the group:
    sh and steps without kaos-lib ignore it, the kaos-lib step saves and exits 85, and sh passes 85 on."""
    import pathlib
    import subprocess
    import sys
    import time
    (tmp_path / "child.py").write_text(CHILD)
    here = pathlib.Path(__file__).parent
    env = {**os.environ, "SRC": str(here.parent / "src"), "TESTS": str(here)}
    p = subprocess.Popen(["sh", "-c", f"trap '' USR1; {sys.executable} child.py; exit $?"], cwd=tmp_path, env=env,
                         start_new_session=True)
    for _ in range(200):
        if (tmp_path / "ready").exists():
            break
        time.sleep(0.05)
    os.killpg(p.pid, signal.SIGUSR1)
    assert p.wait(timeout=20) == 85
