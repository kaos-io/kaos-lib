"""F-30, D-16: `kaosctl step run` on fixtures modelled on both templates: the platform's argument contract (AC-37), outputs
(`<name>.json`) under a mapped /work, no platform secret in the environment or the files (AC-35), and a run of the yolo
template's `data-summary` step offline after setup (AC-32). The step's environment is the Python running the tests."""
import json
import os

import pytest

from kaos_lib import cli
from kaos_lib.studio import envallow, proc, run, sample, steps
from fake_lakefs import FakeLakeFS
from studio_helpers import fake_venv, template_repo

SECRETS = {"LAKEFS_ACCESS_KEY": "AKIA-SECRET-1", "LAKEFS_SECRET_KEY": "s3cr3t-2", "LAKEFS_ENDPOINT": "http://lakefs.internal",
           "MLFLOW_TRACKING_URI": "http://mlflow.internal", "MLFLOW_TRACKING_TOKEN": "tok-3", "AWS_SECRET_ACCESS_KEY": "aws-4",
           "KUBECONFIG": "/home/u/.kube/config", "KUBERNETES_SERVICE_HOST": "10.0.0.1", "ZITADEL_MACHINE_KEY_FILE": "/k.json",
           "CHECKPOINT_BUCKET": "outputs-app"}
DUMP_ENTRY = '''import json, os, pathlib, sys
out = pathlib.Path("/work/output"); out.mkdir(parents=True, exist_ok=True)
(out / "env.json").write_text(json.dumps(dict(os.environ)))
(out / "argv.json").write_text(json.dumps(sys.argv))
print("in /work:", sorted(os.listdir("/work")), "cwd:", os.getcwd())
'''


@pytest.fixture
def repo(tmp_path):
    root = template_repo(tmp_path / "app")
    for s in steps.discover(root):
        fake_venv(s.path)
    return root


def test_should_run_the_data_summary_step_offline_and_print_its_summary_and_outputs(repo, monkeypatch, capsys):
    """AC-32: prints its summary line and exits 0 with no network and no platform: only the composed params."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")                # nothing reachable
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Data summary: seed=42" in out and "summary.json" in out and '"seed": 42' in out and "exited 0" in out
    assert (repo / ".kaos/local/outputs/data-summary/summary.json").is_file()
    assert (repo / ".kaos/local/.gitignore").read_text() == "*\n"


def test_should_start_the_step_with_the_platforms_argument_contract(repo, monkeypatch):
    """AC-37: args = --params <composed yaml> then --<out> <json> for every output of every step it needs."""
    seen = {}
    real = proc.stream
    monkeypatch.setattr(proc, "stream", lambda argv, **kw: seen.update(argv=argv, cwd=kw["cwd"]) or real(argv, **kw))
    (repo / ".kaos/local/outputs/dataset-loading").mkdir(parents=True)
    (repo / ".kaos/local/outputs/dataset-loading/dataset-info.json").write_text('{"dataset_commit": "abc"}')
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    module, *args = seen["argv"][2:]                                    # [python, workmap.py, module, ...]
    assert module == "app.entry"                                        # authoring.STEP_COMMAND = python -m app.entry
    assert args[0] == "--params" and "seed: 42" in args[1]               # the composed params' CONTENT, as Argo passes it
    assert args[2:] == ["--dataset-info", '{"dataset_commit": "abc"}']
    assert seen["cwd"] == repo / "steps/data_summary"


def test_should_default_a_missing_upstream_output_to_the_platforms_empty_object(repo, capsys):
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    assert "input --dataset-info: empty ({})" in capsys.readouterr().out


def test_should_take_an_input_from_the_command_line_or_a_file(repo, tmp_path, capsys):
    f = tmp_path / "info.json"
    f.write_text('{"from": "file"}')
    assert cli.main(["step", "run", "data-summary", str(repo), "--input", f"dataset-info=@{f}"]) == 0
    assert "info={'from': 'file'}" in capsys.readouterr().out
    assert cli.main(["step", "run", "data-summary", str(repo), "--input", 'dataset-info={"x": 1}']) == 0
    assert "info={'x': 1}" in capsys.readouterr().out


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
    env = json.loads((repo / ".kaos/local/work/data-summary/output/env.json").read_text())
    assert not (set(env) & set(SECRETS)) and not envallow.leaked(env), sorted(env)
    for path in (repo / ".kaos/local").rglob("*"):
        if path.is_file():
            text = path.read_text(errors="ignore")
            assert not [v for v in SECRETS.values() if v in text], path
    assert env["KUBECORE_RUN_ID"] == "local" and env["KAOS_LOCAL_WORK"].endswith("work/data-summary")


def test_should_say_clearly_when_a_step_reads_a_platform_service(repo, capsys):
    (repo / "steps/data_summary/app/entry.py").write_text(
        'import os\nprint("uri:", os.environ.get("MLFLOW_TRACKING_URI", "unset"))\n')
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "this step reads MLFLOW_TRACKING_URI, which only the platform sets" in out and "uri: unset" in out


def test_should_map_the_platforms_work_folder_into_the_local_folder(repo, capsys):
    (repo / "steps/data_summary/app/entry.py").write_text(DUMP_ENTRY)
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 0
    assert not os.path.exists("/work/output/env.json")                  # nothing was written to the machine's root
    assert (repo / ".kaos/local/work/data-summary/output/argv.json").is_file()
    assert "in /work: ['output']" in capsys.readouterr().out


def test_should_return_the_steps_exit_code_and_still_print_its_outputs(repo, capsys):
    (repo / "steps/data_summary/app/entry.py").write_text(
        'import pathlib, sys\np = pathlib.Path("/work/output"); p.mkdir(parents=True)\n(p / "partial.json").write_text("{}")\nsys.exit(3)\n')
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 3
    cap = capsys.readouterr()
    assert "partial.json" in cap.out and "exited with code 3" in cap.err


def test_should_report_a_declared_output_the_step_did_not_write(repo, capsys):
    (repo / "steps/dataset_loading/app/entry.py").write_text("print('no outputs here')\n")
    assert cli.main(["step", "run", "dataset-loading", str(repo)]) == 0
    assert "dataset-info.json: declared in pipeline.py but not written" in capsys.readouterr().out


def test_should_name_the_known_steps_for_an_unknown_one(repo, capsys):
    assert cli.main(["step", "run", "nope", str(repo)]) == 1
    assert "Steps: dataset-loading" in capsys.readouterr().err


def test_should_set_up_the_environment_first_when_the_step_has_none(tmp_path, monkeypatch, capsys):
    root = template_repo(tmp_path / "app")
    fake_venv(root / "steps/compose_and_validate")
    calls = []

    def setup(step, flag, ctx, uv, echo=print):
        calls.append(step.name)
        fake_venv(step.path)
        from kaos_lib.studio.dev import DevOutcome
        return DevOutcome(step.name, "created")
    monkeypatch.setattr(run, "setup_step", setup)
    assert cli.main(["step", "run", "data-summary", str(root)]) == 0
    assert calls == ["data-summary"] and "has no environment yet" in capsys.readouterr().out


def test_should_refuse_to_compose_without_the_platform_composer_and_ask_for_a_params_file(repo, capsys):
    (repo / "kubecore/compose.py").unlink()
    assert cli.main(["step", "run", "data-summary", str(repo)]) == 1
    assert "pass --params-file" in capsys.readouterr().err


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
