"""A continued run logs into the MLflow run it continues without the parameter clash (live bug 2026-11-08: Ultralytics'
MLflow callback failed to initialize on attempt 2 because model/data/resume differ). Fake mlflow keeps MLflow's rule:
a parameter, once logged, cannot change."""
import importlib
import sys

import pytest

from kaos_lib import checkpoint, frameworks

FAKE_MLFLOW = {
    "mlflow/__init__.py": "",
    "mlflow/tracking/__init__.py": "",
    "mlflow/tracking/client.py": '''
class MlflowException(Exception):
    pass
class Param:
    def __init__(self, key, value):
        self.key, self.value = key, value
class _Data:
    def __init__(self, params): self.params = params
class _Run:
    def __init__(self, params): self.data = _Data(params)
STORE = {}
class MlflowClient:
    def get_run(self, run_id):
        return _Run(dict(STORE.setdefault(run_id, {"params": {}, "metrics": [], "tags": {}})["params"]))
    def log_batch(self, run_id, metrics=(), params=(), tags=()):
        run = STORE.setdefault(run_id, {"params": {}, "metrics": [], "tags": {}})
        if any(p.key == "boom" for p in params):
            raise MlflowException("INVALID_PARAMETER_VALUE: Something else")
        changed = [p.key for p in params if p.key in run["params"] and run["params"][p.key] != str(p.value)]
        if changed:
            raise MlflowException("INVALID_PARAMETER_VALUE: Changing param values is not allowed. %s" % changed)
        run["params"].update({p.key: str(p.value) for p in params})
        run["metrics"].extend(metrics)
        run["tags"].update(tags)
''',
}


@pytest.fixture
def mlflow_client(tmp_path, monkeypatch):
    for rel, text in FAKE_MLFLOW.items():
        f = tmp_path / "fakes" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    monkeypatch.syspath_prepend(str(tmp_path / "fakes"))
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path))
    monkeypatch.delenv(checkpoint.HOOKS_ENV, raising=False)
    saved_path, saved_patched = list(sys.meta_path), dict(frameworks._patched)
    frameworks._patched.clear()
    frameworks.install()
    module = importlib.import_module("mlflow.tracking.client")
    yield module
    sys.meta_path[:] = saved_path
    frameworks._patched.clear()
    frameworks._patched.update(saved_patched)
    for name in [m for m in sys.modules if m.split(".")[0] == "mlflow"]:
        del sys.modules[name]


def params(module, **kv):
    return [module.Param(k, v) for k, v in kv.items()]


FIRST = dict(model="yolov8n-pose.pt", data="/tmp/a/data.yaml", resume="False", epochs="2000")
SECOND = dict(model="/work/ckpt/ckpt-000001/last.pt", data="/tmp/b/data.yaml", resume="/work/ckpt/ckpt-000001/last.pt",
              epochs="2000", batch="16")


def test_should_log_changed_params_under_resume_prefix_when_run_is_continued(mlflow_client):
    client = mlflow_client.MlflowClient()
    client.log_batch("r1", params=params(mlflow_client, **FIRST))
    client.log_batch("r1", metrics=["m"], params=params(mlflow_client, **SECOND))       # must not raise
    logged = client.get_run("r1").data.params
    assert logged["model"] == "yolov8n-pose.pt", "the first attempt's value is kept"
    assert logged["resume.model"] == "/work/ckpt/ckpt-000001/last.pt"
    assert logged["resume.data"] == "/tmp/b/data.yaml" and logged["batch"] == "16"
    assert "resume.epochs" not in logged, "unchanged params are not repeated"
    assert mlflow_client.STORE["r1"]["metrics"] == ["m"], "metrics in the same batch are logged"


def test_should_be_idempotent_when_the_same_continuation_logs_twice(mlflow_client):
    client = mlflow_client.MlflowClient()
    client.log_batch("r1", params=params(mlflow_client, **FIRST))
    client.log_batch("r1", params=params(mlflow_client, **SECOND))
    client.log_batch("r1", params=params(mlflow_client, **SECOND))
    assert client.get_run("r1").data.params["resume.model"] == "/work/ckpt/ckpt-000001/last.pt"


def test_should_skip_a_resume_param_that_itself_clashes_on_a_third_attempt(mlflow_client):
    client = mlflow_client.MlflowClient()
    client.log_batch("r1", params=params(mlflow_client, **FIRST))
    client.log_batch("r1", params=params(mlflow_client, **SECOND))
    third = dict(SECOND, data="/tmp/c/data.yaml")
    client.log_batch("r1", params=params(mlflow_client, **third))                      # must not raise
    assert client.get_run("r1").data.params["resume.data"] == "/tmp/b/data.yaml"


def test_should_pass_other_errors_through_unchanged(mlflow_client):
    client = mlflow_client.MlflowClient()
    with pytest.raises(mlflow_client.MlflowException, match="Something else"):
        client.log_batch("r1", params=params(mlflow_client, boom="1"))


def test_should_not_import_mlflow_when_the_step_did_not(tmp_path, monkeypatch):
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(tmp_path))
    saved = list(sys.meta_path)
    try:
        frameworks.install()
        assert "mlflow" not in sys.modules
    finally:
        sys.meta_path[:] = saved
