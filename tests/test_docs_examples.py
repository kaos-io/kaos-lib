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


def test_should_name_in_the_run_request_a_dataset_the_pipeline_produces():
    request = yaml.safe_load((ex.FIRST / "produce" / "runs" / "promote.yaml").read_text())
    produced = re.findall(r'dataset\("([a-z0-9-]+)"\)', (ex.FIRST / "template" / "pipeline.py").read_text())
    assert list(request["plan"]["promote"]) == produced == ["clean"]


def test_should_run_the_test_files_of_the_pages_long_jobs_and_try_it_locally(tmp_path):
    app = ex.assemble("try-locally", tmp_path / "app")
    assert sorted(p.name for p in (app / "step_tests").iterdir()) == ["test_prepare.py", "test_train.py"]
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "step_tests"], cwd=app,
                         capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert run.returncode == 0, run.stdout + run.stderr


def test_should_pass_the_params_file_of_the_page_try_it_locally_to_kaosctl_step_run(tmp_path):
    from kaos_lib import cli
    app = ex.assemble("try-locally", tmp_path / "app")
    data = tmp_path / "toy"
    data.mkdir()
    (data / "a.txt").write_text("a\n")
    (data / "empty.txt").write_text("")
    code = cli.main(["step", "run", "prepare", str(app), "--params-file", str(app / "params.yaml"),
                     "--python", sys.executable, "--input", f"dataset={data}"])
    assert code == 0
    written = app / ".kaos" / "local" / "staged" / "clean"
    assert [p.name for p in written.iterdir()] == ["a.txt"]


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
            assert (DOCS / name).is_file() or (REPO / name).is_file(), f"{page.name} includes {target}"
