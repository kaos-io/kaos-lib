"""kaos_lib.step: the context a step is given, its inputs and outputs, and the result it hands on."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

import kaos_lib
from kaos_lib import datasets, lock, step
from kaos_lib.errors import DatasetError, EmptyDataset, StepError

FIXTURES = pathlib.Path(__file__).with_name("contract_fixtures")
CONTEXTS = sorted(p.stem for p in FIXTURES.glob("context-*.wire"))


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def wire(name):
    return (FIXTURES / f"{name}.wire").read_text()


@pytest.fixture(autouse=True)
def one_step_per_test(tmp_path, monkeypatch):
    monkeypatch.setattr(step, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(step, "RESULT_FILE", str(tmp_path / "work" / "output" / "kaos-result.json"))
    monkeypatch.setattr(sys, "exit", sys.exit)                # start() wraps both; put them back after the test
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    yield
    step.stop()


def begin(monkeypatch, context, client=None):
    monkeypatch.setenv(step.ENV, context if isinstance(context, str) else lock.wire(context))
    if client is not None:
        monkeypatch.setattr(step, "_connect", lambda: client)
    return step.start()


def result_file():
    return pathlib.Path(step.RESULT_FILE)


def changed(name, **changes):
    return {**fixture(name), **changes}


# ------------------------------------------------------------------------------------------------- the context
@pytest.mark.parametrize("name", CONTEXTS)
def test_every_fixture_context_starts_a_step(monkeypatch, name):
    want = fixture(name)
    got = begin(monkeypatch, wire(name))
    assert (got.run, got.app, got.project, got.step, got.kind, got.experiment) == tuple(
        want[k] for k in ("run", "app", "project", "step", "kind", "experiment"))
    assert got.params == want["params"]
    assert got.ledger.to_dict() == want["ledger"]
    assert [(p.name, p.type, p.repo, p.promote) for p in got.produces] == [
        (p["name"], p["type"], p["repo"], False) for p in want["produces"]]
    assert set(got.upstream) == set(want["upstream"])
    assert step.start() is got                                   # a second call: the same step


def test_the_escaped_context_arrives_as_it_was_written(monkeypatch):
    got = begin(monkeypatch, wire("context-escapes"))
    assert got.experiment == "café {{workflow.name}}"
    assert got.params["note"].startswith("braces {{=1+1}} } {") and got.params["{key}"] == "a key with braces"
    assert got.params["big"] == 12345678901234567890 and got.params["lr"] == 1e-05


def test_a_skipped_upstream_is_absent_and_a_finished_one_is_its_result(monkeypatch):
    got = begin(monkeypatch, wire("context-skipped-upstream"))
    assert got.upstream["export"] is None
    train = step.upstream("train")
    assert train.values == {"accuracy": 0.93, "best_epoch": 2}
    assert [w.as_dict() for w in train.writes] == fixture("result-model")["writes"]
    assert [r.as_dict() for r in train.reads] == fixture("result-model")["reads"]


def test_fields_this_version_does_not_know_are_ignored(monkeypatch):
    context = changed("context-one-upstream", later="feature")
    context["produces"] = [dict(context["produces"][0], colour="blue")]
    context["ledger"] = dict(context["ledger"], extra=[1])
    assert begin(monkeypatch, context).step == "train"


def test_a_dataset_carries_whether_this_run_promotes_it(monkeypatch):
    context = fixture("context-no-upstream")
    context["produces"] = [dict(context["produces"][0], promote=True)]
    assert begin(monkeypatch, context).produces[0].promote is True


def test_without_a_context_it_is_not_a_step(monkeypatch):
    monkeypatch.delenv(step.ENV, raising=False)
    with pytest.raises(StepError, match="this is not a pipeline step: KAOS_STEP_CONTEXT is not set. "
                                        "Run the step with: kaosctl step run <step>"):
        step.start()


def test_a_context_over_the_cap_is_refused(monkeypatch):
    context = changed("context-no-upstream", params={"blob": "x" * step.CONTEXT_CAP})
    with pytest.raises(StepError, match=r"the step context is \d+ bytes; the limit is 98304"):
        begin(monkeypatch, context)


def test_the_largest_context_that_fits_is_read(monkeypatch):
    base = len(lock.wire(changed("context-no-upstream", params={"blob": ""})))
    context = changed("context-no-upstream", params={"blob": "x" * (step.CONTEXT_CAP - base)})
    assert len(lock.wire(context)) == step.CONTEXT_CAP
    assert len(begin(monkeypatch, context).params["blob"]) == step.CONTEXT_CAP - base


@pytest.mark.parametrize("text,fragment", [
    ("{oops", "the step context is not a JSON object"),
    ("[1, 2]", "the step context is not a JSON object (it is a list)"),
])
def test_a_context_that_is_not_a_json_object(monkeypatch, text, fragment):
    with pytest.raises(StepError) as err:
        begin(monkeypatch, text)
    assert fragment in str(err.value) and "report this" in str(err.value)


@pytest.mark.parametrize("change,fragment", [
    ({"version": 2}, "the step context has version 2; this kaos-lib reads version 1. Upgrade kaos-lib"),
    ({"version": True}, "has version True"),
    ({"run": ""}, "the step context has no run"),
    ({"app": None}, "the step context has no app (it is missing)"),
    ({"project": 7}, "the step context has no project (found int '7')"),
    ({"experiment": None}, "the step context has no experiment"),
    ({"kind": "training"}, "the step context has kind 'training'; a step is one of ingest, transform, train, "
                           "evaluate, publish, control"),
    ({"params": []}, "the step context has no params"),
    ({"ledger": {"version": 1, "reads": []}}, "the step context has no ledger at version 2"),
    ({"ledger": {"version": 2, "reads": [{"repo": "dataset-x", "ref": "v1", "commit": "c"}], "writes": []}},
     "the step context: ledger: reads[0] needs a non-empty string name"),
    ({"produces": None}, "the step context has no produces"),
    ({"produces": [{"name": "m", "type": "weights", "repo": "outputs-a"}]}, "has type 'weights'"),
    ({"produces": [{"name": "kaos-x", "type": "model", "repo": "outputs-a"}]}, "reserved or used twice"),
    ({"upstream": None}, "the step context has no upstream"),
    ({"upstream": {"prepare": {}}}, "upstream.prepare is not a result at version 1"),
    ({"upstream": {"prepare": {"version": 1, "status": "failed"}}}, "has status 'failed'"),
    ({"upstream": {"prepare": {"version": 1, "status": "ok", "values": {}, "writes": []}}}, "has no reads list"),
])
def test_what_is_wrong_with_a_context_is_said(monkeypatch, change, fragment):
    with pytest.raises(StepError) as err:
        begin(monkeypatch, changed("context-one-upstream", **change))
    assert fragment in str(err.value)


@pytest.mark.parametrize("call", [lambda: step.input("raw"), lambda: step.output("model"),
                                  lambda: step.upstream("prepare"), lambda: step.check("model"),
                                  lambda: step.result()])
def test_nothing_works_before_start(call):
    with pytest.raises(StepError, match=r"call step.start\(\) first"):
        call()


# ------------------------------------------------------------------------------------------------------ inputs
@pytest.fixture
def lake(fake):
    """A lakeFS holding the repositories of the fixtures' run, and the fixtures' contexts at its real commits."""
    raw = fake.add_repo("dataset-raw-images", metadata={"kaos.kind": "dataset"},
                        files={"a/1.bin": b"one", "b/2.bin": b"two"})
    labels = fake.add_repo("dataset-labels", metadata={"kaos.kind": "dataset"}, files={"labels.csv": b"x,y\n"})
    made = fake.add_repo("dataset-embeddings", metadata={"kaos.kind": "dataset"}, files={"e.npy": b"emb"})
    fake.add_repo("outputs-hera-demo", metadata={"kaos.kind": "outputs", "kaos.app": "hera-demo"})
    commits = {"1" * 64: raw, "2" * 64: labels, "3" * 64: made}

    def context(name, **changes):
        text = (FIXTURES / f"{name}.json").read_text()
        for old, new in commits.items():
            text = text.replace(old, new)
        return {**json.loads(text), **changes}

    fake.context, fake.commit_of = context, {"raw": raw, "labels": labels, "embeddings": made}
    return fake


def test_an_input_is_the_folder_of_the_pinned_commit(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-no-upstream"), lake.client())
    folder = step.input("raw")
    assert folder.is_dir() and (folder / "a" / "1.bin").read_bytes() == b"one"
    assert step.input("raw") == folder                               # a second call downloads nothing
    assert [r.as_dict() for r in lock.current().reads] == lake.context("context-no-upstream")["ledger"]["reads"]


def test_the_pinned_commit_is_read_even_after_the_dataset_moved(monkeypatch, lake, tmp_path):
    client = lake.client()
    begin(monkeypatch, lake.context("context-no-upstream"), client)
    (tmp_path / "new.bin").write_bytes(b"newer")
    client.create_branch("dataset-raw-images", "more", "main")
    client.upload_object("dataset-raw-images", "more", "c/3.bin", tmp_path / "new.bin")
    client.commit("dataset-raw-images", "more", "more")
    client.merge("dataset-raw-images", "more", "main", "more")
    assert lake.head("dataset-raw-images") != lake.commit_of["raw"]
    assert sorted(p.name for p in step.input("raw").rglob("*.bin")) == ["1.bin", "2.bin"]


def test_a_dataset_an_earlier_step_wrote_is_an_input_by_its_name(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    assert (step.input("embeddings") / "e.npy").read_bytes() == b"emb"
    assert (step.input("labels") / "labels.csv").is_file()
    want = [dict(r) for r in lake.context("context-skipped-upstream")["upstream"]["train"]["reads"]]
    assert [r.as_dict() for r in lock.current().reads] == [want[1], want[0]]     # in the order they were opened


def test_a_model_an_earlier_step_wrote_is_an_input_and_not_a_read(monkeypatch, lake, tmp_path):
    client = lake.client()
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "best.pt").write_bytes(b"w")
    from kaos_lib import outputs
    writer = outputs.RunWriter("hera-demo", "baseline", "hera-demo-x7k2p", "model", client)
    with writer:
        writer.save(weights)
        commit = writer.finish()
    context = lake.context("context-skipped-upstream")
    context["upstream"]["train"]["writes"][0]["commit"] = commit
    context["upstream"]["train"]["reads"] = []
    begin(monkeypatch, context, client)
    assert (step.input("model") / "best.pt").read_bytes() == b"w"
    assert lock.current().reads == []


def test_an_input_that_is_not_declared_names_the_ones_that_are(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    with pytest.raises(StepError, match=r"'images' is not an input of step 'train'. Its inputs are: embeddings, "
                                        r"labels. Add it to inputs=\[...\] in pipeline.py."):
        step.input("images")


def test_an_input_takes_a_name_and_never_a_version(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-no-upstream"), lake.client())
    for extra in ({"version": "v2"}, {"commit": "c1"}, {"ref": "latest"}):
        with pytest.raises(TypeError):
            step.input("raw", **extra)


def test_inside_a_step_a_dataset_the_run_did_not_pin_is_refused(monkeypatch, lake):
    client = lake.client()
    begin(monkeypatch, lake.context("context-no-upstream"), client)
    with pytest.raises(DatasetError, match=r"dataset-labels is not an input of step 'prepare': a step reads only "
                                           r"the versions the run pinned. Add the config value that names it to "
                                           r"inputs=\[...\] in pipeline.py."):
        datasets.resolve(datasets.DatasetRef.parse("dataset-labels@latest"), client)
    pinned = datasets.resolve(datasets.DatasetRef.parse("dataset-raw-images@latest"), client)
    assert pinned == lake.commit_of["raw"]                           # what the run pinned is read, by any path
    assert lock.current().reads[0].name == "raw"


def test_outside_a_step_a_resolve_asks_lakefs_as_before(lake):
    assert datasets.resolve(datasets.DatasetRef.parse("dataset-labels@latest"), lake.client()) \
        == lake.commit_of["labels"]


def test_a_pinned_commit_that_is_gone_is_said(monkeypatch, lake):
    context = lake.context("context-no-upstream")
    context["ledger"]["reads"][0]["commit"] = "f" * 64
    begin(monkeypatch, context, lake.client())
    with pytest.raises(StepError, match=f"input 'raw': commit {'f' * 64} of dataset-raw-images does not exist "
                                        "any more."):
        step.input("raw")


def test_an_input_without_files_is_an_empty_dataset(monkeypatch, lake):
    empty = lake.add_repo("dataset-void", metadata={"kaos.kind": "dataset"})
    context = lake.context("context-no-upstream")
    context["ledger"]["reads"][0].update(repo="dataset-void", commit=empty)
    begin(monkeypatch, context, lake.client())
    with pytest.raises(EmptyDataset, match="holds no files"):
        step.input("raw")


def test_a_whole_staged_copy_is_used_and_anything_else_is_downloaded_with_a_line(monkeypatch, lake, tmp_path, capsys):
    begin(monkeypatch, lake.context("context-no-upstream"), lake.client())
    staged = tmp_path / "staged" / "raw"
    staged.mkdir(parents=True)
    (staged / "from-staging.bin").write_bytes(b"s")
    monkeypatch.setenv("KAOS_STAGED_ROOT", str(tmp_path / "staged"))
    marker = {"repo": "dataset-raw-images", "commit": lake.commit_of["raw"]}
    (staged / ".kaos-ready").write_text(json.dumps(marker))            # a copy that does not say it is whole
    assert step.input("raw") != staged
    assert f"input 'raw': no whole staged copy of dataset-raw-images at {lake.commit_of['raw']}; downloading it." \
        in capsys.readouterr().out
    (staged / ".kaos-ready").write_text(json.dumps(dict(marker, full=True)))
    assert step.input("raw") == staged and capsys.readouterr().out == ""


# ----------------------------------------------------------------------------------------------------- upstream
def test_a_step_that_is_not_upstream(monkeypatch):
    begin(monkeypatch, wire("context-one-upstream"))
    with pytest.raises(StepError, match=r"step 'evaluate' is not upstream of 'train'. Add needs=\['evaluate'\] "
                                        "in pipeline.py."):
        step.upstream("evaluate")


def test_a_needed_step_without_a_result_fails_the_consumer_naming_it(monkeypatch):
    begin(monkeypatch, wire("context-skipped-upstream"))
    with pytest.raises(StepError, match=r"step 'export' wrote no result: it was skipped, or it ended without "
                                        r"step.result\(\). 'evaluate' needs it. Use upstream\('export', "
                                        r"required=False\) if this step can run without it."):
        step.upstream("export")
    assert step.upstream("export", required=False) is None


# ------------------------------------------------------------------------------------------- outputs and result
def test_an_output_that_is_not_declared_names_the_ones_that_are(monkeypatch):
    begin(monkeypatch, wire("context-one-upstream"))
    with pytest.raises(StepError, match=r"'weights' is not produced by step 'train'. It produces: model. "
                                        r"Add it to produces=\[...\] in pipeline.py."):
        step.output("weights")
    with pytest.raises(StepError, match="'weights' is not produced"):
        step.check("weights")


def fill(name, files=None):
    folder = step.output(name)
    for rel, content in (files or {"f.bin": b"data"}).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(content)
    return folder


@pytest.mark.parametrize("context,commit,calls,want", [
    ("context-no-upstream", "3" * 64, lambda: (step.input("raw"), fill("embeddings")), "result-ok"),
    ("context-one-upstream", "4" * 64,
     lambda: (step.input("labels"), step.input("embeddings"), fill("model")), "result-model"),
])
def test_the_result_file_is_the_fixture_byte_for_byte(monkeypatch, context, commit, calls, want):
    monkeypatch.setattr(step, "_dataset", lambda run, datasets, name, read: lock.record(
        read.repo, read.ref, read.commit, read.owner, read.name) and pathlib.Path("."))
    monkeypatch.setattr(step, "_save", lambda run, produce, folder: commit)
    begin(monkeypatch, wire(context))
    calls()
    step.result(**fixture(want)["values"])
    assert result_file().read_text() == wire(want)
    assert not list(result_file().parent.glob("*.part"))


def test_a_step_with_nothing_to_hand_on_still_writes_a_result(monkeypatch):
    begin(monkeypatch, wire("context-escapes"))
    step.result()
    assert json.loads(result_file().read_text()) == {"version": 1, "status": "ok", "values": {}, "reads": [],
                                                     "writes": []}


def test_values_travel_in_wire_form(monkeypatch):
    begin(monkeypatch, wire("context-escapes"))
    step.result(note="{{workflow.name}} café", n=3)
    text = result_file().read_text()
    assert "{{" not in text and text.isascii() and "\n" not in text and ": " not in text
    assert json.loads(text)["values"] == {"note": "{{workflow.name}} café", "n": 3}


def test_a_model_is_saved_under_its_name_and_recorded(monkeypatch, lake):
    client = lake.client()
    context = lake.context("context-one-upstream")
    begin(monkeypatch, context, client)
    step.input("labels")
    fill("model", {"best.pt": b"weights", "plots/loss.png": b"png"})
    step.result(accuracy=0.93)
    got = json.loads(result_file().read_text())
    commit = lake.head("outputs-hera-demo")
    assert got["writes"] == [{"name": "model", "type": "model", "repo": "outputs-hera-demo", "commit": commit}]
    assert got["reads"] == context["ledger"]["reads"] and got["values"] == {"accuracy": 0.93}
    assert set(lake.tree("outputs-hera-demo", commit)) == {
        "model/baseline/hera-demo-x7k2p/best.pt", "model/baseline/hera-demo-x7k2p/plots/loss.png"}


@pytest.mark.parametrize("value,kind", [(object(), "object"), ({1, 2}, "set"), (float("nan"), "float"),
                                         (b"bytes", "bytes")])
def test_a_value_json_cannot_hold_is_refused_before_anything_is_saved(monkeypatch, lake, value, kind):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    fill("model")
    with pytest.raises(StepError, match=f"result value 'bad' is a {kind}; values are text, numbers, booleans, "
                                        "lists and objects."):
        step.result(ok=1, bad=value)
    assert not result_file().exists() and lake.writes == []


def test_a_result_over_the_cap_is_refused_before_anything_is_saved(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    fill("model")
    with pytest.raises(StepError, match=r"the result is \d+ bytes; the limit is 32768. The largest value is "
                                        r"'table' \(\d+ bytes\): save it with step.output\(\) instead."):
        step.result(small=1, table=["row"] * 8000)
    assert not result_file().exists() and lake.writes == []


def test_result_is_called_once(monkeypatch):
    begin(monkeypatch, wire("context-escapes"))
    step.result()
    with pytest.raises(StepError, match=r"step.result\(\) was already called"):
        step.result()


def test_a_declared_output_must_be_written(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    with pytest.raises(StepError, match=r"output 'model' was not written: step 'train' declares it in produces= "
                                        r"and never called step.output\('model'\)"):
        step.result()
    folder = step.output("model")
    with pytest.raises(StepError, match=f"output 'model' is empty: the step wrote no files into {folder}."):
        step.result()
    assert not result_file().exists() and lake.writes == []


def test_a_failed_check_saves_nothing(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    fill("model", {"notes.txt": b"x"})
    step.check("model", layout="yolo", min_files=3)
    with pytest.raises(StepError) as err:
        step.result()
    message = str(err.value)
    assert message.startswith("output 'model' failed its check:") and message.endswith("Nothing was saved.")
    assert "it holds 1 files; at least 3 are needed" in message and "data.yaml" in message
    assert not result_file().exists() and lake.writes == []


def test_a_passing_check_lets_the_output_through(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    fill("model", {"a.bin": b"1", "b.bin": b"2"})
    step.check("model", layout="raw", min_files=2)
    step.result()
    assert result_file().exists()


def test_a_refused_write_says_which_repository(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    fill("model")
    lake.deny = 403
    with pytest.raises(StepError, match="this app may not write outputs-hera-demo"):
        step.result()
    assert not result_file().exists()


# ----------------------------------------------------------------------------- the ledger on the step's MLflow run
def test_result_puts_reads_and_writes_on_the_mlflow_run_as_the_steps_own_file(monkeypatch, lake):
    from fake_mlflow import FakeMlflowClient
    from kaos_lib import frameworks
    mlflow = FakeMlflowClient()
    monkeypatch.setattr(lock, "_client", lambda: mlflow)
    monkeypatch.setattr(frameworks, "_ledger_written", {})
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    step.input("labels")
    frameworks.write_ledger("run-1")                                  # what ending the MLflow run does
    assert json.loads(mlflow.artifacts["run-1"]["ledger/train.json"])["writes"] == []
    fill("model")
    step.result()
    ledger = json.loads(mlflow.artifacts["run-1"]["ledger/train.json"])
    assert [r["name"] for r in ledger["reads"]] == ["labels"] and [w["name"] for w in ledger["writes"]] == ["model"]
    assert set(mlflow.artifacts["run-1"]) == {"ledger/train.json"}


# -------------------------------------------------------------------------------- a step must not end without one
def run_entry(tmp_path, body, context="context-escapes"):
    script = tmp_path / "entry.py"
    script.write_text("from kaos_lib import step\nstep.RESULT_FILE = %r\nstep.start()\n%s\n"
                      % (str(tmp_path / "kaos-result.json"), body))
    env = {**os.environ, "PYTHONPATH": str(pathlib.Path(kaos_lib.__file__).parent.parent), step.ENV: wire(context)}
    done = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=120)
    return done.returncode, done.stderr, (tmp_path / "kaos-result.json")


def test_a_step_that_ends_well_without_a_result_fails(tmp_path):
    code, err, file = run_entry(tmp_path, "print('all done')")
    assert code == 1 and not file.exists()
    assert "ERROR: step 'prepare' ended without step.result(): the next step would get nothing. " \
           "Call step.result() as the last line." in err


def test_a_step_that_hands_on_a_result_ends_well(tmp_path):
    code, err, file = run_entry(tmp_path, "step.result(n=1)")
    assert (code, err) == (0, "") and json.loads(file.read_text())["values"] == {"n": 1}


@pytest.mark.parametrize("body,code", [
    ("raise ValueError('boom')", 1),
    ("import sys; sys.exit(3)", 3),
    ("from kaos_lib import checkpoint; checkpoint.exit_for_restart()", 85),
])
def test_a_step_that_fails_or_is_continued_keeps_its_own_exit(tmp_path, body, code):
    got, err, file = run_entry(tmp_path, body)
    assert got == code and "ended without step.result()" not in err and not file.exists()
