"""Checkpoint and continue before an HPC (Slurm) wall time.

A step declared resumable in ``pipeline.py`` (``step(..., resumable=True)``, or ``resumable="20m"`` for an earlier
signal) gets a stop signal shortly before its wall time. Importing this module installs a handler that only records
the request; your code decides when it is safe to save::

    from kaos_lib import checkpoint

    state = load_state(checkpoint.resume_path()) if checkpoint.is_resume() else fresh_state()
    for epoch in range(state.epoch, epochs):
        train_one_epoch(state)
        if checkpoint.stop_requested():             # a safe point: the end of an epoch or a batch
            checkpoint.save(lambda path: save_state(state, path))   # writes, then ends the step

``save`` calls your function with an empty folder, moves what it wrote into the step's output folder as
``checkpoint/`` in one step (a half-written checkpoint is never left behind), and ends the step with exit code 85.
The platform uploads the checkpoint with the step's other outputs and continues the step in a new job, where
``is_resume()`` is true and ``resume_path()`` is the folder holding it.

Where no stop signal arrives and no checkpoint is handed over (for example on your project's own machines), nothing
happens: ``stop_requested()`` and ``is_resume()`` stay false, so the same step code runs everywhere. If a step does
not save in time, its wall time ends it as before.

Python standard library only; no framework code.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import signal
import sys
import tempfile
import threading
from typing import Callable, Optional

STOP_SIGNAL = signal.SIGUSR1
CONTINUE_EXIT_CODE = 85            # "saved, continue me"
OUTPUT_DIR_ENV = "KAOS_OUTPUT_DIR"
RESUME_PATH_ENV = "KAOS_RESUME_PATH"
DEFAULT_OUTPUT_DIR = "/work/output"
CHECKPOINT_DIR = "checkpoint"

_state = {"requested": False}


def _on_stop_signal(signum, frame) -> None:
    # Only record it: saving belongs at a safe point in the step's own code, not in the middle of a batch.
    _state["requested"] = True


def _install() -> None:
    if threading.current_thread() is threading.main_thread():
        signal.signal(STOP_SIGNAL, _on_stop_signal)


_install()


def stop_requested() -> bool:
    """True once the platform asked the step to stop before its wall time."""
    return _state["requested"]


def resume_path() -> Optional[pathlib.Path]:
    """The folder holding the checkpoint this step continues from, or None on a first run."""
    path = os.environ.get(RESUME_PATH_ENV)
    if path and pathlib.Path(path).is_dir():
        return pathlib.Path(path)
    return None


def is_resume() -> bool:
    """True when this step continues from a checkpoint."""
    return resume_path() is not None


def output_dir() -> pathlib.Path:
    """The step's output folder, which the platform uploads when the step ends."""
    return pathlib.Path(os.environ.get(OUTPUT_DIR_ENV) or DEFAULT_OUTPUT_DIR)


def save(save_fn: Callable[[pathlib.Path], object]) -> bool:
    """Save the checkpoint and end the step, if a stop was requested; otherwise do nothing and return False.

    ``save_fn(path)`` writes the checkpoint into ``path``, an empty folder. What it wrote replaces
    ``<output folder>/checkpoint`` in one rename, then the step exits with ``CONTINUE_EXIT_CODE``. If ``save_fn``
    raises or writes nothing, no checkpoint is left and the error propagates.
    """
    if not stop_requested():
        return False
    out = output_dir()
    out.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=".checkpoint-", dir=out))
    try:
        save_fn(tmp)
        if not any(tmp.iterdir()):
            raise RuntimeError("the save function wrote nothing into " + str(tmp))
        _sync(tmp)
        final = out / CHECKPOINT_DIR
        old = None
        if final.exists():                      # a directory cannot be renamed over a non-empty one
            old = out / f".checkpoint-old-{os.getpid()}"
            os.replace(final, old)
        os.replace(tmp, final)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    print(f"kaos-lib: checkpoint saved to {final}; ending the step with exit code {CONTINUE_EXIT_CODE} "
          "so it continues in a new job", file=sys.stderr, flush=True)
    sys.stdout.flush()
    raise SystemExit(CONTINUE_EXIT_CODE)


def _sync(folder: pathlib.Path) -> None:
    """Flush every file of the checkpoint to disk before it is published."""
    for path in folder.rglob("*"):
        if path.is_file():
            with open(path, "rb") as fh:
                os.fsync(fh.fileno())
