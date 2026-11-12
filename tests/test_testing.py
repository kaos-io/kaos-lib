"""kaos_lib.testing: call a step's main() in the same process with a prepared context and local folders."""
import os

import pytest

from kaos_lib import step, testing
from kaos_lib.errors import StepError


def main():
    """A step as an engineer writes it."""
    ctx = step.start()
    files = sorted(p.name for p in step.input("dataset").rglob("*") if p.is_file())
    previous = step.upstream("prepare", optional=True)
    (step.output("report") / "files.txt").write_text("\n".join(files))
    step.result(files=len(files), experiment=ctx.experiment, seed=ctx.params["train"]["seed"],
                prepared=previous.values["rows"] if previous else None)


def folder(tmp_path, names):
    data = tmp_path / "data"
    data.mkdir()
    for name in names:
        (data / name).write_text(name)
    return data


def test_a_step_runs_in_process_and_its_result_and_outputs_are_read_back(tmp_path):
    data = folder(tmp_path, ["a.txt", "b.txt"])
    with testing.running(tmp_path, kind="evaluate", params={"train": {"seed": 7}}, inputs={"dataset": data},
                         upstream={"prepare": {"rows": 12}}, produces=[("artifact", "report")]) as run:
        main()
    assert run.result["values"] == {"files": 2, "experiment": "test", "seed": 7, "prepared": 12}
    assert [r["name"] for r in run.result["reads"]] == ["dataset"]
    assert [(w["name"], w["type"], w["repo"]) for w in run.result["writes"]] == [("report", "artifact", "outputs-app")]
    assert (run.output("report") / "files.txt").read_text() == "a.txt\nb.txt"


def test_an_input_folder_holds_only_the_files_that_were_given(tmp_path):
    with testing.running(tmp_path, inputs={"dataset": folder(tmp_path, ["a.txt"])}):
        step.start()
        assert sorted(p.name for p in step.input("dataset").iterdir()) == ["a.txt"]
    assert not list((tmp_path / "data").glob("*kaos-ready"))                      # the caller's folder is untouched


def test_a_step_that_did_not_run_before_this_one_is_seen_as_absent(tmp_path):
    with testing.running(tmp_path, upstream={"prepare": None}, params={"train": {"seed": 1}},
                         inputs={"dataset": folder(tmp_path, ["a.txt"])}, produces=[("artifact", "report")]) as run:
        main()
    assert run.result["values"]["prepared"] is None
    with testing.running(tmp_path / "other", upstream={"prepare": None}):
        step.start()
        with pytest.raises(StepError, match="step 'prepare' did not run"):
            step.upstream("prepare")


def test_a_step_that_writes_no_result_leaves_none(tmp_path):
    with testing.running(tmp_path) as run:
        step.start()
    assert run.result is None


def test_the_environment_and_the_step_are_put_back(tmp_path):
    before = dict(os.environ)
    with testing.running(tmp_path):
        step.start()
    assert dict(os.environ) == before and step._running is None


# ------------------------------------------------------------------ workdir, a writable input, what an upstream step wrote
def test_workdir_is_one_emptied_folder_that_is_not_an_output(tmp_path):
    with testing.running(tmp_path, produces=[("artifact", "report")]) as run:
        step.start()
        scratch = step.workdir()
        (scratch / "runs").mkdir()
        (scratch / "runs" / "cache.bin").write_text("x")
        assert step.workdir() == scratch and (scratch / "runs" / "cache.bin").exists()
        (step.output("report") / "r.txt").write_text("r")
        step.result()
    assert not (run.output("report") / "runs").exists() and not list(run.output("report").glob("**/cache.bin"))
    with testing.running(tmp_path):                       # the next attempt finds it empty
        step.start()
        assert list(step.workdir().iterdir()) == []


def test_a_writable_input_is_a_private_copy_that_changes_nothing_else(tmp_path):
    data = folder(tmp_path, ["a.txt"])
    with testing.running(tmp_path, inputs={"dataset": data}, produces=[("artifact", "report")]) as run:
        step.start()
        read_only = step.input("dataset")
        copy = step.input("dataset", writable=True)
        assert copy != read_only and (copy / "a.txt").read_text() == "a.txt" and step.input("dataset", writable=True) == copy
        (copy / "a.txt").write_text("changed")               # a tool that rewrites a file beside its input
        (copy / "labels.cache").write_text("cache")
        assert (read_only / "a.txt").read_text() == "a.txt" and not (read_only / "labels.cache").exists()
        assert not os.path.samefile(copy / "a.txt", read_only / "a.txt")
        (step.output("report") / "r.txt").write_text("r")
        step.result()
    assert (data / "a.txt").read_text() == "a.txt" and sorted(p.name for p in data.iterdir()) == ["a.txt"]
    assert sorted(p.name for p in run.output("report").iterdir()) == ["r.txt"]


def test_a_writable_input_that_is_missing_is_still_none_when_optional(tmp_path):
    with testing.running(tmp_path, upstream={"prepare": None}):
        step.start()
        assert step.input("rows", optional=True, writable=True) is None


def test_a_step_reads_what_an_upstream_step_wrote(tmp_path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "best.pt").write_text("weights")
    with testing.running(tmp_path, kind="evaluate", upstream={"train": {"epochs": 3}},
                         upstream_writes={"train": {"checkpoints": ckpt}}) as run:
        step.start()
        train = step.upstream("train")
        assert train.values == {"epochs": 3}
        (write,) = train.writes
        assert (write.name, write.type, write.repo) == ("checkpoints", "artifact", "outputs-app") and write.commit
        assert (step.input("checkpoints") / "best.pt").read_text() == "weights"
        step.result()
    assert run.result["values"] == {}


def test_an_upstream_step_that_only_wrote_needs_no_values(tmp_path):
    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "best.pt").write_text("w")
    with testing.running(tmp_path, upstream_writes={"train": {"checkpoints": ckpt}}):
        step.start()
        assert step.upstream("train").values == {} and (step.input("checkpoints") / "best.pt").exists()
