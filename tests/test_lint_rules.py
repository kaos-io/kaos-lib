"""Every rule of the pipeline linter fires on its own fixture and stays silent on its clean twin (PRD-CONSOLE-1682
AC-23), with the expected level, range, fix hint and a documentation page that exists."""
import pathlib

import pytest

from kaos_lib.lint import ALL_RULES, lint_project
from lint_corpus import CASES, PLAIN_STEP, repo, write_repo

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "lint"
LEVELS = {"E": "error", "W": "warning", "I": "info"}


def run(tmp_path, files, catalogue):
    return lint_project(write_repo(tmp_path, files), catalogue)


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_should_fire_on_its_fixture_and_stay_silent_on_the_clean_twin(rule_id, tmp_path):
    failing, clean, catalogue, (line, text) = CASES[rule_id]
    hit = [f for f in run(tmp_path / "fail", failing, catalogue).findings if f.rule == rule_id]
    assert hit, f"{rule_id} did not fire"
    finding = hit[0]
    assert finding.level == LEVELS[rule_id[2]]
    assert finding.span.line == line and text in finding.message
    assert finding.fix and finding.doc.endswith(f"/{rule_id}.html")
    assert not [f for f in run(tmp_path / "pass", clean, catalogue).findings if f.rule == rule_id]


def test_should_report_l_i03_as_skipped_because_schedules_do_not_exist_yet(tmp_path):
    report = run(tmp_path, CASES["L-E06"][1], None)
    assert [s.rule for s in report.skipped if s.rule == "L-I03"] == ["L-I03"]
    assert not [f for f in report.findings if f.rule == "L-I03"]


def test_every_rule_has_a_documentation_page():
    for rule in ALL_RULES:
        page = DOCS / f"{rule.id}.md"
        assert page.is_file(), rule.id
        text = page.read_text()
        assert rule.name in text and rule.level in text.lower()


def test_every_rule_is_in_the_corpus_or_documented_as_inactive():
    ids = {r.id for r in ALL_RULES if not r.id.startswith("L-D")}   # the L-D rules have their own corpus
    assert ids - set(CASES) == {"L-E00", "L-I03"}


# --- the variants of the rules that have several ways to fire ------------------------------------------------

def messages(tmp_path, body, steps=None, catalogue=None, rule=None, config=None):
    from lint_corpus import repo
    report = run(tmp_path, repo(body, steps, config), catalogue)
    return [f.message for f in report.findings if rule is None or f.rule == rule]


@pytest.mark.parametrize("body,expect", [
    ('    a = step("a", kind="evaluate", needs=[ghost])\n', "not defined anywhere"),
    ('    a = step("a", kind="evaluate", needs=["b"])\n    b = step("b", kind="evaluate")\n', "as text"),
    ('    a = step("a", kind="evaluate")\n    b = step("a", kind="evaluate")\n', "Two steps are named 'a'"),
    ('    a = step("Bad_Name")\n', "not valid"),
    ('    a = step("a", kind="evaluate", reads=["nope"])\n', "does not exist in config/"),
    ('    a = step("a", kind="evaluate")\n    a2 = step("c", kind="evaluate", needs=[a2])\n', "defined after it"),
])
def test_should_report_each_dependency_or_producer_problem(tmp_path, body, expect):
    assert any(expect in m for m in messages(tmp_path, body, rule="L-E05")), body


def test_should_not_report_a_dependency_it_cannot_resolve_statically(tmp_path):
    body = '    a = step("a", kind="evaluate")\n    prev = [a]\n    b = step("b", kind="evaluate", needs=prev)\n    c = step("c", kind="evaluate", needs=[a])\n'
    assert not messages(tmp_path, body, rule="L-E05")


def test_should_report_a_cycle_in_raw_hera_depends(tmp_path):
    body = '    x = Task(name="x", depends="y")\n    y = Task(name="y", depends="x.Succeeded")\n'
    assert any("depends on itself" in m for m in messages(tmp_path, body, rule="L-E05"))


@pytest.mark.parametrize("body,expect", [
    ('    a = step("a", kind="evaluate", hpc_time_limit="2h", gpu=True)\n', "hpc_time_limit= is gone. Use walltime="),
    ('    a = step("a", kind="evaluate", outputs=["metrics"])\n', "outputs= is gone. Declare what the step writes with produces="),
    ('    a = step("a", kind="evaluate", walltime="2 hours", gpu=True)\n', "must be minutes or hours"),
    ('    a = step("a", kind="evaluate", resumable="soon", gpu=True)\n', "resumable='soon'"),
    ('    a = step("a", kind="evaluate", checkpoint_every=0, gpu=True)\n', "checkpoint_every=0"),
    ('    a = step("a", kind="evaluate", idle_timeout="never", gpu=True)\n', "idle_timeout='never'"),
    ('    a = step()\n', "without a name"),
])
def test_should_report_each_argument_step_refuses(tmp_path, body, expect):
    assert any(expect in m for m in messages(tmp_path, body, rule="L-E06")), body


def test_should_accept_the_arguments_step_accepts(tmp_path):
    body = ('    a = step("a", kind="evaluate", gpu=True, walltime="12h", resumable="20m", checkpoint_every="1h", '
            'idle_timeout=0, when="experiment-name != x")\n    b = step("b", kind="evaluate", resumable=False, checkpoint_every=False)\n')
    assert not messages(tmp_path, body, rule="L-E06")


@pytest.mark.parametrize("body,expect", [
    ('    c = Container(name="c", pod_spec_patch="{}")\n', "patches a pod"),
    ('    c = Container(name="c", executor=Executor(service_account_name="x"))\n', "service account"),
    ('    c = {"serviceAccountName": "x"}\n', "service account"),
    ('    c = Container(name="hpc-follower")\n', "reserves"),
    ('    c = step("meluxina-run", kind="evaluate")\n', "reserves"),
])
def test_should_report_each_client_identity_form(tmp_path, body, expect):
    assert any(expect in m for m in messages(tmp_path, body, rule="L-E04")), body


def test_should_not_flag_the_same_reserved_name_twice(tmp_path):
    assert len(messages(tmp_path, '    c = step(name="hpc-follower")\n', rule="L-E04")) == 1


def test_l_e01_does_not_fire_when_the_step_is_resumable_or_its_code_uses_checkpoints(tmp_path):
    from lint_corpus import CHECKPOINT_STEP, NO_PROGRESS, with_evidence
    body = '    t = step("work", kind="evaluate", gpu=True, walltime="72h")\n'
    failing = with_evidence(("work", False, NO_PROGRESS))
    assert messages(tmp_path / "a", body, {"work": "def f(): pass\n"}, failing, rule="L-E01")
    assert not messages(tmp_path / "b", body, {"work": CHECKPOINT_STEP}, rule="L-E01")
    assert not messages(tmp_path / "c", '    t = step("work", kind="evaluate", gpu=True, walltime="72h", resumable=True)\n',
                        {"work": "def f(): pass\n"}, failing, rule="L-E01")


def test_l_e01_follows_the_catalogues_lane_maximum(tmp_path):
    from lint_corpus import with_lane
    body = '    t = step("work", kind="evaluate", gpu=True, walltime="72h", resumable=False)\n'
    assert not messages(tmp_path / "a", body, {"work": "x = 1\n"}, with_lane(5 * 1440), rule="L-E01")
    assert messages(tmp_path / "b", body, {"work": "x = 1\n"}, with_lane(60), rule="L-E01")


def test_w01_stays_quiet_when_l_e01_already_reports_the_step(tmp_path):
    body = '    t = step("work", kind="evaluate", gpu=True, walltime="72h", resumable=False)\n'
    assert not messages(tmp_path, body, {"work": "x = 1\n"}, rule="L-W01")


def test_w04_reports_a_pipeline_that_never_registers_a_model(tmp_path):
    from lint_corpus import CHECKPOINT_STEP
    out = messages(tmp_path, '    t = step("train-x", kind="evaluate", gpu=True, reads=["train"])\n', {"train-x": CHECKPOINT_STEP},
                   rule="L-W04")
    assert any("registers a model" in m for m in out)


@pytest.mark.parametrize("text", ["dataset-default@latest", "dataset-default@v3", "dataset-default@" + "a" * 40])
def test_w03_reports_a_dataset_version_named_in_step_code(tmp_path, text):
    code = f"REF = '{text}'\n"
    assert any("names a dataset and a version" in m
               for m in messages(tmp_path, '    a = step("a", kind="evaluate")\n', {"a": code}, rule="L-W03"))


@pytest.mark.parametrize("config", ["dataset: dataset-default@latest\n", "dataset: dataset-default\n",
                                    "dataset: dataset-default@v1\n"])
def test_w03_leaves_the_default_version_in_config_alone(tmp_path, config):
    from lint_corpus import CONFIG
    got = messages(tmp_path, '    a = step("a", kind="evaluate", reads=["dataset"])\n',
                   config={**CONFIG, "config/dataset.yaml": config}, rule="L-W03")
    assert got == []


@pytest.mark.parametrize("kw", ['walltime="2h"', "resumable=True", 'checkpoint_every="20m"', 'idle_timeout="40m"'])
def test_a_step_without_a_gpu_may_declare_what_the_engine_accepts_for_every_step(tmp_path, kw):
    assert messages(tmp_path, f'    a = step("a", kind="evaluate", {kw})\n', rule="L-E06") == []


# --- authoring flows: folders, names, one-name rule, conditions on a step's value, loops ------------------------

def test_a_dataset_name_under_three_characters_is_refused_before_render(tmp_path):
    out = messages(tmp_path, '    a = step("a", kind="ingest", produces=[dataset("x")])\n', {"a": ""}, rule="L-E07")
    assert any("the dataset name 'x' is too short. A dataset name has 3 to 40 characters" in m for m in out), out


def test_an_input_that_is_also_an_output_of_the_same_step_is_refused_with_the_fix(tmp_path):
    body = '    a = step("a", kind="transform", inputs=["dataset"], produces=[dataset("dataset")])\n'
    found = [f for f in run(tmp_path, repo(body, {"a": ""}), None).findings if f.rule == "L-E07"]
    assert any("'dataset' is both an input (inputs=) and one of its own outputs (produces=)" in f.message
               and "previous-dataset" in f.fix for f in found), found


def test_a_step_without_its_folder_names_the_folder_and_the_underscore_rule(tmp_path):
    found = [f for f in run(tmp_path, repo('    a = step("model-eval", kind="evaluate")\n', {"other": ""}), None).findings
             if f.rule == "L-E07" and "folder" in f.message]
    assert found and "has no folder steps/model_eval/." in found[0].message
    assert "every hyphen written as an underscore" in found[0].message and "Create steps/model_eval/" in found[0].fix


def test_a_hyphen_folder_is_named_in_the_message(tmp_path):
    files = repo('    a = step("model-eval", kind="evaluate")\n', {"other": ""})
    files["steps/model-eval/Dockerfile"] = "FROM scratch\n"
    found = [f for f in run(tmp_path, files, None).findings if f.rule == "L-E07" and "folder" in f.message]
    assert found and "There is a folder steps/model-eval/: rename it to steps/model_eval/." in found[0].message


def test_a_step_with_its_folder_and_a_repository_without_steps_are_not_judged(tmp_path):
    ok = repo('    a = step("model-eval", kind="evaluate")\n', {"model-eval": ""})
    assert not [f for f in run(tmp_path / "a", ok, None).findings if "no folder" in f.message]
    bare = {k: v for k, v in repo('    a = step("model-eval", kind="evaluate")\n').items() if not k.startswith("steps/")}
    assert not [f for f in run(tmp_path / "b", bare, None).findings if "no folder" in f.message]


def test_a_config_file_with_several_top_level_keys_gives_each_one_as_a_section(tmp_path):
    config = {"config/config.yaml": "defaults:\n  - scenarios\n", "config/scenarios.yaml": "source:\n  a: 1\ntrain:\n  b: 2\n"}
    body = '    a = step("a", kind="evaluate", reads=["source", "train"])\n'
    assert not messages(tmp_path / "a", body, {"a": ""}, rule="L-E05", config=config)
    assert any("does not exist in config/" in m for m in
               messages(tmp_path / "b", '    a = step("a", kind="evaluate", reads=["nope"])\n', {"a": ""}, rule="L-E05", config=config))


def test_a_train_step_that_declares_checkpoint_every_is_not_told_it_is_not_resumable(tmp_path):
    body = '    t = step("work", kind="train", walltime="12h", checkpoint_every="10m", produces=[model("m")])\n'
    assert not messages(tmp_path, body, {"work": PLAIN_STEP}, rule="L-W06")


def test_a_step_built_in_a_loop_is_named_by_its_line_not_by_a_python_object(tmp_path):
    out = messages(tmp_path, '    for i in range(2):\n        step(f"t-{i}", kind="evaluate", gpu=True)\n', rule="L-I01")
    assert out and all("The step built at line 5 declares no time limit" in m and "object" not in m for m in out), out


@pytest.mark.parametrize("when,expect", [
    ("evaluate.passed == true", None),
    ("evaluate.passed == true and experiment-name != off", None),
    ("score > 0.5", "is not a condition the platform can read. A condition compares one name with a text, with == or != and nothing else"),
    ("evaluate.pass-rate == 1", "is not a name step.result() could have been given"),
    ("other.passed == true", "reads a value of step 'other', which this step does not need"),
])
def test_when_on_a_value_of_a_needed_step(tmp_path, when, expect):
    body = (f'    e = step("evaluate", kind="evaluate")\n    o = step("other", kind="evaluate")\n'
            f'    p = step("publish", kind="publish", needs=[e], when="{when}")\n')
    out = messages(tmp_path, body, {"evaluate": "", "other": "", "publish": ""}, rule="L-E06") \
        + messages(tmp_path / "x", body, {"evaluate": "", "other": "", "publish": ""}, rule="L-E07")
    if expect is None:
        assert not [m for m in out if "when" in m], out
    else:
        assert any(expect in m for m in out), out


# --- a value is compared exactly; a line break in when=; one name for one thing across needed steps ----------------

def when_body(condition):
    return ('    e = step("evaluate", kind="evaluate")\n'
            '    p = step("publish", kind="publish", needs=[e], when="' + condition + '")\n')


@pytest.mark.parametrize("written, said", [
    ("1e400", "too large"), (".5", "looks like a number"), ("+1", "looks like a number"), ("01", "looks like a number"),
    ("5.", "looks like a number"), ("True", "write true in lowercase"), ("NULL", "write null in lowercase"),
    ("9007199254740993", "an integer above 9007199254740992"),
])
def test_a_text_compared_with_a_steps_value_that_cannot_be_matched_reliably_is_refused(tmp_path, written, said):
    out = messages(tmp_path, when_body(f"evaluate.rows == '{written}'"), {"evaluate": "", "publish": ""}, rule="L-E06")
    assert any("cannot be matched reliably" in m and said in m for m in out), out


@pytest.mark.parametrize("written", ["1000000", "1e6", "1.0", "0.5", "-3", "1e-5", "true", "false", "abc", "9007199254740992"])
def test_a_text_that_can_be_matched_is_accepted(tmp_path, written):
    out = messages(tmp_path, when_body(f"evaluate.rows != '{written}'"), {"evaluate": "", "publish": ""}, rule="L-E06")
    assert not [m for m in out if "when" in m], out


def test_a_line_break_in_when_is_refused(tmp_path):
    body = '    p = step("publish", kind="publish", when="experiment-name == a\\nand experiment-name == b")\n'
    out = messages(tmp_path, body, {"publish": ""}, rule="L-E06")
    assert any("holds a control character" in m for m in out), out


def test_a_step_that_writes_a_name_a_needed_step_writes_is_refused(tmp_path):
    body = ('    a = step("first", kind="transform", produces=[artifact("report")])\n'
            '    b = step("second", kind="transform", needs=[a], produces=[artifact("report")])\n')
    out = messages(tmp_path, body, {"first": "", "second": ""}, rule="L-E07")
    assert any("report is both something the step it needs, 'a', produces and one of its own outputs (produces=)" in m
               for m in out), out


@pytest.mark.parametrize("walltime", ["721h", "43201", "43201m", "0m", "0"])
def test_a_walltime_the_form_would_refuse_is_refused_by_lint_with_composes_sentence(tmp_path, walltime):
    body = f'    a = step("train", kind="evaluate", walltime="{walltime}")\n'
    out = messages(tmp_path, body, {"train": ""}, rule="L-E06")
    assert any(f"train-walltime is '{walltime}'. Write minutes or hours, for example 90, 90m or 12h: at least one minute, "
               "at most 30 days, no other unit." in m for m in out), out


@pytest.mark.parametrize("walltime", ["720h", "43200", "1m"])
def test_a_walltime_up_to_thirty_days_is_accepted_by_lint(tmp_path, walltime):
    body = f'    a = step("train", kind="evaluate", walltime="{walltime}")\n'
    assert not [m for m in messages(tmp_path, body, {"train": ""}, rule="L-E06") if "walltime" in m]


def test_a_checkpoint_interval_over_thirty_days_is_refused_by_lint(tmp_path):
    body = '    a = step("train", kind="evaluate", checkpoint_every="721h")\n'
    out = messages(tmp_path, body, {"train": ""}, rule="L-E06")
    assert any("train-checkpoint-every is '721h'. Write minutes or hours" in m for m in out), out
