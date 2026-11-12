"""F-30, D-16: `kaosctl step run` on a repository shaped like the templates: the step is started as the platform starts
it (no arguments, the step context), its inputs are folders on this machine, its outputs and its result stay in
`.kaos/local`, no platform secret is in its environment or files (AC-35), and it runs offline (AC-32). The step's
environment is the Python running the tests."""
import json
import sys
import os
import re

import pytest

from kaos_lib import cli
from kaos_lib.studio import envallow, pipeline_engine, proc, pyenv, run, sample, steps
from fake_lakefs import FakeLakeFS
from studio_helpers import fake_venv, template_repo

SECRETS = {"LAKEFS_ACCESS_KEY": "AKIA-SECRET-1", "LAKEFS_SECRET_KEY": "s3cr3t-2", "LAKEFS_ENDPOINT": "http://lakefs.internal",
           "MLFLOW_TRACKING_URI": "http://mlflow.internal", "MLFLOW_TRACKING_TOKEN": "tok-3", "AWS_SECRET_ACCESS_KEY": "aws-4",
           "KUBECONFIG": "/home/u/.kube/config", "KUBERNETES_SERVICE_HOST": "10.0.0.1", "ZITADEL_MACHINE_KEY_FILE": "/k.json"}
DUMP_ENTRY = '''import json, os, pathlib, sys
from kaos_lib import step
step.start()
out = step.output("summary")
env = dict(os.environ)
context = json.loads(env.pop("KAOS_STEP_CONTEXT"))
(out / "env.json").write_text(json.dumps(env))
(out / "argv.json").write_text(json.dumps(sys.argv))
(out / "context.json").write_text(json.dumps(context))
print("in /work:", sorted(os.listdir("/work")), "cwd:", os.getcwd())
step.result()
'''


PARAMS = "summary:\n  label: Data summary\ndata:\n  seed: 42\ndataset: dataset-default@v1\n"
real_resolve_pin = pipeline_engine.resolve_pin


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An app, and a stand-in for the platform's pipeline engine that composes ``PARAMS`` plus the overrides."""
    def compose(root, py, profile, overrides, output):
        text = PARAMS + "".join(token.replace("=", ": ", 1) + "\n" for token in overrides)
        output.write_text(text)
        return text

    monkeypatch.setattr(pipeline_engine, "resolve_pin", lambda *a, **k: None)
    monkeypatch.setattr(pipeline_engine, "ensure", lambda *a, **k: None)
    monkeypatch.setattr(pipeline_engine, "profile_of", lambda *a, **k: "hera")
    monkeypatch.setattr(pipeline_engine, "compose", compose)
    root = template_repo(tmp_path / "app")
    for s in steps.discover(root):
        fake_venv(s.path)
    import kaos_lib                                      # the step's environment holds this kaos-lib
    monkeypatch.setenv("PYTHONPATH", os.path.dirname(os.path.dirname(kaos_lib.__file__)))
    monkeypatch.setattr(envallow, "allowed", lambda env, real=envallow.allowed: {
        **real(env), "PYTHONPATH": env.get("PYTHONPATH", "")})
    return root


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "my-images"
    (folder / "train").mkdir(parents=True)
    for name in ("a.jpg", "b.jpg", "train/c.jpg"):
        (folder / name).write_bytes(b"img")
    return folder


def kept(repo, step):
    return json.loads((repo / f".kaos/local/results/{step}.json").read_text())


def test_should_run_the_data_summary_step_offline_and_print_its_summary_and_result(repo, monkeypatch, capsys):
    """AC-32: prints its summary line and exits 0 with no network and no platform: only the composed params."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")                # nothing reachable
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Data summary: seed=42 info=None" in out and "exited 0" in out
    assert 'values: {"seed": 42}' in out and "wrote   summary (artifact)" in out
    assert kept(repo, "data-summary")["values"] == {"seed": 42}
    assert json.loads((repo / ".kaos/local/staged/summary/summary.json").read_text()) == {"seed": 42}
    assert (repo / ".kaos/local/.gitignore").read_text() == "*\n"


def test_should_start_the_step_as_the_platform_does_with_no_arguments_and_the_step_context(repo, monkeypatch):
    seen = {}
    real = proc.stream
    monkeypatch.setattr(proc, "stream", lambda argv, **kw: seen.update(argv=argv, **kw) or real(argv, **kw))
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    assert seen["argv"][2:] == ["app.entry"]                            # [python, workmap.py, module]: no arguments
    assert seen["cwd"] == repo / "steps/data_summary"
    text = seen["env"]["KAOS_STEP_CONTEXT"]
    assert "{{" not in text and text.isascii() and "\n" not in text    # the contract's wire form
    context = json.loads(text)
    assert list(context) == ["version", "run", "app", "project", "step", "kind", "experiment", "params", "ledger",
                             "produces", "upstream"]
    assert (context["app"], context["step"], context["kind"]) == ("app", "data-summary", "evaluate")
    assert re.fullmatch(r"local-\d{8}t\d{6}z", context["run"])          # every local run has its own name
    assert context["experiment"] == "app"                                # no experiment.name in the config: the app
    assert context["params"] == {"data": {"seed": 42}, "summary": {"label": "Data summary"}}   # only what reads= names
    assert context["produces"] == [{"name": "summary", "type": "artifact", "repo": "outputs-app"}]
    assert context["upstream"] == {"dataset-loading": {"version": 1, "status": "absent"}}


def test_should_give_a_step_a_local_folder_as_its_input_and_keep_what_it_produces(repo, images, capsys):
    assert cli.main(["step", "run", "dataset-loading", str(repo), "--input", f"dataset={images}"]) == 0
    out = capsys.readouterr().out
    assert f"input dataset: the folder {images}" in out and "loading 3 files" in out
    result = kept(repo, "dataset-loading")
    assert result["values"] == {"files": 3}
    assert [(r["name"], r["repo"], r["ref"]) for r in result["reads"]] == [("dataset", "dataset-default", "v1")]
    assert [(w["name"], w["type"], w["repo"]) for w in result["writes"]] == [("clean", "dataset", "dataset-app-clean")]
    staged = repo / ".kaos/local/staged"
    assert sorted(p.name for p in (staged / "clean").iterdir()) == ["a.jpg", "b.jpg", "c.jpg"]   # only the files
    assert sorted(p.name for p in (staged / "dataset").rglob("*") if p.is_file()) == ["a.jpg", "b.jpg", "c.jpg"]
    assert json.loads((staged / "clean.kaos-ready").read_text())["full"] is True and (staged / "dataset.kaos-ready").is_file()
    assert not list(images.glob("*.kaos-ready"))                        # the user's folder is never written to


def test_the_next_step_gets_the_result_of_the_last_local_run_of_the_step_it_needs(repo, images, capsys):
    assert cli.main(["step", "run", "dataset-loading", str(repo), "--input", f"dataset={images}"]) == 0
    capsys.readouterr()
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "upstream dataset-loading: from its last local run" in out and "info={'files': 3}" in out


def test_should_say_when_a_needed_step_did_not_run_here(repo, capsys):
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    assert "upstream dataset-loading: did not run here" in capsys.readouterr().out


def test_should_take_an_upstream_result_from_the_command_line_or_a_file(repo, tmp_path, capsys):
    result = {"version": 1, "status": "ok", "values": {"from": "file"}, "reads": [], "writes": []}
    f = tmp_path / "result.json"
    f.write_text(json.dumps(result))
    assert cli.main(["step", "run", "data-summary", str(repo), "--upstream", f"dataset-loading=@{f}"]) == 0
    assert "info={'from': 'file'}" in capsys.readouterr().out
    given = json.dumps(dict(result, values={"x": 1}))
    assert cli.main(["step", "run", "data-summary", str(repo), "--upstream", f"dataset-loading={given}"]) == 0
    assert "info={'x': 1}" in capsys.readouterr().out


@pytest.mark.parametrize("argv,fragment", [
    (["dataset-loading"], "dataset-loading reads the input 'dataset'. Give it with --input dataset=<folder>"),
    (["data-summary", "--input", "images=/tmp"], "data-summary has no input 'images'"),
    (["dataset-loading", "--input", "dataset"], "write NAME=<folder> or NAME=<dataset>@<version>"),
    (["data-summary", "--upstream", "model-training={}"], "for a step data-summary needs (dataset-loading)"),
    (["data-summary", "--upstream", "dataset-loading={oops"], "the result given for dataset-loading is not JSON"),
])
def test_should_say_what_is_missing_or_wrong_before_starting_the_step(repo, capsys, argv, fragment):
    assert cli.main(["step", "run", argv[0], str(repo), *argv[1:]]) == 1
    assert fragment in capsys.readouterr().err


def test_should_ask_for_a_kind_when_the_step_has_none(repo, capsys):
    text = (repo / "pipeline.py").read_text().replace('kind="evaluate", ', "")
    (repo / "pipeline.py").write_text(text)
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 1
    assert 'data-summary has no kind in pipeline.py: add kind="..."' in capsys.readouterr().err


def test_should_pass_config_overrides_to_the_composition(repo, capsys):
    assert cli.main(["step", "run", "data-summary", str(repo), "--set", "data.seed=7"]) == 0
    assert "seed: 7" in (repo / ".kaos/local/params.yaml").read_text()


def test_should_use_a_given_params_file_without_composing(repo, tmp_path, capsys):
    p = tmp_path / "p.yaml"
    p.write_text("summary:\n  label: mine\ndata:\n  seed: 9\n")
    assert cli.main(["step", "run", "data-summary", str(repo), "--params-file", str(p)]) == 0
    assert "mine: seed=9" in capsys.readouterr().out and not (repo / ".kaos/local/params.yaml").exists()


def test_should_hold_no_platform_secret_in_the_steps_environment_or_in_any_file(repo, monkeypatch, capsys):
    """AC-35: nothing the platform injects reaches the run, even when the user's shell exports it."""
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    (repo / "steps/data_summary/app/entry.py").write_text(DUMP_ENTRY)
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    env = json.loads((repo / ".kaos/local/staged/summary/env.json").read_text())
    assert not (set(env) & set(SECRETS)) and not envallow.leaked(env), sorted(env)
    for path in (repo / ".kaos/local").rglob("*"):
        if path.is_file():
            text = path.read_text(errors="ignore")
            assert not [v for v in SECRETS.values() if v in text], path
    assert env["KAOS_LOCAL_WORK"].endswith("work/data-summary") and env["KAOS_STAGED_ROOT"].endswith("staged")


def test_should_say_clearly_when_a_step_reads_a_platform_service(repo, capsys):
    (repo / "steps/data_summary/app/entry.py").write_text(
        'import os\nprint("uri:", os.environ.get("MLFLOW_TRACKING_URI", "unset"))\n')
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "this step reads MLFLOW_TRACKING_URI, which only the platform sets" in out and "uri: unset" in out


def test_should_map_the_platforms_work_folder_into_the_local_folder(repo, capsys):
    (repo / "steps/data_summary/app/entry.py").write_text(DUMP_ENTRY)
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    assert not os.path.exists("/work/output/kaos-result.json")           # nothing was written to the machine's root
    assert (repo / ".kaos/local/work/data-summary/output/kaos-result.json").is_file()
    assert "in /work: ['kaos']" in capsys.readouterr().out


def test_should_return_the_steps_exit_code_and_say_that_it_left_no_result(repo, capsys):
    (repo / "steps/data_summary/app/entry.py").write_text("import sys\nsys.exit(3)\n")
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 3
    cap = capsys.readouterr()
    assert "Result of data-summary: none written" in cap.out and "exited with code 3" in cap.err
    assert not (repo / ".kaos/local/results/data-summary.json").exists()


def test_a_step_that_ends_without_a_result_fails_here_as_it_would_on_the_platform(repo, capsys):
    (repo / "steps/data_summary/app/entry.py").write_text("from kaos_lib import step\nstep.start()\nprint('done')\n")
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 1
    assert "none written" in capsys.readouterr().out


def test_should_name_the_known_steps_for_an_unknown_one(repo, capsys):
    assert cli.main(["step", "run", "nope", str(repo)]) == 1
    assert "Steps: dataset-loading" in capsys.readouterr().err


def test_should_set_up_the_environment_first_when_the_step_has_none(tmp_path, monkeypatch, capsys, repo):
    import shutil
    shutil.rmtree(pyenv.step_env(repo / "steps/data_summary"), ignore_errors=True)
    calls = []

    def setup(step, flag, ctx, uv, echo=print):
        calls.append(step.name)
        fake_venv(step.path)
        from kaos_lib.studio.dev import DevOutcome
        return DevOutcome(step.name, "created")
    monkeypatch.setattr(run, "setup_step", setup)
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    assert calls == ["data-summary"] and "has no environment yet" in capsys.readouterr().out


def test_should_ask_for_the_engine_or_a_params_file_when_none_is_given(repo, capsys, monkeypatch):
    monkeypatch.setattr(pipeline_engine, "resolve_pin", real_resolve_pin)
    monkeypatch.delenv("KAOS_ENGINE_WHEEL", raising=False)
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "no pipeline engine was given" in err and "--context" in err and "pass --params-file" in err
    assert err.index("--params-file") < err.index("--context") and "pipeline-context" in err


def test_should_take_a_small_sample_of_a_dataset_as_an_input(repo, monkeypatch, capsys):
    fake = FakeLakeFS()
    fake.add_repo("dataset-cats", metadata={"kaos.kind": "dataset"},
                  files={"readme.txt": b"cats", **{f"images/{i}.jpg": b"x" * 400_000 for i in range(10)}})
    fake.tag("dataset-cats", "v1")
    monkeypatch.setattr(sample.LakeFS, "connect", classmethod(lambda cls, *a, **k: fake.client()))
    assert cli.main(["step", "run", "dataset-loading", str(repo), "--input", "dataset=dataset-cats@v1",
                     "--sample-mb", "1"]) == 0
    assert "input dataset: a sample of dataset-cats@v1 (" in capsys.readouterr().out
    read = kept(repo, "dataset-loading")["reads"][0]
    assert (read["name"], read["repo"], read["ref"]) == ("dataset", "dataset-cats", "v1")
    assert 1 < kept(repo, "dataset-loading")["values"]["files"] < 11


# --- the dataset sample (through the same client as `kaosctl dataset pull`) -------------------------------------

def test_should_choose_root_files_first_then_spread_over_folders_within_the_size(tmp_path):
    objects = [{"path": "data.yaml", "size_bytes": 10}] + [
        {"path": f"{d}/f{i}.jpg", "size_bytes": 100 + i} for d in ("train", "val") for i in range(5)]
    picked = [o["path"] for o in sample.choose(objects, 450)]
    assert picked[0] == "data.yaml" and "train/f0.jpg" in picked and "val/f0.jpg" in picked
    assert sum(o["size_bytes"] for o in sample.choose(objects, 450)) <= 450
    assert [o["path"] for o in sample.choose(objects, 450)] == picked      # deterministic


def test_should_download_only_a_small_sample_of_a_dataset(tmp_path):
    fake = FakeLakeFS()
    files = {"data.yaml": b"names: [a]\n", **{f"images/{i}.jpg": b"x" * 400_000 for i in range(10)}}
    fake.add_repo("dataset-cats", files=files)
    fake.tag("dataset-cats", "v1")
    count, size = sample.pull_sample("dataset-cats@v1", tmp_path / "d", 1, client=fake.client())
    assert 1 < count < 11 and size <= 1024 * 1024 and (tmp_path / "d/data.yaml").is_file()


def test_should_refuse_to_sample_a_dataset_with_no_files(tmp_path):
    from kaos_lib.errors import KaosLibError
    fake = FakeLakeFS()
    fake.add_repo("dataset-empty")
    with pytest.raises(KaosLibError, match="holds no files"):
        sample.pull_sample("dataset-empty@latest", tmp_path / "d", 1, client=fake.client())


def _app_files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if ".kaos" not in p.parts and "__pycache__" not in p.parts)


def test_should_run_the_step_with_the_given_python_and_build_no_environment(repo, tmp_path, monkeypatch, capsys):
    import shutil
    for s in steps.discover(repo):
        shutil.rmtree(pyenv.step_env(s.path), ignore_errors=True)      # no environment exists for any step
    before = _app_files(repo)
    monkeypatch.setattr(run, "setup_step", lambda *a, **k: pytest.fail("an environment was built"))
    assert cli.main(["step", "run", "data-summary", str(repo), "--python", sys.executable]) == 0
    assert _app_files(repo) == before and not list(repo.rglob(".venv"))
    assert not pyenv.step_env(repo / "steps/data_summary").exists()


def test_should_refuse_a_python_that_is_missing_or_has_no_kaos_lib(repo, tmp_path, capsys):
    assert cli.main(["step", "run", "data-summary", str(repo), "--python", str(tmp_path / "nope")]) == 1
    assert "no such interpreter" in capsys.readouterr().err
    bare = tmp_path / "bare-python"
    bare.write_text('#!/bin/sh\nexit 1\n')
    bare.chmod(0o755)
    assert cli.main(["step", "run", "data-summary", str(repo), "--python", str(bare)]) == 1
    assert "cannot import kaos_lib" in capsys.readouterr().err


def test_should_resolve_a_relative_python_against_the_folder_the_command_was_called_from(repo, tmp_path, monkeypatch):
    here = tmp_path / "here"
    (here / "bin").mkdir(parents=True)
    link = here / "bin" / "py"
    link.symlink_to(sys.executable)
    monkeypatch.chdir(here)
    seen = {}
    real = run.proc.stream
    monkeypatch.setattr(run.proc, "stream", lambda argv, **kw: seen.update(argv=argv) or real(argv, **kw))
    assert cli.main(["step", "run", "data-summary", str(repo), "--python", "bin/py"]) == 0
    assert seen["argv"][0] == str(link)                        # absolute: the step starts in its own folder


def test_should_name_a_relative_python_that_does_not_exist_before_running_anything(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run.proc, "stream", lambda *a, **k: pytest.fail("the step was started"))
    assert cli.main(["step", "run", "data-summary", str(repo), "--python", "venv/bin/python"]) == 1
    err = capsys.readouterr().err
    assert "no such interpreter" in err and str(tmp_path / "venv/bin/python") in err


def test_the_environment_is_keyed_by_the_real_step_folder_so_a_link_puts_nothing_in_the_repository(repo, tmp_path):
    link = tmp_path / "linked-app"
    link.symlink_to(repo)
    real, via = repo / "steps/data_summary", link / "steps/data_summary"
    assert pyenv.step_env(via) == pyenv.step_env(real)
    assert repo not in pyenv.step_env(real).parents and tmp_path / "xdg" in pyenv.step_env(real).parents
    assert pyenv.step_env(repo / "steps/dataset_loading") != pyenv.step_env(real)
    assert cli.main(["step", "run", "data-summary", str(link)]) == 0
    assert not list(repo.rglob(".venv"))
