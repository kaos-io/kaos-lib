"""The studio on the two real templates (PRD-CONSOLE-1682 AC-31, AC-32, AC-30): set KAOS_LINT_TEMPLATES to a folder holding
clones of hera-pipeline-template and yolo-pipelines-template (branch dev), as for the linter tests. These tests copy the
template, use the network (the package index) and, for the last one, a real container engine; without them they skip."""
import os
import pathlib
import shutil
import subprocess

import pytest

from kaos_lib import cli
from kaos_lib.studio import engine as eng
from kaos_lib.studio import pyenv, steps

ROOT = os.environ.get("KAOS_LINT_TEMPLATES")
pytestmark = pytest.mark.skipif(not ROOT, reason="set KAOS_LINT_TEMPLATES to a folder with both template clones")
RC20 = "kaos-lib[zitadel] @ https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/kaos-lib/kaos_lib-0.4.0rc20-py3-none-any.whl"


def copy_template(name, tmp_path):
    dest = tmp_path / name
    shutil.copytree(pathlib.Path(ROOT) / name, dest, ignore=shutil.ignore_patterns(".git", ".venv", ".kaos"), symlinks=False)
    return dest


def test_should_run_the_yolo_data_summary_step_in_its_own_environment(tmp_path, capsys):
    repo = copy_template("yolo-pipelines-template", tmp_path)
    assert cli.main(["dev", str(repo), "--step", "data-summary", "--step", "compose-and-validate"]) == 0
    py = pyenv.venv_python(pyenv.step_env(repo / "steps/data_summary"))
    assert subprocess.run([str(py), "-c", "import yaml"]).returncode == 0
    assert subprocess.run([str(py), "-c", "import kaos_lib"]).returncode != 0      # PyYAML only: no kaos-lib
    capsys.readouterr()
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    assert "dataset=" in capsys.readouterr().out


def test_should_set_up_the_hera_hello_world_step_with_kaos_lib(tmp_path):
    repo = copy_template("hera-pipeline-template", tmp_path)
    assert cli.main(["dev", str(repo), "--step", "hello-world", "--kaos-lib", RC20]) == 0
    py = pyenv.venv_python(pyenv.step_env(repo / "steps/hello_world"))
    assert subprocess.run([str(py), "-c", "import kaos_lib, yaml"]).returncode == 0


def test_should_skip_the_heavy_yolo_steps_by_default(tmp_path, capsys, monkeypatch):
    repo = copy_template("yolo-pipelines-template", tmp_path)
    monkeypatch.setattr("kaos_lib.studio.dev.setup_step", lambda *a, **k: __import__("kaos_lib.studio.dev", fromlist=["x"]).DevOutcome("x", "created"))
    assert cli.main(["dev", str(repo)]) == 0
    out = capsys.readouterr().out
    for heavy in ("model-training", "qat-finetune", "model-quantization"):
        assert f"{heavy}: skipped" in out


@pytest.mark.parametrize("name", ["hera-pipeline-template", "yolo-pipelines-template"])
def test_should_read_every_step_of_the_template_without_a_note_or_error(name, tmp_path):
    from kaos_lib.studio import deps
    repo = copy_template(name, tmp_path)
    for step in steps.discover(repo):
        d = deps.read_step_deps(step.path)
        assert d.python in ("3.11", "3.12") and not d.notes, (step.name, d.notes)


def _engine():
    found = eng.detect()
    usable, _ = eng.first_usable(found, "amd64") if found else (None, [])
    return usable


def test_should_build_a_template_step_with_a_real_engine(tmp_path, capsys):
    """AC-30 on a real engine: the step image builds locally with CI's build arguments and carries the label."""
    if _engine() is None:
        pytest.skip("no usable container engine on this machine")
    repo = copy_template("hera-pipeline-template", tmp_path)
    assert cli.main(["build", "hello-world", "--path", str(repo), "--kaos-lib", RC20]) == 0
    tag = "kaos-local/hera-pipeline-template:hello-world-local-nogit"
    exe = _engine().engine.exe
    try:
        label = subprocess.run([exe, "inspect", tag, "--format", "{{index .Config.Labels \"io.kaos.lib\"}}"],
                               capture_output=True, text=True).stdout.strip()
        assert "kaos_lib-0.4.0rc20" in label
        ran = subprocess.run([exe, "run", "--rm", "--entrypoint", "python", tag, "-c", "import kaos_lib, app.entry"],
                             capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
    finally:
        subprocess.run([exe, "rmi", "-f", tag], capture_output=True)
