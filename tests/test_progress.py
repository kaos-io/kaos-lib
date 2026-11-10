"""kaos_lib.progress: the step's progress line (and MLflow tags), and the framework hooks that report by themselves."""
import importlib
import json
import sys
import types

import pytest

from kaos_lib import frameworks, progress

from test_checkpoint_frameworks import FAKES


class Clock:
    now = 100.0


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(progress.time, "monotonic", lambda: c.now)
    monkeypatch.delenv(progress.OFF_ENV, raising=False)
    progress.reset()
    yield c
    progress.reset()


def lines(capsys):
    return [progress.parse(line) for line in capsys.readouterr().out.splitlines() if progress.parse(line)]


def test_a_report_prints_one_line_a_log_reader_can_parse(clock, capsys):
    assert progress.report(34, 100, "epoch") is True
    out = capsys.readouterr().out.strip()
    assert out.startswith("KAOS_PROGRESS {")
    rec = progress.parse("2026-11-10T10:00:00Z stdout F " + out)     # a log prefix does not hide it
    assert (rec["done"], rec["total"], rec["unit"], rec["v"]) == (34, 100, "epoch", 1) and rec["t"] > 0


def test_total_is_optional_and_done_never_passes_it(clock, capsys):
    progress.report(7, unit="file")
    clock.now += 60
    progress.report(12, 10, "file")
    first, last = lines(capsys)
    assert "total" not in first and first["done"] == 7
    assert (last["done"], last["total"]) == (10, 10)


def test_lines_are_rate_limited_but_the_last_one_always_prints(clock, capsys):
    assert progress.report(1, 1000, "step")
    assert not progress.report(2, 1000, "step"), "inside the interval"
    clock.now += progress.MIN_INTERVAL_S
    assert progress.report(3, 1000, "step")
    assert not progress.report(3, 1000, "step") and not progress.report(4, 1000, "step")
    assert progress.report(1000, 1000, "step"), "done == total prints at once"
    assert [r["done"] for r in lines(capsys)] == [1, 3, 1000]


def test_a_new_unit_prints_at_once(clock, capsys):
    progress.report(1, 5, "epoch")
    assert progress.report(1, 300, "batch")
    assert [r["unit"] for r in lines(capsys)] == ["epoch", "batch"]


@pytest.mark.parametrize("done,total", [("3", 10), (None, 10), (float("nan"), 10), (-1, 10), (True, 10),
                                         (3, 0), (3, "ten"), (3, float("inf")), (3, -5)])
def test_values_that_cannot_be_shown_are_dropped_and_never_raise(clock, capsys, done, total):
    assert progress.report(done, total) is False
    captured = capsys.readouterr()
    assert captured.out == "" and "progress not reported" in captured.err
    assert progress.report(done, total) is False
    assert capsys.readouterr().err == "", "said once"


def test_the_unit_is_a_short_plain_word(clock, capsys):
    progress.report(1, 2, "  Epoch {evil}\n" + "x" * 80)
    (rec,) = lines(capsys)
    assert rec["unit"].startswith("epochevil") and len(rec["unit"]) == progress.UNIT_MAX


def test_it_can_be_turned_off(clock, capsys, monkeypatch):
    monkeypatch.setenv(progress.OFF_ENV, "0")
    assert progress.report(1, 2) is False and capsys.readouterr().out == ""


def test_an_active_mlflow_run_gets_the_same_values_as_tags_and_a_broken_mlflow_is_ignored(clock, capsys, monkeypatch):
    tags = {}
    fake = types.SimpleNamespace(active_run=lambda: object(), set_tags=tags.update)
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    progress.report(2, 8, "epoch")
    assert tags == {"kaos.progress.done": "2", "kaos.progress.total": "8", "kaos.progress.unit": "epoch"}

    def boom(_):
        raise RuntimeError("tracking server down")
    fake.set_tags = boom
    clock.now += 60
    assert progress.report(3, 8, "epoch") is True, "the line still prints"


def test_no_mlflow_run_means_no_tags_and_mlflow_is_never_imported(clock, monkeypatch):
    monkeypatch.delitem(sys.modules, "mlflow", raising=False)
    progress.report(1, 2)
    assert "mlflow" not in sys.modules


@pytest.mark.parametrize("line", ["", "training epoch 3/100", "KAOS_PROGRESS not-json", 'KAOS_PROGRESS {"v":2,"done":1}',
                                  'KAOS_PROGRESS {"v":1,"done":"x"}', 'KAOS_PROGRESS {"v":1,"done":1,"total":0}',
                                  'KAOS_PROGRESS [1,2]'])
def test_parse_refuses_anything_that_is_not_a_progress_line(line):
    assert progress.parse(line) is None


# ---------------------------------------------------------------------------- the frameworks report by themselves

@pytest.fixture
def fakes(tmp_path, monkeypatch, clock):
    """The fake frameworks of the checkpoint tests, with NO checkpoint folder: progress must not need one."""
    for rel, body in FAKES.items():
        f = tmp_path / "fw" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    monkeypatch.syspath_prepend(str(tmp_path / "fw"))
    monkeypatch.delenv("KAOS_CHECKPOINT_DIR", raising=False)
    for name in list(sys.modules):
        if name.split(".")[0] in ("ultralytics", "pytorch_lightning", "transformers"):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(frameworks, "_patched", {})
    frameworks.install()
    yield tmp_path
    if frameworks._finder in sys.meta_path:
        sys.meta_path.remove(frameworks._finder)


def test_ultralytics_reports_epochs_without_a_checkpoint_folder(fakes, capsys):
    trainer = importlib.import_module("ultralytics.engine.trainer").BaseTrainer(overrides={"save_dir": str(fakes)})
    trainer.epochs, trainer.epoch = 100, 33
    for fn in trainer.callbacks["on_fit_epoch_end"]:
        fn(trainer)
    (rec,) = lines(capsys)
    assert (rec["done"], rec["total"], rec["unit"]) == (34, 100, "epoch")


def test_lightning_reports_epochs_or_steps(fakes, capsys, clock):
    trainer = importlib.import_module("pytorch_lightning.trainer.trainer").Trainer()
    trainer.max_epochs, trainer.max_steps = 20, -1
    trainer.fit(object())
    (cb,) = [c for c in trainer.callbacks if type(c).__name__ == "KaosProgress"]
    trainer.current_epoch = 4
    cb.on_train_epoch_end(trainer, None)
    trainer.max_epochs, trainer.max_steps, trainer.global_step = -1, 5000, 1200
    cb.on_train_epoch_end(trainer, None)
    epoch, step = lines(capsys)
    assert (epoch["done"], epoch["total"], epoch["unit"]) == (5, 20, "epoch")
    assert (step["done"], step["total"], step["unit"]) == (1200, 5000, "step")


def test_huggingface_reports_steps(fakes, capsys):
    trainer = importlib.import_module("transformers.trainer").Trainer(str(fakes / "out"))
    trainer.train()
    recs = lines(capsys)
    assert recs and recs[0]["unit"] == "step" and recs[0]["done"] == 1 and "total" not in recs[0]


def test_importing_kaos_lib_in_a_pipeline_step_installs_the_hooks(monkeypatch):
    import kaos_lib
    monkeypatch.delenv("KAOS_CHECKPOINT_DIR", raising=False)
    monkeypatch.setenv("KUBECORE_RUN_ID", "wf-1")
    monkeypatch.delenv("KAOS_LIB_SUPPORT", raising=False)
    if frameworks._finder in sys.meta_path:
        sys.meta_path.remove(frameworks._finder)
    importlib.reload(kaos_lib)
    try:
        assert frameworks._finder in sys.meta_path
    finally:
        sys.meta_path.remove(frameworks._finder)
