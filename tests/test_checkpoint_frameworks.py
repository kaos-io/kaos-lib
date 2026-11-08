"""Automatic framework hooks (kaos_lib.frameworks) against small fake frameworks: lazy attach, periodic and
stop-driven saves into KAOS_CHECKPOINT_DIR, resume from a verified checkpoint, opt-out (PRD-HPC-1461 D-76)."""
import importlib
import json
import os
import pathlib
import signal
import sys

import pytest

from kaos_lib import checkpoint, frameworks

FAKES = {
    "ultralytics/__init__.py": "",
    "ultralytics/engine/__init__.py": "",
    "ultralytics/engine/trainer.py": '''
import pathlib
class BaseTrainer:
    def __init__(self, cfg=None, overrides=None, _callbacks=None):
        self.args = dict(overrides or {})
        self.callbacks = {}
        self.epoch = 0
        self.last = pathlib.Path(self.args.get("save_dir", ".")) / "last.pt"
        self.best = pathlib.Path(self.args.get("save_dir", ".")) / "best.pt"
    def add_callback(self, event, fn):
        self.callbacks.setdefault(event, []).append(fn)
    def train(self, epochs):
        for self.epoch in range(self.args.get("start", 0), epochs):
            self.last.write_bytes(b"weights-%d" % self.epoch)
            for fn in self.callbacks.get("on_model_save", []):
                fn(self)
''',
    "pytorch_lightning/__init__.py": "",
    "pytorch_lightning/callbacks/__init__.py": "class Callback:\n    pass\n",
    "pytorch_lightning/trainer/__init__.py": "",
    "pytorch_lightning/trainer/trainer.py": '''
class Trainer:
    is_global_zero = True
    def __init__(self):
        self.callbacks = []; self.current_epoch = 0; self.global_step = 0; self.ckpt_used = "unset"
    def save_checkpoint(self, path):
        open(path, "wb").write(b"lightning-%d" % self.global_step)
    def fit(self, model, train_dataloaders=None, val_dataloaders=None, datamodule=None, ckpt_path=None):
        self.ckpt_used = ckpt_path
        for self.global_step in range(1, 4):
            for cb in self.callbacks:
                cb.on_train_batch_end(self, model, None, None, self.global_step)
''',
    "transformers/__init__.py": "class TrainerCallback:\n    pass\n",
    "transformers/trainer.py": '''
import os
class Control:
    should_save = False
class State:
    global_step = 0; epoch = 0.0; is_world_process_zero = True
class Args:
    output_dir = "out"
class Trainer:
    def __init__(self, output_dir):
        self.args = Args(); self.args.output_dir = output_dir; self.cbs = []; self.resumed = "unset"
    def add_callback(self, cb): self.cbs.append(cb)
    def train(self, resume_from_checkpoint=None):
        self.resumed = resume_from_checkpoint
        state, ctl = State(), Control()
        for step in range(1, 4):
            state.global_step = step
            ctl.should_save = False
            for cb in self.cbs: cb.on_step_end(self.args, state, ctl)
            if ctl.should_save:
                d = os.path.join(self.args.output_dir, "checkpoint-%d" % step)
                os.makedirs(d); open(os.path.join(d, "model.bin"), "wb").write(b"hf-%d" % step)
                for cb in self.cbs: cb.on_save(self.args, state, ctl)
''',
}


class Clock:
    now = 5000.0

    def __call__(self):
        return self.now


@pytest.fixture
def rig(tmp_path, monkeypatch):
    for rel, text in FAKES.items():
        f = tmp_path / "fakes" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    monkeypatch.syspath_prepend(str(tmp_path / "fakes"))
    folder = tmp_path / "ckptdir"
    folder.mkdir()
    monkeypatch.setenv(checkpoint.CHECKPOINT_DIR_ENV, str(folder))
    monkeypatch.delenv(checkpoint.HOOKS_ENV, raising=False)
    monkeypatch.delenv(checkpoint.RESUME_PATH_ENV, raising=False)
    monkeypatch.delenv("MLFLOW_RUN_ID", raising=False)
    clock = Clock()
    monkeypatch.setattr(checkpoint, "_clock", clock)
    checkpoint._state["requested"] = False
    checkpoint._state.pop("polled", None)
    checkpoint._reg = None
    saved_path, saved_patched = list(sys.meta_path), dict(frameworks._patched)
    frameworks._patched.clear()
    yield folder, clock
    sys.meta_path[:] = saved_path
    frameworks._patched.clear()
    frameworks._patched.update(saved_patched)
    checkpoint._state["requested"] = False
    checkpoint._state.pop("polled", None)
    checkpoint._reg = None
    for name in [m for m in sys.modules if m.split(".")[0] in ("ultralytics", "pytorch_lightning", "transformers")]:
        del sys.modules[name]
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def ckpts(folder):
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("ckpt-"))


def seed(folder, name, **files):
    d = folder / name
    d.mkdir()
    for k, v in files.items():
        (d / k.replace("_", ".", 1) if False else d / k).write_bytes(v)
    checkpoint._write_manifest(d, {"epoch": 1}, 0.1, int(name.split("-")[1]))
    return d


# ---------------------------------------------------------------------------------------------- activation

def test_hooks_are_off_without_the_platform_folder_or_with_the_opt_out(rig, monkeypatch):
    folder, _ = rig
    monkeypatch.setenv(checkpoint.HOOKS_ENV, "0")
    assert checkpoint.hooks_enabled() is False and checkpoint.activate() is False
    monkeypatch.delenv(checkpoint.HOOKS_ENV)
    monkeypatch.delenv(checkpoint.CHECKPOINT_DIR_ENV)
    assert checkpoint.hooks_enabled() is False and checkpoint.activate() is False


def test_activation_never_imports_a_framework_the_step_did_not_import(rig):
    assert checkpoint.activate() is True
    for name in ("ultralytics", "pytorch_lightning", "transformers", "torch"):
        assert name not in sys.modules


def test_a_framework_imported_after_activation_is_hooked_and_one_imported_before_is_too(rig):
    folder, clock = rig
    importlib.import_module("transformers.trainer")                 # imported before kaos_lib attaches
    checkpoint.activate()
    assert getattr(sys.modules["transformers.trainer"].Trainer.train, "__wrapped__", None) is not None
    importlib.import_module("ultralytics.engine.trainer")           # imported after
    assert getattr(sys.modules["ultralytics.engine.trainer"].BaseTrainer.__init__, "__wrapped__", None) is not None


def test_sigterm_is_a_stop_request_only_when_something_will_save(rig, monkeypatch):
    checkpoint.activate()
    assert signal.getsignal(signal.SIGTERM) == checkpoint._on_terminate
    kills = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append(sig))
    checkpoint._on_terminate(signal.SIGTERM, None)
    assert kills == [signal.SIGTERM] and not checkpoint.stop_requested(), "nothing registered: the default applies"
    checkpoint.register(save=lambda p: (p / "f").write_text("x"), load=lambda p: None)
    checkpoint._on_terminate(signal.SIGTERM, None)
    assert checkpoint.stop_requested() and kills == [signal.SIGTERM]


def test_a_folder_with_a_checkpoint_counts_as_a_resume(rig):
    folder, _ = rig
    assert checkpoint.is_resume() is False
    seed(folder, "ckpt-000001", **{"state.txt": b"1"})
    assert checkpoint.is_resume() is True and checkpoint.resume_path() == folder


# ---------------------------------------------------------------------------------------------- Ultralytics

def ultra_trainer(tmp_path, **overrides):
    mod = importlib.import_module("ultralytics.engine.trainer")
    return mod.BaseTrainer(overrides=dict({"save_dir": str(tmp_path)}, **overrides))


def due_at_once(monkeypatch):
    monkeypatch.setattr(checkpoint, "DEFAULT_EVERY_SECONDS", 0)      # the first check finds a checkpoint due


def test_ultralytics_saves_last_pt_into_the_folder_periodically(rig, tmp_path, monkeypatch):
    folder, clock = rig
    due_at_once(monkeypatch)
    checkpoint.activate()
    t = ultra_trainer(tmp_path)
    t.train(3)
    assert ckpts(folder), "a periodic checkpoint was written"
    newest = folder / ckpts(folder)[-1]
    assert (newest / "last.pt").read_bytes().startswith(b"weights-")
    assert checkpoint.verify(newest) == (True, "")
    assert json.loads((newest / "kaos-run.json").read_text()) == {"mlflow_run_id": None}


def test_ultralytics_saves_and_ends_with_85_on_a_stop_request(rig, tmp_path):
    folder, _ = rig
    checkpoint.activate()
    t = ultra_trainer(tmp_path)
    os.kill(os.getpid(), signal.SIGUSR1)
    with pytest.raises(SystemExit) as stopped:
        t.train(5)
    assert stopped.value.code == 85
    [name] = ckpts(folder)
    assert (folder / name / "last.pt").read_bytes() == b"weights-0"


def test_ultralytics_resumes_from_the_folder_and_keeps_the_mlflow_run(rig, tmp_path):
    folder, _ = rig
    d = seed(folder, "ckpt-000003", **{"last.pt": b"weights-7", "kaos-run.json": json.dumps({"mlflow_run_id": "run42"}).encode()})
    checkpoint.activate()
    t = ultra_trainer(tmp_path)
    assert t.args["resume"] == str(d / "last.pt")
    assert os.environ["MLFLOW_RUN_ID"] == "run42"


def test_ultralytics_resume_skips_a_corrupt_newest_checkpoint(rig, tmp_path):
    folder, _ = rig
    good = seed(folder, "ckpt-000001", **{"last.pt": b"good"})
    bad = seed(folder, "ckpt-000002", **{"last.pt": b"fine"})
    (bad / "last.pt").write_bytes(b"torn")
    checkpoint.activate()
    assert ultra_trainer(tmp_path).args["resume"] == str(good / "last.pt")


def test_ultralytics_leaves_a_resume_the_caller_chose_and_an_empty_folder_alone(rig, tmp_path):
    folder, _ = rig
    checkpoint.activate()
    assert "resume" not in ultra_trainer(tmp_path).args
    seed(folder, "ckpt-000001", **{"last.pt": b"w"})
    assert ultra_trainer(tmp_path, resume="mine.pt").args["resume"] == "mine.pt"


def test_a_step_that_registered_its_own_save_is_not_hooked_twice(rig, tmp_path):
    folder, clock = rig
    checkpoint.activate()
    mine = []
    checkpoint.register(save=lambda p: mine.append(1) or (p / "f").write_text("x"), load=lambda p: None)
    ultra_trainer(tmp_path).train(2)
    assert checkpoint._reg.framework is False


# ---------------------------------------------------------------------------------------------- Lightning

def test_lightning_resumes_and_saves_through_a_callback(rig, monkeypatch):
    folder, clock = rig
    due_at_once(monkeypatch)
    d = seed(folder, "ckpt-000002", **{"last.ckpt": b"old"})
    checkpoint.activate()
    mod = importlib.import_module("pytorch_lightning.trainer.trainer")
    t = mod.Trainer()
    t.fit(object())
    assert t.ckpt_used == str(d / "last.ckpt")
    assert len(t.callbacks) == 1
    newest = folder / ckpts(folder)[-1]
    assert newest.name == "ckpt-000003" and (newest / "last.ckpt").read_bytes().startswith(b"lightning-")


def test_lightning_ends_with_85_on_a_stop_request_and_keeps_an_explicit_ckpt_path(rig):
    folder, _ = rig
    seed(folder, "ckpt-000001", **{"last.ckpt": b"old"})
    checkpoint.activate()
    mod = importlib.import_module("pytorch_lightning.trainer.trainer")
    t = mod.Trainer()
    os.kill(os.getpid(), signal.SIGUSR1)
    with pytest.raises(SystemExit) as stopped:
        t.fit(object(), ckpt_path="mine.ckpt")
    assert stopped.value.code == 85 and t.ckpt_used == "mine.ckpt"


# ---------------------------------------------------------------------------------------------- Hugging Face

def test_huggingface_copies_the_trainers_checkpoint_when_due_and_resumes_from_the_folder(rig, tmp_path, monkeypatch):
    folder, clock = rig
    due_at_once(monkeypatch)
    checkpoint.activate()
    mod = importlib.import_module("transformers.trainer")
    t = mod.Trainer(str(tmp_path / "out"))
    t.train()
    assert t.resumed is None
    newest = folder / ckpts(folder)[-1]
    assert (newest / "hf-checkpoint" / "model.bin").read_bytes() == b"hf-1"
    # A continuation: the folder holds the copy, the Trainer resumes from it.
    checkpoint._reg = None
    t2 = mod.Trainer(str(tmp_path / "out2"))
    t2.train()
    assert t2.resumed == str(newest / "hf-checkpoint")


def test_huggingface_saves_then_ends_with_85_on_a_stop_request(rig, tmp_path):
    folder, _ = rig
    checkpoint.activate()
    mod = importlib.import_module("transformers.trainer")
    t = mod.Trainer(str(tmp_path / "out"))
    os.kill(os.getpid(), signal.SIGUSR1)
    with pytest.raises(SystemExit) as stopped:
        t.train()
    assert stopped.value.code == 85
    assert (folder / ckpts(folder)[-1] / "hf-checkpoint" / "model.bin").exists()


def test_an_unknown_framework_version_is_left_alone(rig, capsys):
    checkpoint.activate()
    mod = importlib.import_module("transformers.trainer")          # imported after: hooks attach
    frameworks._patched.clear()
    del mod.Trainer
    frameworks._apply("transformers.trainer", mod)                 # no Trainer: warns, never raises
    assert "checkpoint hooks not attached" in capsys.readouterr().err


def test_ultralytics_saves_best_pt_with_last_pt_when_it_exists(rig, tmp_path):
    folder, _ = rig
    checkpoint.activate()
    t = ultra_trainer(tmp_path)
    t.best.write_bytes(b"best-weights")
    os.kill(os.getpid(), signal.SIGUSR1)
    with pytest.raises(SystemExit):
        t.train(5)
    [name] = ckpts(folder)
    assert (folder / name / "best.pt").read_bytes() == b"best-weights"
    assert checkpoint.verify(folder / name) == (True, "")


def test_ultralytics_saves_no_best_pt_before_one_exists(rig, tmp_path):
    folder, _ = rig
    checkpoint.activate()
    t = ultra_trainer(tmp_path)
    os.kill(os.getpid(), signal.SIGUSR1)
    with pytest.raises(SystemExit):
        t.train(5)
    [name] = ckpts(folder)
    assert not (folder / name / "best.pt").exists()


def test_ultralytics_restores_best_pt_on_a_continuation_that_starts_on_an_empty_run_dir(rig, tmp_path):
    """Ultralytics only writes best.pt when an epoch beats the fitness it restored from last.pt: a run that peaked
    before the interruption (and a new job has an empty run dir) must get its best.pt back (PRD-HPC-1461 AC-13)."""
    folder, _ = rig
    seed(folder, "ckpt-000003", **{"last.pt": b"weights-7", "best.pt": b"best-4"})
    checkpoint.activate()
    t = ultra_trainer(tmp_path)
    assert t.best.read_bytes() == b"best-4"


def test_ultralytics_restore_does_not_overwrite_a_best_pt_already_in_the_run_dir(rig, tmp_path):
    folder, _ = rig
    seed(folder, "ckpt-000003", **{"last.pt": b"weights-7", "best.pt": b"best-4"})
    (tmp_path / "best.pt").write_bytes(b"newer")
    checkpoint.activate()
    assert ultra_trainer(tmp_path).best.read_bytes() == b"newer"


def test_ultralytics_restore_does_nothing_when_the_folder_has_last_pt_only(rig, tmp_path):
    folder, _ = rig
    seed(folder, "ckpt-000003", **{"last.pt": b"weights-7"})
    checkpoint.activate()
    assert not ultra_trainer(tmp_path).best.exists()
