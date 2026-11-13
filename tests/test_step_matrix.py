"""A step with ``matrix=`` (contract section 12): the item's values as settings, one output for each item, the list
the step after it gets, and what is refused."""
import json
import pathlib
import sys

import pytest

from kaos_lib import lock, step
from kaos_lib.errors import StepError

FIXTURES = pathlib.Path(__file__).with_name("contract_fixtures")


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def one_step_per_test(tmp_path, monkeypatch):
    monkeypatch.setattr(step, "WORK", str(tmp_path / "work"))
    monkeypatch.setattr(step, "RESULT_FILE", str(tmp_path / "work" / "output" / "kaos-result.json"))
    monkeypatch.setattr(sys, "exit", sys.exit)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    yield
    step.stop()


def begin(monkeypatch, context, client=None):
    monkeypatch.setenv(step.ENV, lock.wire(context))
    if client is not None:
        monkeypatch.setattr(step, "_connect", lambda: client)
    return step.start()


def parse_error(context):
    with pytest.raises(StepError) as err:
        step.parse(lock.wire(context))
    return str(err.value)


def item_context(**matrix):
    context = fixture("context-matrix-item")
    context["matrix"] = {**context["matrix"], **matrix}
    return context


# ------------------------------------------------------------------------------------------- the item's context
def test_the_item_knows_which_one_it_is_and_reads_its_values_as_settings(monkeypatch):
    got = begin(monkeypatch, fixture("context-matrix-item"))
    assert (got.matrix.index, got.matrix.of, got.matrix.values) == (1, 4, {"batch": 16, "lr": 0.001})
    assert got.params["lr"] == 0.001 and got.params["batch"] == 16
    assert got.params["train"] == {"epochs": 3, "lr": 0.001}          # the settings are unchanged beside them


def test_a_step_without_matrix_has_none(monkeypatch):
    got = begin(monkeypatch, fixture("context-one-upstream"))
    assert got.matrix is None


def test_a_matrix_name_that_is_also_a_setting_is_refused_and_both_are_named():
    context = fixture("context-matrix-item")
    context["params"]["lr"] = 0.5
    message = parse_error(context)
    assert "'lr'" in message and "matrix=" in message and "params['lr']" in message and "Rename one of them" in message


@pytest.mark.parametrize("matrix,message", [
    ("x", "matrix is not an object"),
    ({"index": 1, "of": 0, "values": {"a": 1}}, "of 0; a step with matrix= has 1 to 32 items"),
    ({"index": 1, "of": 33, "values": {"a": 1}}, "of 33"),
    ({"index": 4, "of": 4, "values": {"a": 1}}, "index 4; it is a whole number from 0 to 3"),
    ({"index": -1, "of": 4, "values": {"a": 1}}, "index -1"),
    ({"index": True, "of": 4, "values": {"a": 1}}, "index True"),
    ({"index": 0, "of": 4, "values": {}}, "values that are not names"),
    ({"index": 0, "of": 4, "values": {"a": [1]}}, "values that are not names"),
    ({"index": 0, "of": 4}, "values that are not names"),
])
def test_a_matrix_that_cannot_be_read_is_refused_with_the_field_named(matrix, message):
    context = fixture("context-matrix-item")
    context["matrix"] = matrix
    assert message in parse_error(context)


def test_a_step_with_matrix_that_produces_a_dataset_is_refused():
    context = fixture("context-matrix-item")
    context["produces"] = [{"name": "clean", "type": "dataset", "repo": "dataset-hera-demo-clean"}]
    message = parse_error(context)
    assert "has matrix= and produces a dataset" in message and "Produce a model or an artifact" in message


# ------------------------------------------------------------------------------------------- the list upstream
def test_the_step_after_a_matrix_step_gets_a_list_in_index_order(monkeypatch):
    begin(monkeypatch, fixture("context-matrix-upstream"))
    items = step.upstream("train")
    assert isinstance(items, list) and [i.index for i in items] == [0, 1, 2, 3]
    assert [i.status for i in items] == ["ok", "failed", "skipped", "ok"]
    assert items[0].matrix == {"lr": 0.01, "batch": 16} and items[0].step == "train"
    assert items[0].values == {"accuracy": 0.93, "best_epoch": 2}
    assert [w.as_dict() for w in items[0].writes] == fixture("result-matrix")["items"][0]["result"]["writes"]
    assert [r.name for r in items[0].reads] == ["labels", "embeddings"]




def test_a_failed_item_has_no_values_and_a_skipped_one_has_its_reason(monkeypatch):
    begin(monkeypatch, fixture("context-matrix-upstream"))
    failed, skipped = step.upstream("train")[1:3]
    assert (failed.values, failed.reads, failed.writes, failed.reason) == ({}, (), (), "")
    assert skipped.reason == "the loss did not move in the first epoch" and skipped.values == {}


def test_the_best_item_can_be_picked_from_the_list(monkeypatch):
    begin(monkeypatch, fixture("context-matrix-upstream"))
    ok = [i for i in step.upstream("train") if i.status == "ok"]
    assert [i.index for i in ok] == [0, 3]


def test_a_matrix_step_that_was_skipped_as_a_whole_is_absent(monkeypatch):
    context = fixture("context-matrix-upstream")
    context["upstream"]["train"] = {"version": 1, "status": "absent"}
    begin(monkeypatch, context)
    assert step.upstream("train", optional=True) is None
    with pytest.raises(StepError, match="step 'train' did not run"):
        step.upstream("train")


@pytest.mark.parametrize("change,message", [
    (lambda e: e.update(items=[]), "has no items"),
    (lambda e: e.update(items="x"), "has no items"),
    (lambda e: e["items"].reverse(), "must be the item with index 0"),
    (lambda e: e["items"][0].update(status="done"), "has status 'done'"),
    (lambda e: e["items"][2].pop("reason"), "is skipped and has no reason"),
    (lambda e: e["items"][0].pop("result"), "items[0].result is not a result at version 1"),
    (lambda e: e["items"][0].update(values="x"), "has no matrix values"),
    (lambda e: e["items"][0]["result"].update(values=None), "has no values"),
])
def test_a_list_that_cannot_be_read_is_refused_with_the_item_named(change, message):
    context = fixture("context-matrix-upstream")
    change(context["upstream"]["train"])
    assert message in parse_error(context)


# ------------------------------------------------------------------------------------------- reading an item's output
def test_input_without_item_says_which_to_choose(monkeypatch):
    begin(monkeypatch, fixture("context-matrix-upstream"))
    with pytest.raises(StepError) as err:
        step.input("model")
    text = str(err.value)
    assert "written by each of the 4 items of step 'train'" in text and "step.input('model', item=N)" in text


def test_input_with_an_item_that_failed_or_is_missing_says_so(monkeypatch):
    begin(monkeypatch, fixture("context-matrix-upstream"))
    with pytest.raises(StepError, match="item 1 of step 'train' has status 'failed', so it wrote no 'model'"):
        step.input("model", item=1)
    with pytest.raises(StepError, match="the items 0 to 3; there is no item 7"):
        step.input("model", item=7)
    with pytest.raises(StepError, match="item= of input\\('model'\\) is '1'"):
        step.input("model", item="1")


def test_item_on_an_output_of_a_step_without_matrix_is_refused(monkeypatch):
    begin(monkeypatch, fixture("context-skipped-upstream"))
    with pytest.raises(StepError, match="written by step 'train', which has no matrix=. Remove item="):
        step.input("model", item=0)


def test_item_on_a_dataset_input_is_refused(monkeypatch):
    begin(monkeypatch, fixture("context-no-upstream"))
    with pytest.raises(StepError, match="a dataset input of step .*Remove item="):
        step.input("raw", item=0)


@pytest.fixture
def lake(fake):
    """A lakeFS with the repositories of the fixtures, and the matrix context at their real commits."""
    labels = fake.add_repo("dataset-labels", metadata={"kaos.kind": "dataset"}, files={"labels.csv": b"x,y\n"})
    made = fake.add_repo("dataset-hera-demo-embeddings", metadata={"kaos.kind": "dataset"}, files={"e.npy": b"emb"})
    fake.add_repo("outputs-hera-demo", metadata={"kaos.kind": "outputs", "kaos.app": "hera-demo"})
    fake.commits = {"2" * 64: labels, "3" * 64: made}
    return fake


def run_item(monkeypatch, lake, index, values, tmp_path, files=None, of=4, **given):
    """One item of the step of the fixture, run against the fake lakeFS; returns the result it wrote."""
    context = fixture("context-matrix-item")
    text = json.dumps(context)
    for old, new in lake.commits.items():
        text = text.replace(old, new)
    context = json.loads(text)
    context["matrix"] = {"index": index, "of": of, "values": values}
    context["produces"] = [{"name": "model", "type": "model", "repo": "outputs-hera-demo"}]
    context["upstream"] = {}
    context["ledger"]["reads"] = []
    lock.reset()
    begin(monkeypatch, context, lake.client())
    folder = step.output("model")
    for rel, data in (files or {"weights.bin": b"w%d" % index}).items():
        (folder / rel).write_bytes(data)
    step.result(**(given or {"accuracy": 0.5 + index / 10}))
    got = json.loads(pathlib.Path(step.RESULT_FILE).read_text())
    step.stop()
    return got


def test_each_item_writes_under_its_own_index_and_branch_and_commit(monkeypatch, lake, tmp_path):
    first = run_item(monkeypatch, lake, 0, {"lr": 0.01, "batch": 16}, tmp_path)
    second = run_item(monkeypatch, lake, 1, {"lr": 0.001, "batch": True}, tmp_path)
    tree = lake.tree("outputs-hera-demo", lake.head("outputs-hera-demo"))
    assert set(tree) == {"model/baseline/hera-demo-x7k2p/0/weights.bin", "model/baseline/hera-demo-x7k2p/1/weights.bin"}
    assert first["writes"][0]["commit"] != second["writes"][0]["commit"]
    meta = lake.commit_meta("outputs-hera-demo", second["writes"][0]["commit"])[1]
    assert meta["kaos.matrix.index"] == "1" and meta["kaos.matrix.lr"] == "0.001" and meta["kaos.matrix.batch"] == "true"
    assert meta["kaos.step"] == "train" and meta["kind"] == "model"
    other = lake.commit_meta("outputs-hera-demo", first["writes"][0]["commit"])[1]
    assert other["kaos.matrix.index"] == "0" and other["kaos.matrix.batch"] == "16"


def test_the_branch_of_an_item_has_its_index():
    from kaos_lib import writer
    assert writer.run_branch("hera-demo-x7k2p", "train", "model-1") == "run-hera-demo-x7k2p-train-model-1"


def test_the_next_step_reads_the_output_of_the_item_it_names(monkeypatch, lake, tmp_path):
    first = run_item(monkeypatch, lake, 0, {"lr": 0.01, "batch": 16}, tmp_path)
    second = run_item(monkeypatch, lake, 3, {"lr": 0.001, "batch": 32}, tmp_path, files={"weights.bin": b"three"})
    context = fixture("context-matrix-upstream")
    text = json.dumps(context)
    for old, new in lake.commits.items():
        text = text.replace(old, new)
    context = json.loads(text)
    items = context["upstream"]["train"]["items"]
    items[0]["result"]["writes"][0]["commit"] = first["writes"][0]["commit"]
    items[3]["result"]["writes"][0]["commit"] = second["writes"][0]["commit"]
    begin(monkeypatch, context, lake.client())
    assert (step.input("model", item=0) / "weights.bin").read_bytes() == b"w0"
    assert (step.input("model", item=3) / "weights.bin").read_bytes() == b"three"


# ------------------------------------------------------------------------------------------- the result cap
@pytest.mark.parametrize("of,cap", [(1, 8192), (2, 8192), (3, 5461), (4, 4096), (32, 512)])
def test_the_share_of_an_item_is_the_smaller_of_8_kib_and_16_kib_divided_by_the_items(of, cap):
    assert step._max_item_values(of) == cap
    assert step.MATRIX_VALUES_CAP == 16384


def test_values_over_the_share_of_an_item_name_the_share_and_the_fix(monkeypatch):
    context = item_context(of=32)
    context["produces"] = []
    begin(monkeypatch, context)
    with pytest.raises(StepError) as err:
        step.result(note="x" * 600)
    text = str(err.value)
    assert "the values of this result cost" in text and "the limit for one item is 512" in text
    assert "The 32 items of a step with matrix= share 16384 for their values" in text
    assert "the smaller of 8192 and 16384 divided by 32" in text and "The largest value is 'note'" in text
    assert "log metrics to MLflow" in text


def test_only_the_values_count_against_the_share_not_what_the_item_read_and_wrote(monkeypatch, lake, tmp_path):
    got = run_item(monkeypatch, lake, 0, {"lr": 0.01, "batch": 16}, tmp_path, of=32, note="x" * 400)
    assert lock.cost(lock.wire(got["values"])) <= 512 < lock.cost(lock.wire(got))     # the ledger is not in the share


def test_a_result_that_fits_the_share_but_not_the_whole_result_is_refused_at_8_kib(monkeypatch):
    context = item_context(of=1, index=0)
    context["produces"] = []
    begin(monkeypatch, context)
    with pytest.raises(StepError) as err:
        step.result(note="x" * 9000)
    assert "the limit for one item is 8192" in str(err.value)


# ------------------------------------------------------------------------------------------- numbers and order
def test_numbers_keep_their_type_and_values_their_order(monkeypatch):
    context = item_context()
    text = lock.wire(context).replace('"lr":0.001', '"lr":1.0').replace('"batch":16', '"batch":12345678901234567')
    monkeypatch.setenv(step.ENV, text)
    got = step.start()
    assert list(got.matrix.values) == ["lr", "batch"]
    assert got.matrix.values["lr"] == 1.0 and type(got.matrix.values["lr"]) is float
    assert got.params["batch"] == 12345678901234567 and type(got.params["batch"]) is int


def test_a_number_beyond_2_to_the_53_is_refused_by_the_local_run_helper(tmp_path):
    from kaos_lib import testing
    with pytest.raises(ValueError, match="beyond 9007199254740992 .*Write it as text"):
        testing.local_context(run="r", app="a", step_name="train", kind="train", experiment="e", params={}, reads=[],
                              produces=[], upstream={}, matrix={"index": 0, "of": 1, "values": {"seed": 2 ** 53 + 1}})


def test_the_values_of_a_local_item_keep_the_order_of_the_axes():
    from kaos_lib import testing
    context = testing.local_context(run="r", app="a", step_name="train", kind="train", experiment="e", params={},
                                    reads=[], produces=[], upstream={},
                                    matrix={"index": 0, "of": 1, "values": {"lr": 0.1, "batch": 16}})
    assert list(context["matrix"]["values"]) == ["lr", "batch"]


# ------------------------------------------------------------------------------------------- the testing helper
def train_main():
    ctx = step.start()
    (step.output("model") / "w.txt").write_text(f"{ctx.params['lr']}/{ctx.params['batch']}")
    step.result(accuracy=ctx.params["lr"] * 10, index=ctx.matrix.index)


def pick_main():
    step.start()
    best = max((i for i in step.upstream("train") if i.status == "ok"), key=lambda i: i.values["accuracy"])
    out = step.output("winner") / "which.txt"
    out.write_text((step.input("model", item=best.index) / "w.txt").read_text())
    step.result(winner=best.index, tried=len(step.upstream("train")), failed=[i.index for i in step.upstream("train") if i.status == "failed"])


def test_testing_runs_an_item_with_its_values_as_settings(tmp_path):
    from kaos_lib import testing
    with testing.running(tmp_path, name="train", produces=[("model", "model")], matrix={"lr": 0.05, "batch": 16},
                         matrix_index=2, matrix_of=4) as run:
        train_main()
    assert run.result["values"] == {"accuracy": 0.5, "index": 2}
    assert (run.output("model", item=2) / "w.txt").read_text() == "0.05/16"


def test_testing_gives_the_step_after_it_a_list_of_items(tmp_path):
    from kaos_lib import testing
    folders = []
    for i, lr in enumerate((0.01, 0.1, 0.03)):
        with testing.running(tmp_path / f"item{i}", name="train", produces=[("model", "model")],
                             matrix={"lr": lr, "batch": 8}, matrix_index=i, matrix_of=3) as run:
            train_main()
        folders.append(run.output("model", item=i))
    items = [{"matrix": {"lr": 0.01, "batch": 8}, "values": {"accuracy": 0.1}, "writes": {"model": folders[0]}},
             {"matrix": {"lr": 0.1, "batch": 8}, "status": "failed"},
             {"matrix": {"lr": 0.03, "batch": 8}, "values": {"accuracy": 0.3}, "writes": {"model": folders[2]},
              "reads": {"labels": "dataset-labels@v1"}}]
    with testing.running(tmp_path / "pick", name="pick-best", kind="evaluate", produces=[("artifact", "winner")],
                         upstream_matrix={"train": items}) as run:
        pick_main()
    assert run.result["values"] == {"winner": 2, "tried": 3, "failed": [1]}
    assert (run.output("winner") / "which.txt").read_text() == "0.03/8"


def test_testing_refuses_an_item_it_does_not_understand(tmp_path):
    from kaos_lib import testing
    with pytest.raises(ValueError, match="upstream_matrix 'train' item 0"):
        with testing.running(tmp_path, upstream_matrix={"train": [{"colour": "red"}]}):
            pass
    with pytest.raises(ValueError, match="status"):
        with testing.running(tmp_path, upstream_matrix={"train": [{"status": "done"}]}):
            pass


def test_testing_shows_a_skipped_item_with_its_reason(tmp_path):
    from kaos_lib import testing
    with testing.running(tmp_path, name="pick-best", kind="evaluate",
                         upstream_matrix={"train": [{"matrix": {"lr": 1}, "status": "skipped", "reason": "no progress"},
                                                    {"matrix": {"lr": 2}}]}):
        step.start()
        first, second = step.upstream("train")
        assert (first.status, first.reason, second.status, second.values) == ("skipped", "no progress", "ok", {})


def test_a_whole_number_beyond_2_to_the_53_in_an_items_result_is_refused_with_the_fix(monkeypatch, lake, tmp_path):
    """The step after a matrix step gets the items' results through the workflow system, which writes a number as a
    float: beyond 2 to the power 53 it would change silently, so the item is told before it saves anything."""
    with pytest.raises(StepError) as exc:
        run_item(monkeypatch, lake, 0, {"lr": 0.1}, tmp_path, seed=2 ** 53 + 1)
    message = str(exc.value)
    assert "result value 'seed'" in message and "9007199254740993" in message and 'Write it as text, for example "9007199254740993"' in message
    step.stop()
    got = run_item(monkeypatch, lake, 0, {"lr": 0.1}, tmp_path, seed=2 ** 53, nested=[{"n": -(2 ** 53)}], text="9007199254740993")
    assert got["values"]["seed"] == 2 ** 53
