"""The step contract in the linter: kind, inputs and produces (L-E07), steps not moved yet (L-E08), `lint --fix`."""
import pytest

from kaos_lib.lint import lint_project
from kaos_lib.lint.cli import main as kaosctl_lint
from kaos_lib.lint.constants import KIND_PLACEHOLDER, STEP_KINDS
from kaos_lib.lint.fix import fix_config, fix_pipeline
from lint_corpus import CONFIG, HEADER, OLD_STEP, PLAIN_STEP, repo, write_repo


def findings(tmp_path, body, steps=None, rule="L-E07", config=None):
    report = lint_project(str(write_repo(tmp_path, repo(body, steps, config))))
    return [f for f in report.findings if f.rule == rule]


def messages(tmp_path, body, steps=None, rule="L-E07", config=None):
    return [f.message + " " + (f.fix or "") for f in findings(tmp_path, body, steps, rule, config)]


# ------------------------------------------------------------------------------------------------------ L-E07
@pytest.mark.parametrize("body,expect", [
    ('    a = step("a")\n', "Step 'a' has no kind. Every step says what it is: one of ingest, transform, train, "
                            "evaluate, publish, control."),
    ('    a = step("a", kind="training")\n', "kind is 'training', which is not a kind"),
    (f'    a = step("a", kind="{KIND_PLACEHOLDER}")\n', "is still the placeholder `kaosctl lint --fix` wrote"),
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


def test_a_missing_kind_links_the_guide(tmp_path):
    found = findings(tmp_path, '    a = step("a")\n')
    assert len(found) == 1 and found[0].fix.endswith("/migrate-to-0.5.html") and found[0].span.line == 4


# ------------------------------------------------------------------------------------------------------ L-E08
def test_should_report_each_sign_of_a_step_written_for_the_old_contract(tmp_path):
    got = findings(tmp_path, '    a = step("a", kind="train")\n', {"a": OLD_STEP}, rule="L-E08")
    assert [(f.file, f.span.line) for f in got] == [("steps/a/app/entry.py", 5), ("steps/a/app/entry.py", 6)]
    assert "still takes --params on its command line" in got[0].message
    assert "still reads KUBECORE_RUN_ID from the environment" in got[1].message
    assert "migrate-to-0.5.html" in got[0].fix


def test_should_report_an_entry_that_never_starts_the_step(tmp_path):
    got = messages(tmp_path, '    a = step("a", kind="train")\n', {"a": "def main():\n    print('x')\n"}, rule="L-E08")
    assert len(got) == 1 and "Step 'a' never calls step.start()" in got[0]


def test_a_moved_step_and_a_step_without_a_folder_are_clean(tmp_path):
    body = '    a = step("a", kind="train")\n    b = step("b", kind="train")\n'
    assert findings(tmp_path, body, {"a": PLAIN_STEP}, rule="L-E08") == []


def test_a_docstring_that_mentions_the_old_names_is_not_code(tmp_path):
    code = '"""Was: --params and KUBECORE_RUN_ID."""\nfrom kaos_lib import step\nstep.start()\nstep.result()\n'
    assert findings(tmp_path, '    a = step("a", kind="train")\n', {"a": code}, rule="L-E08") == []


# ------------------------------------------------------------------------------------------------------- --fix
BEFORE = HEADER + """    load = step("load", reads=["dataset"], outputs=["dataset-info"])
    train = step("train", reads=["train"], needs=[load], gpu=True,
                 hpc_time_limit="12h",   # a comment that stays
                 outputs=["training-result"])
    report = step(
        "report",
        outputs=["report"],
        needs=[train],
    )
    done = step("done", kind="publish", needs=[report])
"""
PLACE = f'kind="{KIND_PLACEHOLDER}"'
AFTER = HEADER + f"""    load = step("load", {PLACE}, reads=["dataset"])
    train = step("train", {PLACE}, reads=["train"], needs=[load], gpu=True,
                 walltime="12h",   # a comment that stays
                 )
    report = step(
        "report", {PLACE},
        needs=[train],
    )
    done = step("done", kind="publish", needs=[report])
"""


def test_fix_renames_removes_and_adds_a_kind_placeholder_and_nothing_else():
    fixed, changes = fix_pipeline(BEFORE)
    assert fixed == AFTER
    compile(fixed, "pipeline.py", "exec")
    assert changes == [
        "line 4: step 'load': outputs= removed (hand values on with step.result(...))",
        "line 4: step 'load': kind= added as a placeholder; choose one of the kinds it lists",
        "line 5: step 'train': hpc_time_limit= renamed to walltime=",
        "line 5: step 'train': outputs= removed (hand values on with step.result(...))",
        "line 5: step 'train': kind= added as a placeholder; choose one of the kinds it lists",
        "line 8: step 'report': outputs= removed (hand values on with step.result(...))",
        "line 8: step 'report': kind= added as a placeholder; choose one of the kinds it lists",
    ]
    assert fix_pipeline(fixed) == (fixed, [])                       # a second run changes nothing


def test_fix_never_chooses_a_kind_so_the_check_still_fails_and_lists_the_kinds(tmp_path, capsys):
    root = write_repo(tmp_path, {**repo(""), "pipeline.py": BEFORE})
    assert kaosctl_lint([str(root), "--fix"]) == 2
    out = capsys.readouterr()
    assert (root / "pipeline.py").read_text() == AFTER
    compile((root / "pipeline.py").read_text(), "pipeline.py", "exec")
    assert out.err.count("fixed pipeline.py line") == 7
    assert out.out.count("is still the placeholder `kaosctl lint --fix` wrote. A step is one of ingest, transform, "
                         "train, evaluate, publish, control.") == 3
    assert "no argument 'outputs'" not in out.out and "no argument 'hpc_time_limit'" not in out.out
    assert KIND_PLACEHOLDER not in STEP_KINDS and all(kind in KIND_PLACEHOLDER for kind in STEP_KINDS)


def test_fix_on_a_file_with_nothing_to_fix_and_on_one_that_does_not_parse(tmp_path, capsys):
    root = write_repo(tmp_path, repo('    a = step("a", kind="train")\n'))
    before = (root / "pipeline.py").read_text()
    kaosctl_lint([str(root), "--fix"])
    assert (root / "pipeline.py").read_text() == before and "nothing to fix in pipeline.py" in capsys.readouterr().err
    assert fix_pipeline("with pipeline(") == ("with pipeline(", [])


def test_fix_keeps_text_that_is_not_ascii():
    text = HEADER + '    a = step("a", reads=["données"], hpc_time_limit="2h", gpu=True)   # é\n'
    fixed = fix_pipeline(text)[0]
    assert fixed == HEADER + f'    a = step("a", {PLACE}, reads=["données"], walltime="2h", gpu=True)   # é\n'
    compile(fixed, "pipeline.py", "exec")


@pytest.mark.parametrize("body", [
    '    a = step("a", gpu=True, walltime="1h", hpc_time_limit="2h")\n',
    '    a = step("a", gpu=True, hpc_time_limit="2h", walltime="1h")\n',
    '    a = step("a", outputs=["x"])\n',
    '    a = step(outputs=["x"], name="a")\n',
    '    a = step("a", gpu=True,\n             outputs=["x"],\n             hpc_time_limit="2h")\n',
])
def test_the_fixed_file_is_always_valid_python_and_a_duplicate_keyword_is_never_written(body):
    fixed, changes = fix_pipeline(HEADER + body)
    compile(fixed, "pipeline.py", "exec")
    assert fixed.count("walltime=") <= 1
    if "walltime=" in body and "hpc_time_limit" in body:
        assert "hpc_time_limit" in fixed and any("left as it is: walltime= is already there" in c for c in changes)
    assert fix_pipeline(fixed)[0] == fixed                                         # a second run changes nothing


def test_fix_refuses_text_from_standard_input(tmp_path, capsys):
    root = write_repo(tmp_path, repo('    a = step("a")\n'))
    assert kaosctl_lint([str(root), "--fix", "--stdin-path", "pipeline.py"]) == 1
    assert "--fix rewrites the pipeline file on disk" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------------ L-E09
CONFIG_BEFORE = "defaults:\n  - _self_\n  - experiment\n  - platform: live # platform-owned group\n  - train\n"
CONFIG_AFTER = "defaults:\n  - _self_\n  - experiment\n  - train\n"


def test_should_report_the_platform_group_in_the_defaults_and_its_folder(tmp_path):
    files = {**repo('    a = step("a", kind="train")\n'), "config/config.yaml": CONFIG_BEFORE,
             "config/platform/live.yaml": "platform:\n  x: 1\n"}
    report = lint_project(str(write_repo(tmp_path, files)))
    got = sorted((f for f in report.findings if f.rule == "L-E09"), key=lambda f: f.span.line)
    assert [(f.file, f.span.line) for f in got] == [("config/config.yaml", 1), ("config/config.yaml", 4)]
    assert "still has the folder config/platform/" in got[0].message and got[0].fix == "Delete the folder config/platform/."
    assert "still names the `platform` config group" in got[1].message and "kaosctl lint --fix" in got[1].fix


def test_fix_removes_the_platform_line_from_the_defaults_and_nothing_else(tmp_path, capsys):
    assert fix_config(CONFIG_BEFORE) == (CONFIG_AFTER, ["line 4: the `platform` config group removed from the defaults"])
    assert fix_config(CONFIG_AFTER) == (CONFIG_AFTER, [])
    root = write_repo(tmp_path, {**repo('    a = step("a", kind="train")\n'), "config/config.yaml": CONFIG_BEFORE})
    assert kaosctl_lint([str(root), "--fix"]) == 0
    assert (root / "config/config.yaml").read_text() == CONFIG_AFTER
    assert "fixed config/config.yaml line 4" in capsys.readouterr().err


def test_a_section_called_platform_inside_a_file_is_not_the_group(tmp_path):
    assert fix_config("defaults:\n  - train\nplatform:\n  note: mine\n")[1] == []


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


# ------------------------------------------------------------------------- --fix: parenthesised values, line endings, guard
@pytest.mark.parametrize("body", [
    '    a = step(name=("a"), outputs=["x"])\n',
    '    a = step(name=(\n "a"\n ), cmd="x")\n',
    '    a = step(("a"), outputs=["x"])\n',
    '    a = step(("a" \n "b"), outputs=["x"])\n',
    '    a = step(name="a", outputs=(["x"]))\n',
    '    a = step(name="a", outputs=(\n["x"]\n), cmd="y")\n',
    '    a = step(name=(  # c\n "a"), cmd="y")\n',
])
def test_fix_places_edits_outside_the_parentheses_of_a_parenthesised_argument(body):
    fixed, changes = fix_pipeline(HEADER + body)
    compile(fixed, "pipeline.py", "exec")
    assert changes and KIND_PLACEHOLDER in fixed and "outputs" not in fixed
    assert fix_pipeline(fixed)[0] == fixed


@pytest.mark.parametrize("eol", ["\r", "\r\n"])
def test_fix_handles_cr_and_crlf_line_endings(eol):
    text = (HEADER + '    x = 1\n    a = step(name="a", outputs=["x"], cmd="y")\n').replace("\n", eol)
    fixed, changes = fix_pipeline(text)
    assert len(changes) == 2
    assert fixed == (HEADER + f'    x = 1\n    a = step(name="a", {PLACE}, cmd="y")\n').replace("\n", eol)
    compile(fixed, "pipeline.py", "exec")


def test_fix_on_disk_keeps_crlf_endings(tmp_path):
    root = write_repo(tmp_path, repo(""))
    (root / "pipeline.py").write_bytes((HEADER + '    a = step("a", outputs=["x"])\n').replace("\n", "\r\n").encode())
    kaosctl_lint([str(root), "--fix"])
    assert (root / "pipeline.py").read_bytes() == \
        (HEADER + f'    a = step("a", {PLACE})\n').replace("\n", "\r\n").encode()


def test_fix_writes_nothing_when_the_fixed_text_would_not_compile(tmp_path, capsys, monkeypatch):
    from kaos_lib.lint import cli as lint_cli
    root = write_repo(tmp_path, {**repo(""), "pipeline.py": BEFORE})
    before = (root / "pipeline.py").read_bytes()
    monkeypatch.setattr(lint_cli, "fix_pipeline", lambda text, rel: (text + "    a = step(name=(\"a\", kind=\"x\")\n",
                                                                     ["line 4: made up"]))
    assert kaosctl_lint([str(root), "--fix"]) != 0
    assert (root / "pipeline.py").read_bytes() == before
    err = capsys.readouterr().err
    assert "could not be applied to pipeline.py" in err and "by hand" in err and "fixed pipeline.py" not in err
