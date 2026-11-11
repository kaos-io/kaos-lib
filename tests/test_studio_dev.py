"""F-29, D-15: `kaosctl dev` on fixtures modelled on both templates. Reading is static (AC-31 reads, AC-36 asserts the
Python version, the kaos-lib spec and the workspace setting); installing is stubbed behind `proc.run`."""
import json

import pytest

from kaos_lib import cli
from kaos_lib.studio import deps, dev, kaoslib, proc, pyenv, steps, vscode
from studio_helpers import VenvStub, template_repo


@pytest.fixture
def repo(tmp_path):
    return template_repo(tmp_path / "app")


@pytest.fixture
def venv_stub(monkeypatch):
    stub = VenvStub("3.11")
    monkeypatch.setattr(proc, "run", stub)
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: "/usr/bin/uv" if name == "uv" else None)
    return stub


def requirements_of(repo, step):
    return (repo / "steps" / step / ".venv" / "kaos-requirements.txt").read_text().splitlines()


# --- reading, statically ----------------------------------------------------------------------------------------

def test_should_find_every_step_with_its_outputs_and_what_it_needs(repo):
    found = {s.name: s for s in steps.discover(repo)}
    assert set(found) == {"dataset-loading", "data-summary", "model-training", "compose-and-validate"}
    assert found["dataset-loading"].outputs == ["dataset-info"] and found["data-summary"].needs == ["dataset-loading"]
    assert found["model-training"].gpu and found["compose-and-validate"].implicit


def test_should_read_a_steps_that_needs_only_pyyaml(repo):
    d = deps.read_step_deps(repo / "steps/data_summary")
    assert (d.python, d.requirements, d.imports_kaos_lib, d.declares_kaos_lib_arg) == ("3.11", ["PyYAML"], False, False)


def test_should_read_the_kaos_lib_default_of_a_step_that_declares_the_argument(repo):
    d = deps.read_step_deps(repo / "steps/dataset_loading")
    assert d.declares_kaos_lib_arg and d.kaos_lib_default == "kaos-lib[zitadel]==0.4.0rc20" and d.requirements == []


def test_should_take_the_python_version_and_the_locked_main_group_of_a_poetry_step(repo):
    d = deps.read_step_deps(repo / "steps/model_training")
    assert d.python == "3.12" and d.requirements == ["torch==2.3.1"] and d.heavy() == ["torch"]
    assert d.sources == ["poetry.lock"]        # the dev group's pytest and poetry itself (in /opt/poetry) are not the image's


def test_should_fall_back_to_pyproject_constraints_without_a_lock_file(repo):
    (repo / "steps/model_training/poetry.lock").unlink()
    d = deps.read_step_deps(repo / "steps/model_training")
    assert d.requirements == ["torch>=2.3,<3", "PyYAML>=6.0,<7"]


def test_should_keep_a_lock_platform_marker_so_a_win32_only_dep_is_not_demanded_elsewhere(tmp_path):
    # Regression: a poetry.lock package carrying `markers` (e.g. pywin32, sys_platform == "win32") must keep it, or
    # `kaosctl dev` demands a Windows-only dep on macOS/Linux and fails on a step whose real poetry build is fine.
    repo = template_repo(tmp_path / "app", {
        "steps/model_training/poetry.lock":
            '[[package]]\nname = "torch"\nversion = "2.3.1"\ngroups = ["main"]\n\n'
            '[[package]]\nname = "pywin32"\nversion = "311"\ngroups = ["main"]\nmarkers = "sys_platform == \\"win32\\""\n',
    })
    d = deps.read_step_deps(repo / "steps/model_training")
    assert 'pywin32==311 ; sys_platform == "win32"' in d.requirements   # kept, so pip/uv skip it off-Windows
    assert "torch==2.3.1" in d.requirements                             # a dep with no marker is unchanged


def test_should_follow_a_requirements_file_named_in_the_dockerfile(repo):
    (repo / "steps/data_summary/Dockerfile").write_text(
        "FROM python:3.10-slim\nRUN pip install --no-cache-dir -r requirements.txt\n")
    (repo / "steps/data_summary/requirements.txt").write_text(
        "# c\n--index-url https://example.org/simple\nnumpy==1.26.4  # pinned\n-r more.txt\n")
    (repo / "steps/data_summary/more.txt").write_text("pandas>=2\n")
    d = deps.read_step_deps(repo / "steps/data_summary")
    assert (d.python, d.requirements, d.index_options) == ("3.10", ["numpy==1.26.4", "pandas>=2"], [("--index-url", "https://example.org/simple")])


def test_should_read_a_pyproject_project_table_when_the_dockerfile_installs_nothing(repo):
    (repo / "steps/data_summary/Dockerfile").write_text("FROM python:3.11-slim\nCOPY app/ ./app/\n")
    (repo / "steps/data_summary/pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["PyYAML>=6", "rich"]\n')
    assert deps.read_step_deps(repo / "steps/data_summary").requirements == ["PyYAML>=6", "rich"]


def test_should_note_a_requirements_file_that_is_missing_instead_of_failing(repo):
    (repo / "steps/data_summary/Dockerfile").write_text("FROM python:3.11-slim\nRUN pip install -r nowhere.txt\n")
    assert "nowhere.txt: file not found" in deps.read_step_deps(repo / "steps/data_summary").notes[0]


def test_should_never_run_the_steps_code(repo):
    (repo / "steps/data_summary/app/entry.py").write_text("raise SystemExit('the step ran')\n")
    (repo / "steps/data_summary/setup.py").write_text("raise SystemExit('a build hook ran')\n")
    assert deps.read_step_deps(repo / "steps/data_summary").requirements == ["PyYAML"]


# --- the kaos-lib that is installed (AC-36) ------------------------------------------------------------------------

def test_should_choose_the_kaos_lib_flag_first_then_the_context_then_the_dockerfile_default(tmp_path):
    ctx = tmp_path / "ctx.yaml"
    ctx.write_text("kaosLib:\n  spec: 'kaos-lib[zitadel]==0.4.0rc19'\n")
    assert "0.4.0rc21" in kaoslib.resolve("kaos-lib==0.4.0rc21", str(ctx), "kaos-lib==0.4.0rc1").requirement
    assert kaoslib.resolve(None, str(ctx), "kaos-lib==0.4.0rc1").source.startswith("the context file")
    assert "0.4.0rc1" in kaoslib.resolve(None, None, "kaos-lib==0.4.0rc1").requirement


def test_should_use_the_prerelease_index_for_an_rc_pin_and_none_for_a_url(tmp_path):
    assert "kaos-lib-rc" in kaoslib.resolve("kaos-lib==0.4.0rc20").index_urls[0]
    assert kaoslib.resolve("kaos-lib @ https://example.org/kaos_lib-0.4.0-py3-none-any.whl").index_urls == []


def test_should_refuse_a_spec_that_is_not_kaos_lib():
    from kaos_lib.errors import KaosLibError
    with pytest.raises(KaosLibError, match="--kaos-lib"):
        kaoslib.resolve("evil-package==1")


# --- the command ------------------------------------------------------------------------------------------------------

def test_should_set_up_a_venv_per_step_with_the_requirements_and_kaos_lib_where_used(repo, venv_stub, capsys):
    assert cli.main(["dev", str(repo), "--kaos-lib", "kaos-lib[zitadel]==0.4.0rc20"]) == 0
    assert requirements_of(repo, "data_summary") == ["PyYAML"]                       # AC-32: PyYAML only
    lib = requirements_of(repo, "dataset_loading")
    assert lib[-1] == "kaos-lib[zitadel]==0.4.0rc20" and lib[0].startswith("--extra-index-url") and "kaos-lib-rc" in lib[0]
    assert not (repo / "steps/model_training/.venv").exists()                         # torch: skipped by default
    out = capsys.readouterr().out
    assert "model-training: skipped, its dependencies are large (torch" in out and "kaosctl dev --step model-training" in out


def test_should_set_up_a_heavy_step_when_it_is_named_or_all_is_given(repo, venv_stub):
    assert cli.main(["dev", str(repo), "--step", "model-training"]) == 0
    assert requirements_of(repo, "model_training")[0] == "torch==2.3.1"
    assert venv_stub.calls and any(c[:2] == ["/usr/bin/uv", "venv"] for c in venv_stub.calls)


def test_should_write_the_interpreter_hint_into_each_step_folder(repo, venv_stub):
    cli.main(["dev", str(repo), "--step", "data-summary"])
    settings = json.loads((repo / "steps/data_summary/.vscode/settings.json").read_text())
    assert settings == {"python.defaultInterpreterPath": vscode.interpreter_value()}
    assert settings["python.defaultInterpreterPath"].startswith("${workspaceFolder}/.venv/")


def test_should_merge_into_an_existing_settings_file_and_leave_a_commented_one_alone(repo, venv_stub, capsys):
    d = repo / "steps/data_summary/.vscode"
    d.mkdir()
    (d / "settings.json").write_text('{"editor.tabSize": 2}')
    cli.main(["dev", str(repo), "--step", "data-summary"])
    assert json.loads((d / "settings.json").read_text())["editor.tabSize"] == 2
    (d / "settings.json").write_text('// mine\n{"a": 1}\n')
    cli.main(["dev", str(repo), "--step", "data-summary"])
    assert (d / "settings.json").read_text().startswith("// mine") and "left" in capsys.readouterr().out


def test_should_be_idempotent_and_install_nothing_the_second_time(repo, venv_stub, capsys):
    cli.main(["dev", str(repo), "--step", "data-summary"])
    first = len(venv_stub.installs())
    capsys.readouterr()
    assert cli.main(["dev", str(repo), "--step", "data-summary"]) == 0
    assert len(venv_stub.installs()) == first and "up-to-date" in capsys.readouterr().out


def test_should_install_again_when_the_dependencies_change(repo, venv_stub):
    cli.main(["dev", str(repo), "--step", "data-summary"])
    (repo / "steps/data_summary/Dockerfile").write_text(
        "FROM python:3.11-slim\nRUN pip install --no-cache-dir PyYAML rich\n")
    cli.main(["dev", str(repo), "--step", "data-summary"])
    assert len(venv_stub.installs()) == 2 and "rich" in requirements_of(repo, "data_summary")


def test_should_ignore_the_environment_in_git_without_editing_any_repository_file(repo, venv_stub):
    cli.main(["dev", str(repo), "--step", "data-summary"])
    assert (repo / "steps/data_summary/.venv/.gitignore").read_text() == "*\n"
    assert not (repo / ".gitignore").exists()


def test_should_suggest_uv_and_fall_back_to_pip_when_uv_is_missing(repo, monkeypatch, capsys):
    stub = VenvStub("3.11")
    monkeypatch.setattr(proc, "run", stub)
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: None)
    assert cli.main(["dev", str(repo), "--step", "data-summary"]) == 0
    out = capsys.readouterr().out
    assert "uv" in out and "kaosctl does not install it" in out and "https://docs.astral.sh/uv" in out
    assert any(c[1:3] == ["-m", "venv"] for c in stub.calls) and any(c[1:4] == ["-m", "pip", "install"] for c in stub.calls)
    assert not [c for c in stub.calls if c[0] == "/usr/bin/uv"]


def test_should_say_when_the_python_of_the_image_is_not_on_this_machine(repo, monkeypatch, capsys):
    monkeypatch.setattr(proc, "run", VenvStub("3.13"))
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: None)
    monkeypatch.setattr("sys.version_info", (3, 13, 1, "final", 0))
    cli.main(["dev", str(repo), "--step", "data-summary"])
    assert "Python 3.11 (the version of the step's image) was not found" in capsys.readouterr().out


def test_should_never_let_uv_download_a_python(repo, venv_stub):
    cli.main(["dev", str(repo), "--step", "data-summary"])
    assert all("--no-python-downloads" in c for c in venv_stub.calls if c[:2] == ["/usr/bin/uv", "venv"])


def test_should_fail_with_the_install_output_when_a_package_cannot_be_installed(repo, monkeypatch, capsys):
    stub = VenvStub()
    def failing(argv, **kw):
        res = stub(argv, **kw)
        return proc.Result(1, "", "No matching distribution found for PyYAML") if "install" in argv else res
    monkeypatch.setattr(proc, "run", failing)
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: "/usr/bin/uv" if name == "uv" else None)
    assert cli.main(["dev", str(repo), "--step", "data-summary"]) == 1
    cap = capsys.readouterr()
    assert "No matching distribution" in cap.out and "could not be set up: data-summary" in cap.err


def test_should_build_a_real_environment_offline_for_a_step_with_no_dependencies(tmp_path, capsys):
    """No stub: a real `python -m venv` (or uv) for a step that installs nothing, so no network is needed."""
    repo = template_repo(tmp_path / "app", {"steps/data_summary/Dockerfile": "FROM python:3.11-slim\nCOPY app/ ./app/\n"})
    code = cli.main(["dev", str(repo), "--step", "data-summary"])
    if code != 0:
        pytest.skip("this machine cannot create a virtual environment here: " + capsys.readouterr().out[-300:])
    py = pyenv.venv_python(repo / "steps/data_summary/.venv")
    assert py.is_file() and (repo / "steps/data_summary/.venv/.kaos-env.json").is_file()
