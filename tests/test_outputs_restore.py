"""Use cases for putting ``autosave`` files back when a run continues (PRD-HPC-1461 D-44).

A run that stopped (the stop signal, a crash, a lost pod) continues in a new job, often on another node with an
empty disk. Opening its run writer again puts each ``autosave`` file back where the step expects it, so code that
already does "if the checkpoint exists, load it" resumes without a change.
"""
import os
import pathlib

import pytest

from kaos_lib import outputs
from kaos_lib.errors import LakeFSError


def stop(writer):
    """The platform's stop signal inside a run: the writer saves and raises SystemExit(85) out of the block."""
    os.kill(os.getpid(), outputs.STOP_SIGNAL)
    pytest.fail("the stop signal did not end the step")


def new_node(*paths):
    """A continued job lands on another node: nothing the step wrote is on its disk."""
    for p in paths:
        pathlib.Path(p).unlink(missing_ok=True)


# 1. A first run starts clean.
def test_a_first_run_restores_nothing_and_downloads_nothing(fake, client, tmp_path, monkeypatch):
    monkeypatch.setattr(client, "download_object", lambda *a, **k: pytest.fail("a first run downloaded"))
    with outputs.run("myapp", "e", "r1", client=client, autosave=tmp_path / "ckpt.pt") as r:
        assert r.restore() == []
    assert not (tmp_path / "ckpt.pt").exists()


# 2. The main case: stopped before the time limit, continued on another node.
def test_a_continued_run_gets_its_checkpoint_back_where_it_was(fake, client, tmp_path):
    ckpt = tmp_path / "ckpt.pt"
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt):
            ckpt.write_bytes(b"epoch-3")
            os.kill(os.getpid(), outputs.STOP_SIGNAL)
    new_node(ckpt)
    with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
        assert ckpt.read_bytes() == b"epoch-3"
        assert r.restore() == []          # already there now: a second call changes nothing


# 3. A training script that resumes if its file exists, unchanged across jobs.
def _train(ckpt: pathlib.Path, epochs: int, stop_at=None):
    """A user's loop: resume from ckpt if present, write it every epoch. No kaos-lib calls inside."""
    start = int(ckpt.read_text()) if ckpt.exists() else 0
    done = []
    for epoch in range(start + 1, epochs + 1):
        ckpt.write_text(str(epoch))
        done.append(epoch)
        if epoch == stop_at:
            os.kill(os.getpid(), outputs.STOP_SIGNAL)
    return done


def test_a_plain_resume_if_exists_loop_continues_without_changes(fake, client, tmp_path):
    ckpt = tmp_path / "state.txt"
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt):
            _train(ckpt, epochs=5, stop_at=3)               # job 1: epochs 1..3, then the time limit
    new_node(ckpt)
    with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
        assert _train(ckpt, epochs=5) == [4, 5]             # job 2: picks up at 4, not 1
        r.save(ckpt)
    tree = fake.tree("outputs-myapp", "main")
    assert "checkpoints/e/r1/state.txt" in tree
    assert "run-r1-checkpoints" not in fake.repos["outputs-myapp"]["branches"]   # finished: merged, branch gone


# 4. Several continuations in a row.
def test_three_jobs_in_a_row_each_continue_from_the_last(fake, client, tmp_path):
    ckpt = tmp_path / "state.txt"
    for stop_at in (2, 4):
        with pytest.raises(SystemExit):
            with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt):
                _train(ckpt, epochs=6, stop_at=stop_at)
        new_node(ckpt)
    with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt):
        assert _train(ckpt, epochs=6) == [5, 6]


# 5. A crash (not the signal) keeps the branch too; the retry restores the last saved file.
def test_a_crashed_run_restores_what_it_saved_before_the_crash(fake, client, tmp_path):
    ckpt = tmp_path / "ckpt.pt"
    with pytest.raises(RuntimeError):
        with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
            ckpt.write_bytes(b"saved")
            r.save(ckpt)
            ckpt.write_bytes(b"newer, never saved")
            raise RuntimeError("out of memory")
    new_node(ckpt)
    with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt):
        assert ckpt.read_bytes() == b"saved"


# 6. What is on the local disk always wins.
def test_a_local_file_is_never_overwritten(fake, client, tmp_path):
    ckpt = tmp_path / "ckpt.pt"
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
            ckpt.write_bytes(b"old")
            stop(r)
    ckpt.write_bytes(b"local and newer")          # same node, the file survived
    with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
        assert ckpt.read_bytes() == b"local and newer"
        assert r.restore() == []


# 7. Nothing to restore: the branch does not hold that name.
def test_a_name_the_branch_does_not_hold_is_skipped(fake, client, tmp_path):
    other = tmp_path / "other.pt"
    other.write_bytes(b"x")
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=other) as r:
            stop(r)
    missing = tmp_path / "never-saved.pt"
    with outputs.run("myapp", "e", "r1", client=client, autosave=missing) as r:
        assert r.restore() == [] and not missing.exists()


# 8. Folders are not restored (their files are saved without the folder's name).
def test_folders_are_left_to_latest(fake, client, tmp_path):
    runs = tmp_path / "runs"
    (runs / "weights").mkdir(parents=True)
    (runs / "weights" / "last.pt").write_bytes(b"w")
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=runs) as r:
            stop(r)
    for p in (runs / "weights" / "last.pt", runs / "weights"):
        p.unlink() if p.is_file() else p.rmdir()
    runs.rmdir()
    with outputs.run("myapp", "e", "r1", client=client, autosave=[runs, str(runs) + "/"]) as r:
        assert r.restore() == [] and not runs.exists()
        got = r.latest("weights/", dest=tmp_path / "fetched")            # the documented way for a folder
        assert (got / "last.pt").read_bytes() == b"w"


# 9. Paths: nested folders that do not exist yet, relative paths, and every accepted form.
def test_missing_parent_folders_are_created(fake, client, tmp_path):
    ckpt = tmp_path / "deep" / "er" / "ckpt.pt"
    ckpt.parent.mkdir(parents=True)
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
            ckpt.write_bytes(b"d")
            stop(r)
    new_node(ckpt)
    ckpt.parent.rmdir()
    ckpt.parent.parent.rmdir()
    with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt):
        assert ckpt.read_bytes() == b"d"


@pytest.mark.parametrize("form", ["str", "path", "list"])
def test_relative_and_every_accepted_form(fake, client, tmp_path, form):   # conftest runs tests in tmp_path
    rel = "ckpt.pt"
    autosave = {"str": rel, "path": pathlib.Path(rel), "list": [rel]}[form]
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=autosave) as r:
            pathlib.Path(rel).write_bytes(b"rel")
            stop(r)
    new_node(rel)
    with outputs.run("myapp", "e", "r1", client=client, autosave=autosave):
        assert pathlib.Path(rel).read_bytes() == b"rel"


# 10. A failed download leaves nothing half-written and stops the step.
def test_a_failed_download_leaves_no_file_and_raises(fake, client, tmp_path, monkeypatch):
    ckpt = tmp_path / "ckpt.pt"
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
            ckpt.write_bytes(b"x" * 100)
            stop(r)
    new_node(ckpt)

    def broken(repo, ref, path, dest):
        dest.write_bytes(b"x" * 10)                 # part of the file arrived ...
        raise LakeFSError("connection reset", status=503)   # ... then the network failed

    monkeypatch.setattr(client, "download_object", broken)
    with pytest.raises(LakeFSError):
        outputs.run("myapp", "e", "r1", client=client, autosave=ckpt).open()
    assert not ckpt.exists() and not (tmp_path / "ckpt.pt.kaos-restore").exists()
    assert outputs._WATCHED == []                   # a writer that failed to open is not watched


# 11. Runs and kinds stay apart.
def test_two_kinds_of_one_run_restore_only_their_own_files(fake, client, tmp_path):
    ck, rp = tmp_path / "ckpt.pt", tmp_path / "report.json"
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", "checkpoints", client=client, autosave=ck) as a, \
                outputs.run("myapp", "e", "r1", "reports", client=client, autosave=rp):
            ck.write_bytes(b"c")
            rp.write_bytes(b"r")
            stop(a)
    new_node(ck, rp)
    with outputs.run("myapp", "e", "r1", "reports", client=client, autosave=[rp, ck]):
        assert rp.read_bytes() == b"r" and not ck.exists()


def test_another_run_never_gets_this_runs_files(fake, client, tmp_path):
    ckpt = tmp_path / "ckpt.pt"
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt) as r:
            ckpt.write_bytes(b"r1")
            stop(r)
    new_node(ckpt)
    with outputs.run("myapp", "e", "r2", client=client, autosave=ckpt):
        assert not ckpt.exists()


# 12. A finished run does not resume: its branch is merged and gone.
def test_a_finished_run_opened_again_starts_clean(fake, client, tmp_path):
    ckpt = tmp_path / "ckpt.pt"
    ckpt.write_bytes(b"final")
    outputs.write_run("myapp", "e", "r1", tmp_path, client=client)
    new_node(ckpt)
    with outputs.run("myapp", "e", "r1", client=client, autosave=ckpt):
        assert not ckpt.exists()          # open() restores only on a run that is still going (its branch exists)


# 13. Without autosave nothing changes.
def test_without_autosave_open_is_unchanged(fake, client, tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        with outputs.run("myapp", "e", "r1", client=client) as r:
            f = tmp_path / "a.pt"
            f.write_bytes(b"a")
            r.save(f)
            stop(r)
    monkeypatch.setattr(client, "download_object", lambda *a, **k: pytest.fail("downloaded without autosave"))
    with outputs.run("myapp", "e", "r1", client=client) as r:
        assert r.restore() == []
