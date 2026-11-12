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


def test_an_upstream_write_given_as_a_mapping_carries_its_type_and_repository(tmp_path):
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "a.txt").write_text("a")
    with testing.running(tmp_path, app="yolo", upstream_writes={
            "prepare-data": {"prepared": {"folder": prepared, "type": "dataset"}}}):
        step.start()
        (write,) = step.upstream("prepare-data").writes
        assert (write.name, write.type, write.repo) == ("prepared", "dataset", "dataset-yolo-prepared") and write.commit
        assert (step.input("prepared") / "a.txt").read_text() == "a"


def test_an_upstream_write_can_name_its_commit_and_need_no_folder(tmp_path):
    with testing.running(tmp_path, app="yolo", upstream_writes={
            "train": {"checkpoints": {"type": "model", "commit": "c" * 40}}}):
        step.start()
        (write,) = step.upstream("train").writes
        assert (write.type, write.repo, write.commit) == ("model", "outputs-yolo", "c" * 40)


def test_an_upstream_write_with_neither_folder_nor_commit_is_refused(tmp_path):
    with pytest.raises(ValueError, match="checkpoints.*folder or a commit"):
        with testing.running(tmp_path, upstream_writes={"train": {"checkpoints": {"type": "model"}}}):
            pass


def test_an_upstream_write_of_an_unknown_type_is_refused(tmp_path):
    with pytest.raises(ValueError, match="type"):
        with testing.running(tmp_path, upstream_writes={"train": {"x": {"commit": "c" * 40, "type": "table"}}}):
            pass


def test_what_an_upstream_step_read_is_given_as_repository_and_version(tmp_path):
    with testing.running(tmp_path, upstream_reads={"prepare-data": {"dataset": "dataset-raw@v2"}}):
        step.start()
        (read,) = step.upstream("prepare-data").reads
        assert (read.name, read.repo, read.ref) == ("dataset", "dataset-raw", "v2")
        assert len(read.commit) == 64 and set(read.commit) <= set("0123456789abcdef")


def test_the_commit_of_an_upstream_read_is_the_same_each_time_and_can_be_named(tmp_path):
    with testing.running(tmp_path / "a", upstream_reads={"p": {"dataset": "dataset-raw@v2"}}):
        step.start()
        first = step.upstream("p").reads[0].commit
    with testing.running(tmp_path / "b", upstream_reads={"p": {"dataset": "dataset-raw@v2"}}):
        step.start()
        assert step.upstream("p").reads[0].commit == first
    named = {"repo": "dataset-raw", "ref": "v2", "commit": "a" * 40}
    with testing.running(tmp_path / "c", upstream_reads={"p": {"dataset": named}}):
        step.start()
        assert step.upstream("p").reads[0].commit == "a" * 40


def test_an_upstream_that_only_read_needs_no_values_or_writes(tmp_path):
    with testing.running(tmp_path, upstream_reads={"p": {"dataset": "dataset-raw@v2"}}):
        step.start()
        up = step.upstream("p")
        assert up.values == {} and not up.writes


def test_an_upstream_read_without_a_version_is_refused(tmp_path):
    with pytest.raises(ValueError, match="repository@version"):
        with testing.running(tmp_path, upstream_reads={"p": {"dataset": "dataset-raw"}}):
            pass


def test_a_step_that_skips_itself_leaves_a_skipped_result_and_a_needed_skipped_step_is_seen_as_skipped(tmp_path):
    def entry():
        step.start()
        if step.skipped("evaluate"):
            step.skip(f"evaluate was skipped: {step.skipped('evaluate')}")
        step.result()

    with testing.running(tmp_path, kind="publish", name="publish", upstream_skipped={"evaluate": "score too low"}) as run:
        with pytest.raises(SystemExit) as stop:
            entry()
    assert stop.value.code == 0
    assert run.result == {"version": 1, "status": "skipped", "reason": "evaluate was skipped: score too low"}
