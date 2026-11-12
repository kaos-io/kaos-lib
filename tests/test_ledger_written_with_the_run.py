"""In a pipeline step the ledger reaches the MLflow run by itself when the run ends: the step calls nothing."""
import importlib
import sys

import pytest

from kaos_lib import frameworks, lock

FAKE_MLFLOW = {
    "mlflow/__init__.py": "from mlflow.tracking.fluent import active_run, end_run, start_run\n",
    "mlflow/tracking/__init__.py": "",
    "mlflow/tracking/fluent.py": '''
ENDED = []
_active = []
class _Info:
    def __init__(self, run_id): self.run_id = run_id
class ActiveRun:
    def __init__(self, run_id): self.info = _Info(run_id)
    def __enter__(self): return self
    def __exit__(self, *exc):
        end_run("FINISHED" if exc[0] is None else "FAILED")
        return False
def start_run(run_id="run-1"):
    _active.append(ActiveRun(run_id)); return _active[-1]
def active_run():
    return _active[-1] if _active else None
def end_run(status="FINISHED"):
    if _active:
        ENDED.append((_active.pop().info.run_id, status))
''',
}


class Recorder:
    """Stands in for the MLflow client the ledger is written with: remembers what was written, per run."""
    def __init__(self, fail=False):
        self.fail, self.tags, self.texts, self.names = fail, {}, {}, {}

    def set_tag(self, run_id, key, value):
        if self.fail:
            raise RuntimeError("tracking server down")
        self.tags.setdefault(run_id, {})[key] = value

    def log_text(self, run_id, text, name):
        self.texts.setdefault(run_id, []).append(text)
        self.names.setdefault(run_id, []).append(name)


@pytest.fixture
def step(tmp_path, monkeypatch):
    for rel, body in FAKE_MLFLOW.items():
        f = tmp_path / "fw" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    monkeypatch.syspath_prepend(str(tmp_path / "fw"))
    for name in [m for m in sys.modules if m == "mlflow" or m.startswith("mlflow.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(frameworks, "_patched", {})
    monkeypatch.setattr(frameworks, "_ledger_written", {})
    lock.reset()
    client = Recorder()
    monkeypatch.setattr(lock, "_client", lambda: client)
    frameworks.install()
    yield client
    lock.reset()
    if frameworks._finder in sys.meta_path:
        sys.meta_path.remove(frameworks._finder)
    for name in [m for m in sys.modules if m == "mlflow" or m.startswith("mlflow.")]:
        del sys.modules[name]                       # the fake must not outlive the test (monkeypatch restores the rest)


def test_leaving_the_run_writes_what_the_step_read(step):
    mlflow = importlib.import_module("mlflow")
    with mlflow.start_run("run-7"):
        lock.record("dataset-a", "latest", "c" * 64)
    assert step.tags["run-7"] == {"kaos_lib.data.dataset-a.commit": "c" * 64}
    assert len(step.texts["run-7"]) == 1 and '"dataset-a"' in step.texts["run-7"][0]
    assert step.names["run-7"] == ["ledger/local.json"]              # not in a pipeline step: the file is "local"
    assert sys.modules["mlflow.tracking.fluent"].ENDED == [("run-7", "FINISHED")]


def test_mlflow_end_run_called_directly_writes_it_too_and_a_failed_run_still_gets_it(step):
    mlflow = importlib.import_module("mlflow")
    mlflow.start_run("run-8")
    lock.record("dataset-a", "v2", "d" * 64)
    mlflow.end_run("FAILED")
    assert "run-8" in step.tags and sys.modules["mlflow.tracking.fluent"].ENDED == [("run-8", "FAILED")]


def test_nothing_read_means_nothing_written_and_an_unchanged_ledger_is_written_once(step):
    mlflow = importlib.import_module("mlflow")
    with mlflow.start_run("run-9"):
        pass
    assert step.tags == {}
    lock.record("dataset-a", "latest", "c" * 64)
    for _ in range(2):                              # a continued run ends twice with the same reads
        with mlflow.start_run("run-9"):
            pass
    assert len(step.texts["run-9"]) == 1


def test_a_tracking_failure_never_keeps_the_run_from_ending(step, capsys):
    step.fail = True
    mlflow = importlib.import_module("mlflow")
    with mlflow.start_run("run-10"):
        lock.record("dataset-a", "latest", "c" * 64)
    assert sys.modules["mlflow.tracking.fluent"].ENDED == [("run-10", "FINISHED")]
    assert "the ledger was not written to MLflow run run-10" in capsys.readouterr().err


def test_mlflow_imported_before_kaos_lib_is_hooked_too(step):
    if frameworks._finder in sys.meta_path:
        sys.meta_path.remove(frameworks._finder)
    for name in [m for m in sys.modules if m == "mlflow" or m.startswith("mlflow.")]:
        del sys.modules[name]
    frameworks._patched.clear()
    mlflow = importlib.import_module("mlflow")      # the plain function is bound as mlflow.end_run
    frameworks.install()
    mlflow.start_run("run-11")
    lock.record("dataset-a", "latest", "c" * 64)
    mlflow.end_run()
    assert "run-11" in step.tags


def test_in_a_pipeline_step_the_file_carries_the_steps_name(step, monkeypatch):
    import pathlib
    wire = (pathlib.Path(__file__).with_name("contract_fixtures") / "context-one-upstream.wire").read_text()
    monkeypatch.setenv("KAOS_STEP_CONTEXT", wire)
    mlflow = importlib.import_module("mlflow")
    with mlflow.start_run("run-12"):
        lock.record("dataset-a", "latest", "c" * 64)
    assert step.names["run-12"] == ["ledger/train.json"]
