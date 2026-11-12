"""The step contract in the linter: kind, inputs and produces (L-E07), an app made before the contract (L-E06..L-E09)."""
import pytest

from kaos_lib.lint import lint_project
from kaos_lib.lint.cli import main as kaosctl_lint
from kaos_lib.lint.constants import OLD_APP_NOTICE, STEP_KINDS
from lint_corpus import CONFIG, OLD_STEP, PLAIN_STEP, repo, write_repo


def findings(tmp_path, body, steps=None, rule="L-E07", config=None):
    report = lint_project(str(write_repo(tmp_path, repo(body, steps, config))))
    return [f for f in report.findings if f.rule == rule]


def messages(tmp_path, body, steps=None, rule="L-E07", config=None):
    return [f.message + " " + (f.fix or "") for f in findings(tmp_path, body, steps, rule, config)]


# ------------------------------------------------------------------------------------------------------ L-E07
def test_a_step_without_kind_among_steps_with_one_is_not_told_the_app_is_old(tmp_path):
    body = ('    a = step("a", kind="transform")\n    b = step("b", needs=[a])\n'
            '    c = step("c", kind="train", needs=[b])\n')
    got = messages(tmp_path, body)
    assert len(got) == 1 and "Step 'b' has no kind=, which every step declares: one of " in got[0]
    assert got[0].strip().startswith("Step 'b'") and OLD_APP_NOTICE not in got[0] and "made before" not in got[0]


def test_when_no_step_has_a_kind_the_app_is_told_it_is_old(tmp_path):
    body = '    a = step("a")\n    b = step("b", needs=[a])\n    c = step("c", needs=[b])\n'
    got = messages(tmp_path, body)
    assert len(got) == 3 and all(OLD_APP_NOTICE in m for m in got)


@pytest.mark.parametrize("body,expect", [
    ('    a = step("a")\n', "Step 'a' has no kind=, which every step declares: one of ingest, transform, train, "
                            "evaluate, publish, control. " + OLD_APP_NOTICE),
    ('    a = step("a", kind="training")\n', "kind is 'training', which is not a kind"),
    ('    a = step("a", kind="train", inputs="dataset")\n', "inputs must be a list of names"),
    ('    a = step("a", kind="train", inputs=["dataset", "dataset"])\n', "lists the input 'dataset' twice"),
    ('    a = step("a", kind="train", produces=["model"])\n', 'produces takes model("name")'),
    ('    a = step("a", kind="train", produces=model("m"))\n', "produces must be a list"),
    ('    a = step("a", kind="train", produces=[model("m"), artifact("m")])\n', "produces 'm' twice"),
    ('    a = step("a", kind="train", produces=[model("kaos-model")])\n', "names starting with 'kaos-'"),
    ('    a = step("a", kind="train", produces=[dataset("Clean Data")])\n', "is not a name for what a step produces"),
    ('    a = step("a", kind="train", produces=[model("%s")])\n' % ("m" * 41), "at most 40 characters"),
    ('    a = step("a", kind="train", inputs=["Data_Set"])\n', "'Data_Set' is not a name for an input"),
    ('    a = step("a", kind="train", inputs=["kaos-data"])\n', "names starting with 'kaos-' are the platform's"),
    ('    a = step("kaos-train", kind="train")\n', "The step name 'kaos-train' cannot be used"),
    ('    a = step("%s", kind="train")\n' % ("s" * 41), "at most 40 characters"),
    ('    a = step("a", kind="transform", produces=[dataset("clean", of="raw")])\n', "of=...) is reserved"),
    ('    a = step("a", kind="transform", produces=[dataset("clean")])\n'
     '    b = step("b", kind="train", needs=[a], inputs=["clean"])\n',
     "has the input 'clean' and needs a step that produces 'clean'"),
    ('    a = step("a", kind="train", produces=[model("model")])\n'
     '    b = step("b", kind="train", produces=[model("model")])\n'
     '    c = step("c", kind="evaluate", needs=[a, b])\n',
     "Step 'c' needs 'a' and 'b', which both produce 'model'"),
    ("".join(f'    s{i} = step("s{i}", kind="train")\n' for i in range(11))
     + '    z = step("z", kind="evaluate", needs=[' + ", ".join(f"s{i}" for i in range(11)) + '])\n',
     "Step 'z' needs 11 steps; a step can need at most 10."),
])
def test_should_report_a_step_that_does_not_declare_itself(tmp_path, body, expect):
    assert any(expect in m for m in messages(tmp_path, body)), messages(tmp_path, body)


@pytest.mark.parametrize("kind", STEP_KINDS)
def test_every_kind_is_accepted(tmp_path, kind):
    assert findings(tmp_path, f'    a = step("a", kind="{kind}")\n') == []


def test_a_full_declaration_is_clean_and_values_that_are_not_literals_are_not_judged(tmp_path):
    body = ('    a = step("a", kind="transform", inputs=["raw", "labels"], produces=[dataset("clean")])\n'
            '    b = step("b", kind="train", needs=[a], inputs=["labels"], gpu=True, walltime="12h",\n'
            '             produces=[model("model"), artifact("report")])\n'
            '    c = step("c", kind=KIND, inputs=INPUTS, produces=PRODUCES)\n')
    assert findings(tmp_path, body, config={**CONFIG, "config/data.yaml": "raw: dataset-raw@latest\nlabels: dataset-l@v1\n"}) == []


def test_a_missing_kind_is_an_old_app_and_names_no_conversion(tmp_path):
    found = findings(tmp_path, '    a = step("a")\n')
    assert len(found) == 1 and found[0].message.endswith(OLD_APP_NOTICE) and found[0].span.line == 4
    assert "choose one" not in found[0].message + found[0].fix and "lint --fix" not in found[0].fix


# ------------------------------------------------------------------------------------------------------ L-E08
def test_should_report_each_sign_of_a_step_written_for_the_old_contract(tmp_path):
    got = findings(tmp_path, '    a = step("a", kind="train")\n', {"a": OLD_STEP}, rule="L-E08")
    assert [(f.file, f.span.line) for f in got] == [("steps/a/app/entry.py", 5), ("steps/a/app/entry.py", 6)]
    assert "takes --params on its command line" in got[0].message
    assert "reads KUBECORE_RUN_ID from the environment" in got[1].message
    assert all(f.message.endswith(OLD_APP_NOTICE) for f in got)


def test_should_report_an_entry_that_never_starts_the_step(tmp_path):
    got = messages(tmp_path, '    a = step("a", kind="train")\n', {"a": "def main():\n    print('x')\n"}, rule="L-E08")
    assert len(got) == 1 and "Step 'a' never calls step.start()" in got[0]


def test_a_moved_step_and_a_step_without_a_folder_are_clean(tmp_path):
    body = '    a = step("a", kind="train")\n    b = step("b", kind="train")\n'
    assert findings(tmp_path, body, {"a": PLAIN_STEP}, rule="L-E08") == []


def test_a_docstring_that_mentions_the_old_names_is_not_code(tmp_path):
    code = '"""Was: --params and KUBECORE_RUN_ID."""\nfrom kaos_lib import step\nstep.start()\nstep.result()\n'
    assert findings(tmp_path, '    a = step("a", kind="train")\n', {"a": code}, rule="L-E08") == []


# ----------------------------------------------------------------------- what only an app from before the contract has
@pytest.mark.parametrize("arg", ["outputs=['x']", "hpc_time_limit='2h'", "disk='20Gi'"])
def test_a_removed_argument_is_refused_with_the_old_app_sentence_and_no_conversion(tmp_path, arg):
    got = findings(tmp_path, f'    a = step("a", kind="train", {arg})\n', rule="L-E06")
    name = arg.split("=")[0]
    assert len(got) == 1 and got[0].message == f"step() no longer takes '{name}'. {OLD_APP_NOTICE}"
    assert got[0].fix == "Remove the argument or write it as the message says; step() raises on it when the " \
                         "pipeline is rendered."


def test_an_unknown_argument_is_not_an_old_app(tmp_path):
    got = findings(tmp_path, '    a = step("a", kind="train", colour="red")\n', rule="L-E06")
    assert len(got) == 1 and OLD_APP_NOTICE not in got[0].message


def test_an_app_with_a_kubecore_folder_of_its_own_is_an_old_app(tmp_path):
    files = {**repo('    a = step("a", kind="train")\n', {"a": PLAIN_STEP}), "kubecore/authoring.py": "x = 1\n"}
    got = [f for f in lint_project(str(write_repo(tmp_path, files))).findings if f.rule == "L-E08"]
    assert len(got) == 1 and "has a kubecore/ folder of its own" in got[0].message
    assert got[0].message.endswith(OLD_APP_NOTICE)


def test_the_linter_has_no_fix_option(capsys):
    with pytest.raises(SystemExit):
        kaosctl_lint(["--fix"])
    assert "unrecognized arguments: --fix" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------------ L-E09
CONFIG_BEFORE = "defaults:\n  - _self_\n  - experiment\n  - platform: live # platform-owned group\n  - train\n"
CONFIG_AFTER = "defaults:\n  - _self_\n  - experiment\n  - train\n"


def test_should_report_the_platform_group_in_the_defaults_and_its_folder(tmp_path):
    files = {**repo('    a = step("a", kind="train")\n'), "config/config.yaml": CONFIG_BEFORE,
             "config/platform/live.yaml": "platform:\n  x: 1\n"}
    report = lint_project(str(write_repo(tmp_path, files)))
    got = sorted((f for f in report.findings if f.rule == "L-E09"), key=lambda f: f.span.line)
    assert [(f.file, f.span.line) for f in got] == [("config/config.yaml", 1), ("config/config.yaml", 4)]
    assert "has a config/platform/ folder" in got[0].message and got[0].message.endswith(OLD_APP_NOTICE)
    assert "names the `platform` config group" in got[1].message and got[1].message.endswith(OLD_APP_NOTICE)


# ------------------------------------------------------------------------------- what the linter does not read
def test_lint_does_not_read_a_virtualenv_kaos_dev_made_nor_what_git_ignores(tmp_path):
    files = repo('    a = step("a", kind="train")\n', {"a": PLAIN_STEP})
    bad = "import argparse\nargparse.ArgumentParser().add_argument('--params')\n"      # what L-E08 would flag
    files.update({"steps/a/.venv/lib/python3.12/site-packages/kaos_lib/old.py": bad,
                  "steps/a/myenv/pyvenv.cfg": "home = /usr/bin\n", "steps/a/myenv/lib/x.py": bad,
                  "steps/a/.kaos/local/y.py": bad, "steps/a/build/z.py": bad, "steps/a/.gitignore": "# built\nbuild/\n"})
    report = lint_project(str(write_repo(tmp_path, files)))
    assert [f for f in report.findings if f.rule in ("L-E08", "L-E00")] == []
    write_repo(tmp_path, {"steps/a/app/helper.py": bad})                                 # the app's own file counts
    assert [f.file for f in lint_project(str(tmp_path)).findings if f.rule == "L-E08"] == ["steps/a/app/helper.py"]


# ------------------------------------------------------------ what the engine refuses, the linter refuses too
ENGINE = [
    ('    a = step("a", "train")\n', "L-E06", "step() takes only the name by position"),
    ('    a = step("a", kind="control", inputs=["dataset"])\n', "L-E07", "is a control step: it steers the run"),
    ('    a = step("a", kind="control", produces=[artifact("r")])\n', "L-E07", "is a control step"),
    ('    a = step("main", kind="train")\n', "L-E07", "The step name 'main' is the platform's"),
    ('    a = step("compose-and-validate", kind="train")\n', "L-E07", "is the platform's"),
    ('    a = step("x-hpc", kind="train")\n', "L-E07", "The step name 'x-hpc' is the platform's"),
    ('    a = step("a", kind="train", inputs=[%s])\n' % ", ".join(f'"i{i}"' for i in range(17)), "L-E07",
     "can read 17 datasets by name"),
    ('    a = step("a", kind="transform", produces=[dataset("clean")])\n'
     '    b = step("b", kind="transform", produces=[dataset("clean")])\n', "L-E07",
     "the dataset 'clean' is already produced by step 'a'. A dataset has one writer"),
    ('    a = step("a", kind="train", inputs=["nope"])\n', "L-E07", "the input 'nope' is not in config/"),
    ('    a = step("a", kind="train", inputs=["experiment"])\n', "L-E07", "the input 'experiment' is a section"),
    ('    a = step("a", kind="transform", produces=[dataset("clean", extra=1)])\n', "L-E07",
     "dataset() takes a name and nothing else"),
]


@pytest.mark.parametrize("body,rule,expect", ENGINE, ids=[e[2][:40] for e in ENGINE])
def test_lint_refuses_what_the_engine_refuses(tmp_path, body, rule, expect):
    assert any(expect in m for m in messages(tmp_path, body, rule=rule)), messages(tmp_path, body, rule=rule)


def test_readable_datasets_count_inputs_and_what_the_needed_steps_produce(tmp_path):
    body = ('    a = step("a", kind="transform", produces=[%s])\n' % ", ".join(f'dataset("d{i}")' for i in range(16))
            + '    b = step("b", kind="train", needs=[a], inputs=["dataset"])\n')
    assert any("can read 17 datasets" in m for m in messages(tmp_path, body))


def test_a_repeated_keyword_is_reported(tmp_path):
    assert any("step() is given 'kind' twice" in m for m in
               messages(tmp_path, '    a = step("a", kind="train", kind="train")\n', rule="L-E06"))


def test_an_attribute_call_in_produces_is_the_same_as_a_name(tmp_path):
    body = '    import kubecore.authoring as au\n    a = step("a", kind="train", produces=[au.model("m")])\n'
    assert findings(tmp_path, body) == []
    body = '    import kubecore.authoring as au\n    a = step("a", kind="train", produces=[au.model("kaos-m")])\n'
    assert any("names starting with 'kaos-'" in m for m in messages(tmp_path, body))


# ------------------------------------------------------------------------------------- when= (L-E06)
def when_messages(tmp_path, when, config=None, name="a"):
    body = f'    a = step("{name}", kind="train", when={when!r})\n'
    return [(f.line if hasattr(f, "line") else f.span.line, f.message, f.fix)
            for f in findings(tmp_path, body, rule="L-E06", config=config)]


@pytest.mark.parametrize("when", [
    "experiment-name != off", "experiment-name == 'two words'", 'experiment-name == "two words"',
    "dataset == a or dataset == b and experiment-name == 3", "train-epochs == 3", "experiment-name=='x'",
])
def test_a_when_in_plain_words_naming_a_form_field_is_clean(tmp_path, when):
    assert when_messages(tmp_path, when) == []


@pytest.mark.parametrize("when", [
    "experiment-name = off", "experiment-name", "experiment-name ==", "(experiment-name == a)", "len(dataset) == 3",
    "experiment-name == a && dataset == b", "experiment-name == two words", "", "experiment-name == a and",
])
def test_a_when_that_is_not_a_comparison_is_reported_with_an_example(tmp_path, when):
    got = when_messages(tmp_path, when)
    assert len(got) == 1 and got[0][0] == 4
    assert got[0][1] == (f"Step 'a': when={when!r} is not a run-form field compared with a value, for example "
                         f'when="mode != off". Join comparisons with and / or; no parentheses.')
    assert got[0][2] == 'Write it as a field name, ==, or !=, and a value: when="mode != off".'


@pytest.mark.parametrize("when", ["{{workflow.parameters.mode}} == qat", "mode == {{x}}", "{{=a == b}}"])
def test_the_workflow_systems_own_form_in_when_is_reported(tmp_path, when):
    got = when_messages(tmp_path, when)
    assert len(got) == 1 and got[0][0] == 4 and got[0][1] == (
        "Step 'a': when= is written with the name of a run-form field, for example when=\"mode != off\". "
        "Write the field's name instead of {{workflow.parameters.<field>}}.")


def test_a_when_naming_a_field_the_run_form_does_not_have_is_reported_with_the_fields_it_has(tmp_path):
    got = when_messages(tmp_path, "quantization-mode != off")
    assert len(got) == 1 and got[0][1] == (
        "Step 'a': when='quantization-mode != off' names 'quantization-mode', which is not a field of the run form. "
        "The fields are: dataset, experiment-name, train-epochs.")
    assert got[0][2] == "Use the name of a setting as the run form shows it: its path with dashes."


def test_a_field_of_a_group_and_of_a_group_file_is_a_run_form_field(tmp_path):
    config = {**CONFIG, "config/config.yaml": "defaults:\n  - experiment\n  - dataset\n  - model: small\n",
              "config/model/small.yaml": "model:\n  size: 1\n  nested:\n    depth: 2\n"}
    assert when_messages(tmp_path, "model == small and model-size == 1 and model-nested-depth != 2", config) == []


def test_with_a_structured_schema_a_field_of_a_known_section_is_not_judged(tmp_path):
    config = {**CONFIG, "config/config.yaml": "defaults:\n  - quantization_schema\n  - train\n",
              "config/train.yaml": "train:\n  epochs: 3\n"}
    assert when_messages(tmp_path, "train-mode != off", config) == []
    assert len(when_messages(tmp_path, "other-mode != off", config)) == 1


def test_without_a_config_folder_the_field_is_not_judged(tmp_path):
    assert when_messages(tmp_path, "anything != off", config={}) == []
