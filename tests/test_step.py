"""kaos_lib.step: the context a step is given, its inputs and outputs, and the result it hands on."""
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

import kaos_lib
from kaos_lib import datasets, lock, step
from kaos_lib.layouts import local
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


def refused(capsys, monkeypatch, context) -> str:
    """Start a step on a context that cannot be read: the one line it leaves on stderr."""
    with pytest.raises(SystemExit) as stop:
        begin(monkeypatch, context)
    err = capsys.readouterr().err
    assert stop.value.code == 1 and err.startswith("ERROR: ") and err.count("\n") == 1 and "Traceback" not in err
    return err


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
    assert got.params == {**want["params"], **want.get("matrix", {}).get("values", {})}   # an item's values are settings
    assert got.ledger.to_dict() == want["ledger"]
    assert [(p.name, p.type, p.repo) for p in got.produces] == [(p["name"], p["type"], p["repo"]) for p in want["produces"]]
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


def test_a_skipped_upstream_has_its_reason_and_an_absent_one_has_none(monkeypatch):
    context = changed("context-skipped-upstream")
    context["upstream"]["export"] = fixture("result-skipped")
    got = begin(monkeypatch, json.dumps(context))
    assert got.upstream["export"] is None and got.skipped == {"export": fixture("result-skipped")["reason"]}
    assert step.skipped("export") == fixture("result-skipped")["reason"] and step.skipped("train") is None
    with pytest.raises(StepError, match=r"step 'export' was skipped \(the verdict was not good enough to publish\), "
                                         r"so it left no result, and 'evaluate' needs it."):
        step.upstream("export")
    assert step.upstream("export", optional=True) is None


def test_a_step_that_did_not_run_is_skipped_with_no_reason(monkeypatch):
    begin(monkeypatch, wire("context-skipped-upstream"))
    assert step.skipped("export") == "" and step.skipped("train") is None
    with pytest.raises(StepError, match="step 'export' did not run, so it left no result"):
        step.upstream("export")
    with pytest.raises(StepError, match="step 'nothere' is not upstream of 'evaluate'"):
        step.skipped("nothere")


def test_a_skipped_result_without_a_reason_is_refused(monkeypatch, capsys):
    context = changed("context-skipped-upstream")
    context["upstream"]["export"] = {"version": 1, "status": "skipped"}
    assert "is skipped and has no reason" in refused(capsys, monkeypatch, context)


def test_without_a_context_it_is_not_a_step_one_line_and_exit_1(monkeypatch, capsys):
    monkeypatch.delenv(step.ENV, raising=False)
    with pytest.raises(SystemExit) as stop:
        step.start()
    assert stop.value.code == 1
    assert capsys.readouterr().err == ("ERROR: this is not a pipeline step: KAOS_STEP_CONTEXT is not set. "
                                       "Run the step with: kaosctl step run <step>\n")


def test_a_context_over_the_cap_is_refused(monkeypatch, capsys):
    context = changed("context-no-upstream", params={"blob": "x" * step.CONTEXT_CAP})
    assert re.search(r"the step context costs \d+; the limit is 98304", refused(capsys, monkeypatch, context))


def test_the_cap_counts_the_cost_and_the_largest_context_that_fits_is_read(monkeypatch, capsys):
    base = lock.cost(lock.wire(changed("context-no-upstream", params={"blob": ""})))
    context = changed("context-no-upstream", params={"blob": "x" * (step.CONTEXT_CAP - base)})
    assert lock.cost(lock.wire(context)) == step.CONTEXT_CAP > len(lock.wire(context))
    assert len(begin(monkeypatch, context).params["blob"]) == step.CONTEXT_CAP - base
    step.stop()
    quotes = changed("context-no-upstream", params={"blob": '"' * 40000})      # 80002 bytes that cost 120002
    assert len(lock.wire(quotes)) < step.CONTEXT_CAP
    assert "the step context costs" in refused(capsys, monkeypatch, quotes)


@pytest.mark.parametrize("text,fragment", [
    ("{oops", "the step context is not a JSON object"),
    ("[1, 2]", "the step context is not a JSON object (it is a list)"),
])
def test_a_context_that_is_not_a_json_object(monkeypatch, capsys, text, fragment):
    err = refused(capsys, monkeypatch, text)
    assert fragment in err and "report this" in err


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
    ({"produces": [{"name": "kaos-x", "type": "model", "repo": "outputs-a"}]}, "reserved, used twice or not a name"),
    ({"produces": [{"name": "x" * 41, "type": "model", "repo": "outputs-a"}]}, "at most 40 characters"),
    ({"produces": [{"name": "Model", "type": "model", "repo": "outputs-a"}]}, "not a name"),
    ({"upstream": None}, "the step context has no upstream"),
    ({"upstream": {"prepare": {}}}, "upstream.prepare is not a result at version 1"),
    ({"upstream": {"prepare": {"version": 1, "status": "failed"}}}, "has status 'failed'"),
    ({"upstream": {"prepare": {"version": 1, "status": "ok", "values": {}, "writes": []}}}, "has no reads list"),
])
def test_what_is_wrong_with_a_context_is_said(monkeypatch, capsys, change, fragment):
    assert fragment in refused(capsys, monkeypatch, changed("context-one-upstream", **change))


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
    made = fake.add_repo("dataset-hera-demo-embeddings", metadata={"kaos.kind": "dataset"}, files={"e.npy": b"emb"})
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


def test_every_declared_input_is_in_the_reads_whether_it_was_opened_or_not(monkeypatch, lake):
    context = lake.context("context-one-upstream")
    begin(monkeypatch, context, lake.client())
    assert [r.as_dict() for r in lock.current().reads] == context["ledger"]["reads"]      # "labels", never opened
    step.input("embeddings")                                         # a dataset the step before wrote: added when read
    assert [r.name for r in lock.current().reads] == ["labels", "embeddings"]


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
    assert [r.as_dict() for r in lock.current().reads] == want       # the declared input, then what was read


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
    assert [r.name for r in lock.current().reads] == ["raw"]


def test_inside_a_step_a_commit_given_in_code_is_no_way_round_the_pin(monkeypatch, lake):
    client = lake.client()
    begin(monkeypatch, lake.context("context-no-upstream"), client)
    other, pinned = lake.head("dataset-labels"), lake.commit_of["raw"]
    ref = datasets.DatasetRef("dataset-labels", "latest")
    with pytest.raises(DatasetError, match="dataset-labels is not an input of step 'prepare'"):
        datasets.resolve(ref, client, commit=other)
    with pytest.raises(DatasetError, match="dataset-labels is not an input of step 'prepare'"):
        datasets.resolve(datasets.DatasetRef("dataset-labels", "latest", commit=other), client)
    with pytest.raises(DatasetError, match="dataset-raw-images is not an input"):          # not the pinned commit
        datasets.resolve(datasets.DatasetRef("dataset-raw-images", "latest"), client, commit=other)
    with pytest.raises(DatasetError, match="dataset-labels is not an input"):
        datasets.materialize(datasets.DatasetRef.parse("dataset-labels@" + other), client=client)
    assert datasets.resolve(datasets.DatasetRef("dataset-raw-images", "latest"), client, commit=pinned) == pinned


def test_an_input_without_files_is_one_line_naming_the_input_and_what_to_do(monkeypatch, lake):
    empty = lake.add_repo("dataset-void", metadata={"kaos.kind": "dataset"})
    context = lake.context("context-no-upstream")
    context["ledger"]["reads"][0].update(repo="dataset-void", commit=empty, ref="latest")
    begin(monkeypatch, context, lake.client())
    with pytest.raises(StepError, match=r"input 'raw': dataset-void holds no files at the version this run read "
                                        r"\(latest\). Push data to it with `kaosctl dataset push <folder> "
                                        r"dataset-void`, or choose another dataset for 'raw' on the run form."):
        step.input("raw")


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


def test_a_whole_staged_copy_is_used_and_anything_else_is_downloaded_with_a_line(monkeypatch, lake, tmp_path, capsys):
    begin(monkeypatch, lake.context("context-no-upstream"), lake.client())
    staged = tmp_path / "staged" / "raw"
    staged.mkdir(parents=True)
    (staged / "from-staging.bin").write_bytes(b"s")
    monkeypatch.setenv("KAOS_STAGED_ROOT", str(tmp_path / "staged"))
    marker = {"repo": "dataset-raw-images", "commit": lake.commit_of["raw"]}
    local.staged_marker(staged).write_text(json.dumps(marker))            # a copy that does not say it is whole
    assert step.input("raw") != staged
    assert f"input 'raw': no whole staged copy of dataset-raw-images at {lake.commit_of['raw']}; downloading it." \
        in capsys.readouterr().out
    local.staged_marker(staged).write_text(json.dumps(dict(marker, full=True)))
    assert step.input("raw") == staged and capsys.readouterr().out == ""


# ----------------------------------------------------------------------------------------------------- upstream
def test_a_step_that_is_not_upstream(monkeypatch):
    begin(monkeypatch, wire("context-one-upstream"))
    with pytest.raises(StepError, match=r"step 'evaluate' is not upstream of 'train'. Add needs=\['evaluate'\] "
                                        "in pipeline.py."):
        step.upstream("evaluate")


def test_a_needed_step_without_a_result_fails_the_consumer_naming_it(monkeypatch):
    begin(monkeypatch, wire("context-skipped-upstream"))
    with pytest.raises(StepError, match=r"step 'export' did not run, so it left no result, and 'evaluate' needs "
                                        r"it. Use upstream\('export', optional=True\) if this step can run without it."):
        step.upstream("export")
    assert step.upstream("export", optional=True) is None


def test_an_input_a_step_that_did_not_run_would_have_produced(monkeypatch):
    begin(monkeypatch, wire("context-skipped-upstream"))
    with pytest.raises(StepError, match=r"input 'exported' of step 'evaluate' is not there, and export did not run or was skipped: "
                                        r"a step that did not run produced nothing. Use input\('exported', "
                                        r"optional=True\) if this step can run without it. What is there: model."):
        step.input("exported")
    assert step.input("exported", optional=True) is None


def test_optional_does_not_excuse_a_name_nothing_could_have_produced(monkeypatch):
    begin(monkeypatch, wire("context-one-upstream"))                 # every needed step ran
    with pytest.raises(StepError, match="'images' is not an input of step 'train'"):
        step.input("images", optional=True)


def test_a_value_name_of_the_platform_is_refused(monkeypatch):
    begin(monkeypatch, wire("context-escapes"))
    with pytest.raises(StepError, match="result value 'kaos-plan': names starting with 'kaos-' are the platform's"):
        step.result(**{"kaos-plan": 1})


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
    monkeypatch.setattr(step, "_save", lambda run: [lock.Write(p.name, p.type, p.repo, commit)
                                                    for p in run.step.produces])
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
    commit = got["writes"][0]["commit"]      # not the head of main: the result's record is committed after the model
    assert got["writes"] == [{"name": "model", "type": "model", "repo": "outputs-hera-demo", "commit": commit}]
    assert got["reads"] == context["ledger"]["reads"] and got["values"] == {"accuracy": 0.93}
    assert set(lake.tree("outputs-hera-demo", commit)) == {
        "model/baseline/hera-demo-x7k2p/best.pt", "model/baseline/hera-demo-x7k2p/plots/loss.png"}


def test_a_model_commit_carries_the_mlflow_run_of_the_step_and_a_dataset_does_not(monkeypatch, lake):
    from kaos_lib import frameworks
    monkeypatch.setattr(frameworks, "_mlflow_run_id", lambda: "ml-run-7")
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    step.input("labels")
    fill("model")
    step.result()
    commit = json.loads(result_file().read_text())["writes"][0]["commit"]
    assert lake.commit_meta("outputs-hera-demo", commit)[1]["mlflow_run_id"] == "ml-run-7"


def test_a_run_that_ended_before_result_is_still_the_runs_mlflow_run(monkeypatch, lake):
    from kaos_lib import frameworks
    monkeypatch.setattr(frameworks, "_mlflow_run_id", lambda: None)          # no active run any more
    monkeypatch.setattr(frameworks, "_ended_runs", ["ml-run-1", "ml-run-2"])
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    step.input("labels")
    fill("model")
    step.result()
    commit = json.loads(result_file().read_text())["writes"][0]["commit"]
    assert lake.commit_meta("outputs-hera-demo", commit)[1]["mlflow_run_id"] == "ml-run-2"


def test_a_step_that_never_used_mlflow_writes_no_mlflow_run_id(monkeypatch, lake):
    from kaos_lib import frameworks
    monkeypatch.setattr(frameworks, "_ended_runs", [])
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    step.input("labels")
    fill("model")
    step.result()
    commit = lake.head("outputs-hera-demo")
    assert "mlflow_run_id" not in lake.commit_meta("outputs-hera-demo", commit)[1]


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
    with pytest.raises(StepError, match=r"the result costs \d+; the limit is 8192. The largest value is 'table' "
                                        r"\(\d+\). A result carries a few small values: log metrics to MLflow, or "
                                        r"write the rest into an artifact with step.output\(\) and hand on its name."):
        step.result(small=1, table=["row"] * 1200)
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
def run_entry(tmp_path, body, context="context-escapes", pre="", stdout=False):
    script = tmp_path / "entry.py"
    script.write_text("%sfrom kaos_lib import step\nstep.WORK = %r\nstep.RESULT_FILE = %r\nstep.start()\n%s\n"
                      % (pre, str(tmp_path / "work"), str(tmp_path / "work" / "output" / "kaos-result.json"), body))
    env = {**os.environ, "PYTHONPATH": str(pathlib.Path(kaos_lib.__file__).parent.parent), step.ENV: wire(context)}
    done = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=120)
    result = tmp_path / "work" / "output" / "kaos-result.json"
    return (done.returncode, done.stderr, result, done.stdout) if stdout else (done.returncode, done.stderr, result)


ENDED = "ended without step.result()"
EXITS = [   # body, exit code, whether a result file exists, whether the "ended without" line is printed
    ("pass", 1, False, True),
    ("raise SystemExit(0)", 1, False, True),
    ("import sys; sys.exit(0)", 1, False, True),
    ("raise SystemExit(3)", 1, False, True),            # not told from a normal end: out of reach, but never zero
    ("import sys; sys.exit(3)", 3, False, False),
    ("import sys\ntry:\n    sys.exit(3)\nexcept SystemExit:\n    raise", 3, False, False),
    ("import sys; sys.exit('a message')", 1, False, False),
    ("import sys; sys.exit(256)", 1, False, True),      # 8 bits only: 256 would end as 0
    ("import sys; sys.exit(512)", 1, False, True),
    ("import sys; sys.exit(257)", 1, False, False),
    ("import sys; sys.exit('text')", 1, False, False),
    ("import sys; sys.exit(None)", 1, False, True),
    ("import sys\ntry:\n    sys.exit(2)\nexcept SystemExit:\n    pass", 2, False, False),     # caught: keeps its code
    ("import argparse\ntry:\n    argparse.ArgumentParser().parse_args(['--nope'])\nexcept SystemExit:\n    pass", 2,
     False, False),
    ("import argparse\nargparse.ArgumentParser().parse_args(['--nope'])", 2, False, False),
    ("import sys, threading\nt = threading.Thread(target=lambda: sys.exit(1)); t.start(); t.join()", 1, False, True),
    ("raise RuntimeError('boom')", 1, False, False),
    ("import sys\nsys.excepthook = lambda *a: print('custom hook')\nraise RuntimeError('x')", 1, False, True),
    ("try:\n    raise RuntimeError('train failed')\nexcept Exception as e:\n    print('error', e)", 1, False, True),
    ("step.result(a=1)", 0, True, False),
    ("step.skip('nothing to publish')", 0, True, False),
    ("step.skip('nothing to publish')\nraise RuntimeError('never reached')", 0, True, False),
    ("step.result(a=1)\nraise RuntimeError('late')", 1, True, False),
    ("step.result(a=1)\nstep.result(a=2)", 1, True, False),
    ("from kaos_lib import checkpoint; checkpoint.exit_for_restart()", 85, False, False),
    ("import os; os._exit(0)", 0, False, False),        # out of reach: nothing runs after it
]


@pytest.mark.parametrize("body,code,has_result,says", EXITS, ids=[e[0].splitlines()[0][:50] for e in EXITS])
def test_a_step_ends_non_zero_without_a_result_and_keeps_the_exit_code_it_chose(tmp_path, body, code, has_result, says):
    got, err, file = run_entry(tmp_path, body)
    assert got == code and file.exists() is has_result and (ENDED in err) is says, err


def test_a_failure_the_library_explains_is_one_line_with_the_place_in_the_step_and_no_traceback(tmp_path):
    got, err, file = run_entry(tmp_path, "step.input('nope')")
    assert got == 1 and not file.exists()
    assert "Traceback" not in err and ENDED not in err
    lines = [line for line in err.splitlines() if line.strip()]
    assert lines[0].startswith("ERROR: ") and "nope" in lines[0]
    assert lines[1].startswith("  at ") and "kaos_lib" not in lines[1]


def test_a_failure_of_the_steps_own_code_keeps_its_traceback(tmp_path):
    got, err, file = run_entry(tmp_path, "raise RuntimeError('boom')")
    assert got == 1 and "Traceback" in err and "RuntimeError: boom" in err


def test_handlers_registered_before_start_run_and_those_after_run_once_when_the_step_has_no_result(tmp_path):
    pre = "import atexit\natexit.register(lambda: print('BEFORE START'))\n"
    body = "import atexit\natexit.register(lambda: print('AFTER START', flush=True))"
    got, err, file, out = run_entry(tmp_path, body, pre=pre, stdout=True)
    assert got == 1 and not file.exists() and ENDED in err
    assert out.splitlines().count("BEFORE START") == 1 and out.splitlines().count("AFTER START") == 1


def test_the_hook_is_taken_off_when_the_step_is_forgotten(monkeypatch):
    real_exit, real_hook = sys.exit, sys.excepthook
    begin(monkeypatch, wire("context-escapes"))
    assert sys.exit is not real_exit
    step.stop()
    assert sys.exit is real_exit and sys.excepthook is real_hook


def test_result_after_a_failed_result_works_once(monkeypatch, lake):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    with pytest.raises(StepError, match="was not written"):
        step.result()
    fill("model")
    step.result()
    with pytest.raises(StepError, match=r"step.result\(\) was already called"):
        step.result()


# ------------------------------------------------------------------ an output folder that is a link; a name that is both
def test_an_output_folder_that_is_a_symlink_is_refused_and_nothing_is_deleted_through_it(monkeypatch, tmp_path):
    begin(monkeypatch, wire("context-no-upstream"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep").write_text("x")
    folder = tmp_path / "work" / "kaos" / "outputs" / "embeddings"
    folder.parent.mkdir(parents=True)
    folder.symlink_to(elsewhere)
    with pytest.raises(StepError, match=r"output 'embeddings'.*must be a real folder"):
        step.output("embeddings")
    assert (elsewhere / "keep").read_text() == "x" and folder.is_symlink()


def test_a_step_whose_output_has_the_name_of_one_of_its_inputs_is_refused_at_start(monkeypatch, capsys):
    context = fixture("context-no-upstream")
    context["produces"][0]["name"] = "raw"                       # the step reads 'raw' and writes 'raw'
    err = refused(capsys, monkeypatch, context)
    assert "'raw'" in err and "output" in err and "input" in err and "different name" in err


def test_an_output_named_like_an_input_of_a_needed_step_is_refused_at_start(monkeypatch, capsys):
    context = fixture("context-one-upstream")
    write = next(iter(context["upstream"].values()))["writes"][0]
    context["produces"][0]["name"] = write["name"]
    assert "different name" in refused(capsys, monkeypatch, context)


# ------------------------------------------------------------------------------- what the log says an output changed
def _write_dataset(monkeypatch, lake, context, files, capsys):
    """Run one step that writes ``files`` into its dataset output; returns the lines it printed."""
    begin(monkeypatch, lake.context(context), lake.client())
    fill("embeddings", files)
    capsys.readouterr()
    step.result()
    lines = capsys.readouterr().out.splitlines()
    step.stop()
    return lines


REPO = "dataset-hera-demo-embeddings"


def _newest_seal(lake):
    tags = lake.repos[REPO]["tags"]
    tag = max(t for t in tags if t.startswith("k-"))
    return tag, tags[tag]


def test_the_log_says_what_a_first_version_uploaded_and_that_it_is_sealed_not_latest(monkeypatch, lake, capsys):
    before = lake.head(REPO)
    lines = _write_dataset(monkeypatch, lake, "context-no-upstream", {"a.bin": b"a", "b.bin": b"b"}, capsys)
    tag, sealed = _newest_seal(lake)
    assert lake.head(REPO) == before != sealed, "a step never moves latest"
    assert lines == [
        "output 'embeddings': 2 file(s) to upload, 1 to delete, 0 unchanged since the last version of "
        "dataset-hera-demo-embeddings.",
        f"output 'embeddings': sealed dataset-hera-demo-embeddings at {sealed[:12]} (kept as {tag}). It becomes the "
        "latest when the whole run has ended well, if the run form's promote-embeddings is ticked."]


def test_the_log_says_when_a_run_changed_one_file_and_when_it_changed_nothing(monkeypatch, lake, capsys):
    """latest does not move in a step, so what 'last version' means is what main holds: here, the content the
    test's lake starts with (nothing)."""
    lines = _write_dataset(monkeypatch, lake, "context-no-upstream", {"a.bin": b"a", "b.bin": b"b"}, capsys)
    assert lines[0].startswith("output 'embeddings': 2 file(s) to upload")
    lake.repos[REPO]["branches"]["main"]["commit"] = _newest_seal(lake)[1]       # as the final task of that run would have moved it
    head = lake.head(REPO)
    lines = _write_dataset(monkeypatch, lake, "context-no-upstream", {"a.bin": b"a", "b.bin": b"changed"}, capsys)
    assert lines[0] == ("output 'embeddings': 1 file(s) to upload, 0 to delete, 1 unchanged since the last version of "
                        "dataset-hera-demo-embeddings.")
    lines = _write_dataset(monkeypatch, lake, "context-no-upstream", {"a.bin": b"a", "b.bin": b"b"}, capsys)
    assert lines == [
        "output 'embeddings': 0 file(s) to upload, 0 to delete, 2 unchanged since the last version of "
        "dataset-hera-demo-embeddings.",
        f"output 'embeddings': the same content as the last version of dataset-hera-demo-embeddings "
        f"({head[:12]}); no new version."]


def test_the_log_says_where_a_model_was_saved(monkeypatch, lake, capsys):
    begin(monkeypatch, lake.context("context-one-upstream"), lake.client())
    step.input("labels")
    fill("model", {"best.pt": b"w"})
    capsys.readouterr()
    step.result()
    commit = json.loads(result_file().read_text())["writes"][0]["commit"]
    assert capsys.readouterr().out.splitlines() == [
        "output 'model': 1 file(s) to upload, 0 to delete, 0 unchanged since the last version of outputs-hera-demo "
        "(model/baseline/hera-demo-x7k2p/).",
        f"output 'model': saved at {commit[:12]}."]


# ------------------------------------------------------------------------------------------------------- step.skip
def test_a_step_that_skips_itself_ends_with_exit_0_and_a_skipped_result_and_saves_nothing(tmp_path):
    got, err, file, out = run_entry(tmp_path, "step.skip('the verdict is not good enough to publish')",
                                    context="context-no-upstream", stdout=True)
    assert got == 0 and "step 'prepare' skipped: the verdict is not good enough to publish" in out
    assert err.startswith("WARNING: the result of step 'prepare' could not be saved for a later run to reuse"), \
        "no lake here: the record is not saved, which is a warning and not a failure"
    assert json.loads(file.read_text()) == {"version": 1, "status": "skipped",
                                            "reason": "the verdict is not good enough to publish"}
    assert not (tmp_path / "work" / "kaos" / "outputs").exists(), "a step that declares a dataset needs write nothing"


def test_the_skipped_result_is_the_fixture_of_the_contract(tmp_path):
    got, _, file = run_entry(tmp_path, f"step.skip({fixture('result-skipped')['reason']!r})", context="context-no-upstream")
    assert got == 0 and file.read_text() == wire("result-skipped")


@pytest.mark.parametrize("reason,message", [
    ("", "step.skip() needs the reason, as text"),
    ("   ", "step.skip() needs the reason, as text"),
    (None, "step.skip() needs the reason, as text"),
    ("x" * 301, "the reason of step.skip() has 301 characters; the limit is 300"),
])
def test_a_skip_without_a_usable_reason_fails_the_step_and_says_how_to_write_it(monkeypatch, reason, message):
    begin(monkeypatch, wire("context-no-upstream"))
    with pytest.raises(StepError, match=re.escape(message)):
        step.skip(reason)
    assert not result_file().exists()


def test_a_step_cannot_skip_after_it_handed_on_its_result(monkeypatch):
    begin(monkeypatch, changed("context-no-upstream", produces=[]))
    step.result()
    with pytest.raises(StepError, match=re.escape("step.result() or step.skip() was already called.")):
        step.skip("too late")


# ------------------------------------------------------------------------------------- the record of a run (re-running)
def record_text(lake, name):
    """The text of the record kaos-runs/<run>/<name>.json on main of the app's outputs repository."""
    tree = lake.tree("outputs-hera-demo", lake.head("outputs-hera-demo"))
    return tree.get(f"kaos-runs/hera-demo-x7k2p/{name}.json")


def test_the_result_a_step_hands_on_is_kept_exactly_as_a_record_of_the_run(monkeypatch, lake):
    from kaos_lib import record
    client = lake.client()
    begin(monkeypatch, lake.context("context-one-upstream"), client)
    step.input("labels")
    fill("model")
    step.result(accuracy=0.93)
    assert record.read(client, "hera-demo", "hera-demo-x7k2p", "train") == json.loads(result_file().read_text())
    assert record_text(lake, "train") is not None, "the file is on main of the outputs repository"


def test_a_skipped_step_keeps_its_skipped_result_as_its_record(monkeypatch, lake):
    from kaos_lib import record
    client = lake.client()
    begin(monkeypatch, lake.context("context-no-upstream"), client)
    with pytest.raises(SystemExit) as stop:
        step.skip(fixture("result-skipped")["reason"])
    assert stop.value.code == 0
    assert record.read(client, "hera-demo", "hera-demo-x7k2p", "prepare") == fixture("result-skipped")


def test_a_record_that_cannot_be_saved_is_a_warning_and_the_step_still_succeeds(monkeypatch, lake, capsys):
    client = lake.client()
    begin(monkeypatch, changed("context-no-upstream", produces=[]), client)
    monkeypatch.setattr(client, "merge", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the lake is busy")))
    step.result(rows=3)
    err = capsys.readouterr().err
    assert err.startswith("WARNING: the result of step 'prepare' could not be saved for a later run to reuse "
                          "(RuntimeError: the lake is busy). The step succeeded.")
    assert json.loads(result_file().read_text())["values"] == {"rows": 3}
    assert record_text(lake, "prepare") is None


def test_no_lake_to_save_to_is_the_same_warning(monkeypatch, tmp_path, capsys):
    begin(monkeypatch, changed("context-no-upstream", produces=[]))
    monkeypatch.setattr(step, "_connect", lambda: (_ for _ in ()).throw(StepError("no lake here")))
    step.result()
    assert "WARNING: the result of step 'prepare' could not be saved" in capsys.readouterr().err
    assert result_file().is_file()


def test_a_local_run_and_an_item_of_a_matrix_step_save_no_record(monkeypatch, lake, tmp_path):
    client = lake.client()
    monkeypatch.setenv(step.LOCAL_WORK_ENV, str(tmp_path / "local"))
    monkeypatch.setenv(local.STAGED_ENV, str(tmp_path / "staged"))
    begin(monkeypatch, changed("context-no-upstream", produces=[]), client)
    step.result()
    assert record_text(lake, "prepare") is None
    step.stop()
    monkeypatch.delenv(step.LOCAL_WORK_ENV)
    item = changed("context-matrix-item", produces=[])
    begin(monkeypatch, item, client)
    step.result()
    assert record_text(lake, item["step"]) is None


def an_earlier_model(client, tmp_path):
    """A model written by another run of the app, ``hera-demo-old01``: the commit that holds it."""
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "best.pt").write_bytes(b"old weights")
    from kaos_lib import outputs
    earlier = outputs.RunWriter("hera-demo", "baseline", "hera-demo-old01", "model", client)
    with earlier:
        earlier.save(weights)
        return earlier.finish()


def test_a_model_of_an_earlier_run_is_read_from_the_path_its_write_names(monkeypatch, lake, tmp_path):
    client = lake.client()
    commit = an_earlier_model(client, tmp_path)
    context = lake.context("context-skipped-upstream")
    context["upstream"]["train"]["reads"] = []
    context["upstream"]["train"]["writes"] = [{"name": "model", "type": "model", "repo": "outputs-hera-demo",
                                               "commit": commit, "path": "model/baseline/hera-demo-old01/"}]
    begin(monkeypatch, context, client)
    assert (step.input("model") / "best.pt").read_bytes() == b"old weights"


def test_without_a_path_the_model_is_looked_for_under_the_run_that_reads_it(monkeypatch, lake, tmp_path):
    client = lake.client()
    commit = an_earlier_model(client, tmp_path)
    context = lake.context("context-skipped-upstream")
    context["upstream"]["train"]["reads"] = []
    context["upstream"]["train"]["writes"][0]["commit"] = commit
    begin(monkeypatch, context, client)
    with pytest.raises(StepError, match=r"input 'model': outputs-hera-demo holds no files under "
                                        r"model/baseline/hera-demo-x7k2p/"):
        step.input("model")


def test_a_result_taken_from_an_earlier_run_carries_the_path_of_its_model(monkeypatch):
    got = begin(monkeypatch, wire("context-reused-upstream"))
    assert got.run == "hera-demo-y3m9d"
    train = step.upstream("train")
    assert [w.as_dict() for w in train.writes] == fixture("result-reused")["writes"]
    assert train.writes[0].path == "model/baseline/hera-demo-x7k2p/"
    assert step.skipped("export") == ""
