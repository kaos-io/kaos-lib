import importlib.util
from pathlib import Path

import pytest
from kaos_lib import checkpoint, testing


def load(step_folder):
    path = Path(__file__).parents[1] / "steps" / step_folder / "app" / "entry.py"
    spec = importlib.util.spec_from_file_location(step_folder, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_train_continues_from_its_checkpoint_after_a_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("KAOS_CHECKPOINT_DIR", str(tmp_path / "checkpoints"))
    stop = iter([False, True])  # the platform asks for the machine back after the second epoch
    monkeypatch.setattr(checkpoint, "stop_requested", lambda: next(stop, False))
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.txt").write_text("abcd")
    step = dict(kind="train", params={"train": {"epochs": 5}}, upstream_writes={"prepare": {"clean": clean}},
                produces=[("model", "model")])
    with pytest.raises(SystemExit) as stopped, testing.running(tmp_path / "first", **step):
        load("train").main()
    assert stopped.value.code == 85
    with testing.running(tmp_path / "second", **step) as run:
        load("train").main()
    assert (run.output("model") / "weights.txt").read_text() == "20\n"  # 5 epochs of 4 bytes
