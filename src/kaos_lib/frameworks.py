"""Automatic checkpoint hooks for the frameworks a step may use (Ultralytics, PyTorch Lightning, Hugging Face Trainer).

Where the platform sets ``KAOS_CHECKPOINT_DIR`` (and ``KAOS_CHECKPOINT_HOOKS`` is not 0), importing ``kaos_lib``
attaches these hooks; your code calls nothing. A framework is touched only when your step imports it: nothing here
imports a framework, and kaos-lib depends on none of them. Each hook does two things:

* **Save.** While training, a checkpoint of the framework's own state is copied into the checkpoint folder every few
  minutes (see ``kaos_lib.checkpoint``) and, when the step is asked to stop (SIGTERM or SIGUSR1), at the next safe
  point, after which the step ends so it can continue elsewhere.
* **Resume.** When training starts and the folder holds a checkpoint that verifies, training continues from it
  (same total epochs/steps) instead of starting over. A run you already told to resume is left alone.

Plain PyTorch and anything else: register your own functions with ``kaos_lib.checkpoint.register(save=, load=)``.
"""
from __future__ import annotations

import functools
import importlib
import importlib.abc
import json
import os
import pathlib
import shutil
import sys
from typing import Callable, Dict, Optional

from . import checkpoint

_patched: Dict[str, bool] = {}


def _warn(what: str, exc: BaseException) -> None:
    print("kaos-lib: checkpoint hooks not attached to %s: %s" % (what, exc), file=sys.stderr, flush=True)


def _newest(filename: str) -> Optional[pathlib.Path]:
    """``filename`` inside the newest checkpoint of the folder that verifies, or None."""
    folder = checkpoint.checkpoint_dir()
    if not folder.is_dir():
        return None
    for found in checkpoint.loadable(folder):
        if (found / filename).exists():
            return found / filename
    return None


# ------------------------------------------------------------------------------------------------ Ultralytics

ULTRA_RUN_FILE = "kaos-run.json"


def _patch_ultralytics(module) -> None:
    trainer_cls = module.BaseTrainer
    original = trainer_cls.__init__

    @functools.wraps(original)
    def __init__(self, *args, **kwargs):
        args, kwargs = _ultra_resume(args, kwargs)
        original(self, *args, **kwargs)
        try:
            _ultra_attach(self)
        except Exception as exc:               # a hook problem must never fail the training
            _warn("Ultralytics", exc)

    trainer_cls.__init__ = __init__


def _ultra_resume(args, kwargs):
    """Point the trainer's ``resume`` at the folder's last.pt, unless the caller chose. The overrides dict is
    changed in place: ``YOLO.train`` reads the same dict to decide whether to skip building a fresh model."""
    try:
        if "overrides" in kwargs:
            overrides = kwargs["overrides"]
            if overrides is None:
                overrides = kwargs["overrides"] = {}
        elif len(args) > 1:
            overrides = args[1]
            if overrides is None:
                args = (args[0], {}) + tuple(args[2:])
                overrides = args[1]
        else:
            overrides = kwargs["overrides"] = {}
        if overrides.get("resume"):
            return args, kwargs
        last = _newest("last.pt")
        if last is None:
            return args, kwargs
        overrides["resume"] = str(last)
        run = last.parent / ULTRA_RUN_FILE
        if run.exists():                        # continue the same MLflow run, not a new one
            run_id = json.loads(run.read_text()).get("mlflow_run_id")
            if run_id:
                os.environ.setdefault("MLFLOW_RUN_ID", run_id)
        print("kaos-lib: resuming Ultralytics training from %s" % last, file=sys.stderr, flush=True)
    except Exception as exc:
        _warn("Ultralytics (resume)", exc)
    return args, kwargs


def _mlflow_run_id() -> Optional[str]:
    mlflow = sys.modules.get("mlflow")          # only if the step already uses it
    try:
        run = mlflow.active_run() if mlflow else None
        return run.info.run_id if run else None
    except Exception:
        return None


def _ultra_attach(trainer) -> None:
    def save(path: pathlib.Path):
        shutil.copy2(str(trainer.last), str(path / "last.pt"))
        (path / ULTRA_RUN_FILE).write_text(json.dumps({"mlflow_run_id": _mlflow_run_id()}))
        return {"epoch": int(trainer.epoch) + 1}

    if checkpoint.attach(save) is None:
        return
    # on_model_save fires after the trainer wrote last.pt at the end of an epoch: the safe point.
    trainer.add_callback("on_model_save", lambda t: checkpoint.tick())


# ------------------------------------------------------------------------------------------------ Lightning

def _patch_lightning(module) -> None:
    trainer_cls = module.Trainer
    original = trainer_cls.fit
    top = module.__name__.rsplit(".trainer.trainer", 1)[0]

    @functools.wraps(original)
    def fit(self, model, *args, **kwargs):
        try:
            if kwargs.get("ckpt_path") is None and len(args) < 4:
                last = _newest("last.ckpt")
                if last is not None:
                    kwargs["ckpt_path"] = str(last)
                    print("kaos-lib: resuming Lightning training from %s" % last, file=sys.stderr, flush=True)
            _lightning_attach(self, top)
        except Exception as exc:
            _warn("Lightning", exc)
        return original(self, model, *args, **kwargs)

    trainer_cls.fit = fit


def _lightning_attach(trainer, top: str) -> None:
    if not getattr(trainer, "is_global_zero", True):
        return                                   # one rank writes the checkpoint

    def save(path: pathlib.Path):
        trainer.save_checkpoint(str(path / "last.ckpt"))
        return {"epoch": int(trainer.current_epoch), "step": int(trainer.global_step)}

    if checkpoint.attach(save) is None:
        return
    base = importlib.import_module(top + ".callbacks").Callback

    class KaosCheckpoint(base):                 # defined here so Lightning is imported only if the step imported it
        def on_train_batch_end(self, trainer, pl_module, *a, **k):
            checkpoint.tick()

    trainer.callbacks.append(KaosCheckpoint())


# ------------------------------------------------------------------------------------------------ Hugging Face

def _patch_transformers(module) -> None:
    trainer_cls = module.Trainer
    original = trainer_cls.train

    @functools.wraps(original)
    def train(self, resume_from_checkpoint=None, *args, **kwargs):
        try:
            if resume_from_checkpoint is None:
                found = _newest("hf-checkpoint")
                if found is not None:
                    resume_from_checkpoint = str(found)
                    print("kaos-lib: resuming Hugging Face training from %s" % found, file=sys.stderr, flush=True)
            _hf_attach(self)
        except Exception as exc:
            _warn("Hugging Face Trainer", exc)
        return original(self, resume_from_checkpoint, *args, **kwargs)

    trainer_cls.train = train


def _hf_attach(trainer) -> None:
    holder = {"state": None}

    def latest(output_dir: str) -> pathlib.Path:
        found = [p for p in pathlib.Path(output_dir).glob("checkpoint-*") if p.name.split("-")[-1].isdigit()]
        return max(found, key=lambda p: int(p.name.split("-")[-1]))

    def save(path: pathlib.Path):
        shutil.copytree(str(latest(trainer.args.output_dir)), str(path / "hf-checkpoint"))
        return {"step": int(holder["state"].global_step)}

    if checkpoint.attach(save) is None:
        return
    base = importlib.import_module("transformers").TrainerCallback

    class KaosCheckpoint(base):
        pending = False

        def on_step_end(self, args, state, control, **kwargs):
            if checkpoint.stop_requested() or checkpoint.is_due():
                self.pending, control.should_save = True, True    # have the Trainer write its checkpoint now

        def on_save(self, args, state, control, **kwargs):
            if self.pending and state.is_world_process_zero:
                holder["state"], self.pending = state, False
                checkpoint.save_now()

    trainer.add_callback(KaosCheckpoint())


# ------------------------------------------------------------------------------------------------ import hook

WATCHED: Dict[str, Callable] = {
    "ultralytics.engine.trainer": _patch_ultralytics,
    "pytorch_lightning.trainer.trainer": _patch_lightning,
    "lightning.pytorch.trainer.trainer": _patch_lightning,
    "transformers.trainer": _patch_transformers,
}


def _apply(name: str, module) -> None:
    if _patched.get(name):
        return
    _patched[name] = True
    try:
        WATCHED[name](module)
    except Exception as exc:                    # a framework version we do not know: leave it alone
        _warn(name, exc)


class _Loader(importlib.abc.Loader):
    def __init__(self, inner, name):
        self._inner, self._name = inner, name

    def create_module(self, spec):
        return self._inner.create_module(spec) if hasattr(self._inner, "create_module") else None

    def exec_module(self, module):
        self._inner.exec_module(module)
        _apply(self._name, module)


class _Finder(importlib.abc.MetaPathFinder):
    """Lets the real import happen, then attaches the hook to the module that was just imported."""

    def find_spec(self, fullname, path, target=None):
        if fullname not in WATCHED or _patched.get(fullname):
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None and spec.loader is not None:
                spec.loader = _Loader(spec.loader, fullname)
                return spec
        return None


_finder = _Finder()


def install() -> None:
    """Attach to the frameworks already imported, and to those imported later. Safe to call twice."""
    for name in WATCHED:
        if name in sys.modules:
            _apply(name, sys.modules[name])
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)
