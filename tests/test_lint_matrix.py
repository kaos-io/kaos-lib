"""``matrix=`` in the linter (L-E06): each thing the render refuses is reported, in the render's words, and a valid
matrix is not. The graph shows a matrix step as one node with its number of items."""
import json
import pathlib

import pytest

from kaos_lib.lint import lint_project
from kaos_lib.lint.constants import STEP_PARAMS
from kaos_lib.lint.graph import build_graph
from lint_corpus import repo, write_repo

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
GOOD = '{"lr": [0.01, 0.001], "batch": [16, 32]}'


def got(tmp_path, body, rule="L-E06", steps=None):
    report = lint_project(str(write_repo(tmp_path, repo(body, steps))))
    return [f for f in report.findings if f.rule == rule]


def messages(tmp_path, body, **kw):
    return [f.message for f in got(tmp_path, body, **kw)]


def train(matrix=GOOD, extra=""):
    return f'    t = step("train", kind="train", matrix={matrix}, produces=[model("m")]{extra})\n'


def test_matrix_is_a_keyword_of_step():
    assert "matrix" in STEP_PARAMS


def test_a_valid_matrix_is_not_reported_by_any_rule(tmp_path):
    body = (train() + '    b = step("pick", kind="evaluate", needs=[t], produces=[artifact("w")])\n'
            '    c = step("report", kind="evaluate", needs=[b], when="train-epochs != 0")\n')
    report = lint_project(str(write_repo(tmp_path, repo(body))))
    assert [f.message for f in report.findings if f.rule in ("L-E05", "L-E06", "L-E07")] == []


@pytest.mark.parametrize("matrix,expect", [
    ("[1, 2]", "matrix= is [1, 2]. Write the values to try for each setting"),
    ("{}", "matrix= is {}. Write the values to try"),
    ('"lr"', "matrix= is 'lr'"),
    ('{"lr": 0.01}', "matrix= gives 'lr' the value 0.01. Give a list with at least one value, for example 'lr': [1, 2]."),
    ('{"lr": []}', "gives 'lr' the value []"),
    ('{"Learning-Rate": [1]}', "matrix= holds the name 'Learning-Rate'. A name is lowercase letters, digits and _"),
    ('{"1lr": [1]}', "matrix= holds the name '1lr'"),
    ('{"lr": [[1]]}', "matrix= value [1] of 'lr' is a list. A value is a number, true or false, or a short text."),
    ('{"lr": [{"a": 1}]}', "is an object"),
    ('{"lr": [None]}', "is empty"),
    ('{"opt": ["a{b"]}', "matrix= value 'a{b' of 'opt' is the text 'a{b'. A text value is 1 to 64 letters, digits"),
    ('{"opt": [""]}', "is the text ''"),
    ('{"opt": ["x" * 65]}', None),
    ('{"a": list(range(5)), "b": [1]}', None),
])
def test_each_matrix_the_render_refuses_is_reported_with_the_fix(tmp_path, matrix, expect):
    found = got(tmp_path, train(matrix))
    if expect is None:        # not a literal: the lint cannot judge it and says nothing
        assert not found
        return
    assert any(expect in f.message for f in found), [f.message for f in found]
    assert all(f.fix for f in found)
    assert all(f.message.startswith("Step 'train': ") for f in found)


def test_more_than_32_combinations_are_refused_with_the_count(tmp_path):
    big = '{"a": [1, 2, 3, 4, 5, 6], "b": [1, 2, 3, 4, 5, 6]}'
    assert any("matrix= makes 36 combinations; a step runs at most 32. Remove values, or split the step." in m
               for m in messages(tmp_path, train(big)))
    assert not messages(tmp_path, train('{"a": [1, 2, 3, 4], "b": [1, 2, 3, 4, 5, 6, 7, 8]}'))      # exactly 32


def test_a_name_that_is_also_a_section_the_step_reads_is_refused(tmp_path):
    out = messages(tmp_path, train('{"train": [1, 2]}', ', reads=["train"]'))
    assert any("matrix= has the name 'train', which is also a section the step reads (reads=). Rename one of them" in m
               for m in out), out


@pytest.mark.parametrize("kind", ["ingest", "publish", "control"])
def test_a_step_that_runs_once_cannot_have_a_matrix(tmp_path, kind):
    out = messages(tmp_path, f'    a = step("a", kind="{kind}", matrix={GOOD})\n')
    assert any(f"a step of kind {kind} runs once, so it cannot have matrix=" in m for m in out), out


@pytest.mark.parametrize("kind", ["transform", "train", "evaluate"])
def test_the_kinds_that_do_work_may_have_a_matrix(tmp_path, kind):
    body = f'    a = step("a", kind="{kind}", matrix={GOOD}, produces=[artifact("r"), model("m")])\n'
    assert not [m for m in messages(tmp_path, body) if "kind" in m]


def test_a_dataset_in_produces_is_refused(tmp_path):
    body = f'    a = step("a", kind="transform", matrix={GOOD}, produces=[dataset("clean")])\n'
    assert any("a step with matrix= cannot produce a dataset: a dataset has one writer and one version per run" in m
               for m in messages(tmp_path, body))


def test_a_matrix_step_that_needs_a_matrix_step_is_refused(tmp_path):
    body = (train() + f'    u = step("use", kind="evaluate", matrix={GOOD}, needs=[t], produces=[artifact("r")])\n')
    out = messages(tmp_path, body)
    assert any("a step with matrix= cannot need another step with matrix=: each combination would need the matching one"
               in m for m in out), out
    assert not any("cannot need" in m for m in messages(tmp_path / "x", train()))


def test_a_when_that_reads_a_value_of_a_matrix_step_is_refused_and_one_on_the_matrix_step_is_not(tmp_path):
    body = (train() + '    p = step("pick", kind="evaluate", needs=[t], when="train.accuracy == 1")\n')
    out = messages(tmp_path, body)
    assert any("when= reads a value of step 'train', which runs once for each combination of its matrix= and so has "
               "no one value" in m for m in out), out
    on_the_matrix_step = f'    t = step("train", kind="train", matrix={GOOD}, when="train-epochs != 0", produces=[model("m")])\n'
    assert not messages(tmp_path / "y", on_the_matrix_step)


def test_the_graph_shows_a_matrix_step_as_one_node_with_its_number_of_items(tmp_path):
    body = (f'    t = step("train", kind="train", matrix={GOOD}, produces=[model("m")])\n'
            '    a = step("plain", kind="evaluate", needs=[t])\n'
            '    g = {"a": [1]}\n    s = step("later", kind="evaluate", matrix=g)\n')
    nodes = build_graph(write_repo(tmp_path, repo(body)))["pipelines"][0]["nodes"]
    assert [n["matrix_items"] for n in nodes] == [4, None, None]
    assert [n["name"] for n in nodes] == ["train", "plain", "later"]
    json.dumps(nodes)


def test_each_matrix_refusal_has_a_place_on_the_rule_page():
    page = (DOCS / "lint" / "L-E06.md").read_text()
    for sentence in ("matrix= is", "matrix= holds the name", "matrix= has the name", "matrix= gives", "matrix= value",
                     "combinations; a step runs at most 32", "runs once, so it cannot have matrix=",
                     "cannot produce a dataset", "cannot need another step with matrix=", "has no one value"):
        assert sentence in page, sentence


# ------------------------------------------------------------------------------ matrix_allow_failed, ledger, needs, ints
def test_matrix_allow_failed_is_a_keyword_of_step():
    assert "matrix_allow_failed" in STEP_PARAMS


def test_matrix_allow_failed_without_matrix_is_refused_in_the_engines_words(tmp_path):
    body = '    t = step("train", kind="train", matrix_allow_failed=True)\n'
    assert messages(tmp_path, body) == ["Step 'train': matrix_allow_failed=True is for a step with matrix=: it lets the "
                                        "step after it run when some items failed. Add matrix=, or remove matrix_allow_failed."]


def test_matrix_allow_failed_that_is_not_a_boolean_is_refused(tmp_path):
    body = '    t = step("train", kind="train", matrix={"lr": [1]}, matrix_allow_failed="yes")\n'
    assert messages(tmp_path, body) == ["Step 'train': matrix_allow_failed='yes' must be True or False."]


def test_matrix_allow_failed_with_matrix_is_fine(tmp_path):
    assert not got(tmp_path, '    t = step("train", kind="train", matrix={"lr": [1]}, matrix_allow_failed=True)\n')
    assert not got(tmp_path, '    t = step("train", kind="train", matrix_allow_failed=False)\n')


def test_a_whole_number_beyond_2_to_the_53_is_refused_and_text_and_floats_are_not(tmp_path):
    assert messages(tmp_path, train('{"seed": [12345678901234567890]}')) == [
        "Step 'train': matrix= value 12345678901234567890 of 'seed' is the number 12345678901234567890, which is beyond "
        "9007199254740992 (2 to the power 53): a number that large cannot be kept exactly. Write it as text, for example "
        '"12345678901234567890".']
    assert not got(tmp_path, train('{"seed": ["12345678901234567890", 1e30, 9007199254740992, True]}'))


def test_more_than_4_things_read_and_written_by_a_matrix_step_is_refused(tmp_path):
    body = ('    t = step("train", kind="train", matrix={"lr": [1]}, inputs=["a", "b", "c"], '
            'produces=[model("m"), model("n")])\n')
    assert messages(tmp_path, body) == [
        "Step 'train': a step with matrix= may read and write at most 4 things in all (inputs= and produces= together; "
        "it has 5): up to 32 items hand back what they read and wrote in one shared result. Read fewer inputs, or join "
        "what the step writes."]
    assert not got(tmp_path, body.replace('"c"', '').replace('"a", "b", ', '"a", "b"').replace('"b"]', '"b"]'))


def test_a_step_that_needs_two_matrix_steps_is_refused(tmp_path):
    body = (train() + '    u = step("other", kind="train", matrix={"k": [1, 2]}, produces=[model("o")])\n'
            '    j = step("join", kind="evaluate", needs=[t, u])\n')
    assert messages(tmp_path, body) == [
        "Step 'join': it needs two steps with matrix= (other, train). The results of all the items of a matrix step "
        "share a large part of a step's context, so a step may need one of them. Put a step between."]


def test_a_step_that_needs_a_matrix_step_may_need_four_steps_in_all(tmp_path):
    plain = "".join(f'    p{i} = step("p{i}", kind="transform")\n' for i in range(4))
    ok = train() + plain + '    j = step("join", kind="evaluate", needs=[t, p0, p1, p2])\n'
    assert not got(tmp_path, ok)
    bad = train() + plain + '    j = step("join", kind="evaluate", needs=[t, p0, p1, p2, p3])\n'
    assert messages(tmp_path / "bad", bad) == [
        "Step 'join': it needs 5 steps, one of them with matrix=; a step that needs a matrix step may need at most 4 "
        "steps in all. The items' results take 56 KiB of its context. Join some of the steps it needs, or put a step "
        "between."]


# ------------------------------------------------------------------------------ L-W08
def w08(tmp_path, body, **kw):
    return messages(tmp_path, body, rule="L-W08", **kw)


FAILED = '    t = step("train", kind="train", matrix={"lr": [1, 2]}, matrix_allow_failed=True, produces=[model("m")])\n'


def test_a_dataset_step_right_after_an_allowed_failure_is_warned_about(tmp_path):
    found = w08(tmp_path, FAILED + '    s = step("scores", kind="evaluate", needs=[t], produces=[dataset("scores")])\n')
    assert len(found) == 1 and "matrix_allow_failed=True" in found[0] and "('scores')" in found[0]
    assert "become the latest one" in found[0]


def test_a_dataset_step_two_steps_after_is_warned_about_too(tmp_path):
    body = (FAILED + '    b = step("pick", kind="evaluate", needs=[t], produces=[artifact("w")])\n'
            '    s = step("scores", kind="evaluate", needs=[b], produces=[dataset("scores")])\n')
    assert len(w08(tmp_path, body)) == 1


def test_no_warning_without_a_dataset_after_or_without_the_allowance(tmp_path):
    assert not w08(tmp_path / "a", FAILED + '    b = step("pick", kind="evaluate", needs=[t], produces=[artifact("w")])\n')
    unrelated = FAILED + '    s = step("scores", kind="transform", produces=[dataset("scores")])\n'
    assert not w08(tmp_path / "b", unrelated)
    plain = train() + '    s = step("scores", kind="evaluate", needs=[t], produces=[dataset("scores")])\n'
    assert not w08(tmp_path / "c", plain)
