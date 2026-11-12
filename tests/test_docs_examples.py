"""The code in the guide is real: every example app of docs/examples is linted and run (docs_examples.py), and the
pages include their code from those files, so a page cannot show code that does not work."""
import os
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import docs_examples as ex  # noqa: E402

REPO = ex.HERE
DOCS = REPO / "docs"


@pytest.mark.parametrize("state", ex.STATES)
def test_should_report_no_lint_error_for_the_app_after_each_page(state, tmp_path):
    report = ex.lint(ex.assemble(state, tmp_path / "app"))
    assert report.errors == 0, report.to_json()


@pytest.mark.parametrize("state", ex.STATES)
def test_should_run_prepare_and_hello_world_after_each_page(state, tmp_path):
    walk = ex.Walk(state, tmp_path)
    walk.prepare()
    walk.hello_world()


def test_should_hand_on_the_dropped_files_as_a_file_and_as_a_count(tmp_path):
    walk = ex.Walk("pass-on", tmp_path)
    walk.prepare()
    result = walk.hello_world()
    assert result["values"]["files"] == 2
    assert walk.results["prepare"]["values"]["dropped"] == 1
    assert [w["name"] for w in walk.results["prepare"]["writes"]] == ["clean", "dropped-files"]


def test_should_continue_train_from_its_checkpoint_after_it_was_asked_to_stop(tmp_path):
    walk = ex.Walk("long-job", tmp_path)
    walk.prepare()
    with pytest.raises(SystemExit) as stopped:
        walk.train(stop_after=2)
    assert stopped.value.code == 85
    result = walk.train()
    assert result["values"] == {"epochs": 5}
    # 12 bytes of clean for each of the 5 epochs, the first 2 before the stop and the other 3 after it
    assert (walk.outputs["train"]["model"] / "weights.txt").read_text() == "60\n"


def test_should_run_the_second_pipeline_on_a_dataset_the_first_one_produced(tmp_path):
    walk = ex.Walk("template", tmp_path)
    assert walk.second()["values"] == {"files": 3}
    app = tmp_path / "second"
    assert ex.lint(app).errors == 0
    assert yaml.safe_load((app / "config" / "clean.yaml").read_text()) == {"clean": "dataset-myapp-clean@latest"}


def test_should_name_the_run_form_field_of_a_dataset_the_pipeline_produces():
    """The form has `promote-<name>` for each dataset a step produces; the page names the one of the example."""
    produced = re.findall(r'dataset\("([a-z0-9-]+)"\)', (ex.FIRST / "template" / "pipeline.py").read_text())
    assert produced == ["clean"]
    page = (DOCS / "flow-datasets.md").read_text()
    assert "`promote-clean`" in page and "plan:" not in page and "advanced config" not in page


def test_should_run_the_test_files_of_the_pages_long_jobs_and_try_it_locally(tmp_path):
    app = ex.assemble("try-locally", tmp_path / "app")
    assert sorted(p.name for p in (app / "step_tests").iterdir()) == ["test_prepare.py", "test_train.py"]
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "step_tests"], cwd=app,
                         capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert run.returncode == 0, run.stdout + run.stderr


def test_should_run_the_two_commands_of_the_page_try_it_locally_on_the_folders_the_page_makes(tmp_path):
    """The page makes `toy` on page 1 and `reference` itself (three files), then runs prepare and hello-world."""
    from kaos_lib import cli
    app = ex.assemble("try-locally", tmp_path / "app")
    toy = tmp_path / "toy"
    toy.mkdir()
    for name, text in {"a.txt": "one\n", "b.txt": "two two\n", "empty.txt": ""}.items():
        (toy / name).write_text(text)
    page = (DOCS / "try-it-locally.md").read_text(encoding="utf-8")
    make = re.search(r"```bash\n(mkdir reference[^\n]*)\n```", page).group(1)
    subprocess.run(make, shell=True, cwd=tmp_path, check=True)   # the lines of the page, as they stand
    assert len(list((tmp_path / "reference").iterdir())) == 3
    common = [str(app), "--params-file", str(app / "params.yaml"), "--python", sys.executable]
    assert cli.main(["step", "run", "prepare", *common, "--input", f"dataset={toy}"]) == 0
    written = app / ".kaos" / "local" / "staged" / "clean"
    assert sorted(p.name for p in written.iterdir()) == ["a.txt", "b.txt"]
    assert cli.main(["step", "run", "hello-world", *common, "--input", f"reference={tmp_path / 'reference'}"]) == 0
    report = (app / ".kaos" / "local" / "staged" / "report" / "hello.txt").read_text()
    assert "3 in the reference" in report and "2 files" in report, report


def test_should_run_every_example_through_the_build_check():
    ex.check_all()


def test_should_include_every_example_file_in_a_page():
    included = " ".join(p.read_text(encoding="utf-8") for p in DOCS.glob("*.md"))
    missing = [str(p.relative_to(DOCS)) for p in sorted((DOCS / "examples").rglob("*"))
               if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in p.parts
               and f"\"{p.relative_to(DOCS).as_posix()}\"" not in included
               and f"\"{p.relative_to(DOCS).as_posix()}:" not in included]
    assert not missing, f"example files no page includes: {missing}"


def test_should_include_only_files_that_exist():
    for page in DOCS.glob("*.md"):
        for target in re.findall(r'--8<--\s+"([^"]+)"', page.read_text(encoding="utf-8")):
            name = target.split(":")[0]
            if name.startswith("generated/"):  # written by docs_gen.py at build time, not kept in git
                continue
            assert (DOCS / name).is_file() or (REPO / name).is_file(), f"{page.name} includes {target}"


def test_should_compare_two_versions_of_a_dataset_read_by_one_step(tmp_path):
    result = ex.flow_two_inputs(tmp_path)
    assert [r["name"] for r in result["reads"]] == ["before", "after"]  # in the order of inputs=


def test_should_let_the_step_after_a_skipped_step_run_with_and_without_its_result(tmp_path):
    assert ex.flow_skip(tmp_path)["values"] == {"extra_ran": True}


def test_should_run_the_tests_of_the_step_that_copes_with_a_skipped_step(tmp_path):
    app = ex.flow_app("skip", tmp_path)
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "step_tests"], cwd=app,
                         capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert run.returncode == 0 and "2 passed" in run.stdout, run.stdout + run.stderr


def test_should_keep_the_model_of_the_better_of_two_steps_a_step_needs(tmp_path):
    assert ex.flow_fan_in(tmp_path)["values"]["winner"] == "large"


def test_should_name_a_setting_of_the_run_form_in_the_condition_of_a_skipped_step():
    text = (ex.FLOWS / "skip" / "pipeline.py").read_text()
    field = re.search(r"when=\"([a-z-]+) [!=]=", text).group(1)
    config = yaml.safe_load((ex.FLOWS / "skip" / "config" / "extra.yaml").read_text())
    assert field == "-".join(["extra", *config["extra"]])  # config path with dashes: extra.mode is extra-mode


def test_should_log_a_parameter_and_a_curve_to_mlflow_from_a_step_and_save_its_model(tmp_path):
    assert ex.flow_metrics(tmp_path)["values"] == {"final_loss": 1 / 3}


def test_should_bring_the_files_of_a_source_in_as_a_dataset_and_fail_when_the_source_gives_none(tmp_path):
    assert ex.flow_ingest(tmp_path)["values"] == {"files": 2}


def test_should_lint_the_dockerfile_that_adds_packages_without_an_error_or_a_warning(tmp_path):
    ex.packages_dockerfile(tmp_path)


def test_should_read_the_dataset_another_project_shares_as_a_reference_with_an_owner():
    ex.shared_reference()


def test_should_show_the_result_a_step_hands_on_with_what_it_read_and_wrote(tmp_path):
    import json
    shown = json.loads((ex.EXAMPLES / "ledger" / "hello-world-result.json").read_text())
    assert ex.ledger_example(tmp_path) == shown
    assert [r["name"] for r in shown["reads"]] == ["reference", "clean"]  # the inputs first, then what else it opened
    assert [(w["name"], w["type"]) for w in shown["writes"]] == [("report", "artifact")]
    assert all(len(x["commit"]) == 64 for x in shown["reads"] + shown["writes"])


def test_should_deliver_the_model_with_a_publish_step_that_produces_nothing(tmp_path):
    assert ex.flow_publish(tmp_path)["values"] == {"delivered": "my-model"}


def test_should_let_a_control_step_stop_a_run_with_wrong_settings_and_hand_on_its_values(tmp_path):
    assert ex.flow_control(tmp_path)["values"] == {}
