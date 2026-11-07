"""Checkpoints for long runs: save regularly, verify on load, continue after any interruption.

Register how your step saves and loads its state once, after the model is built, and call ``tick()`` at the safe
points of your loop (the end of a batch or an epoch)::

    from kaos_lib import checkpoint

    model = build_model()
    checkpoint.register(save=lambda path: save_state(model, path),    # writes into the folder it is given, and
                        load=lambda path: load_state(model, path))    # returns the progress: an int or a dict
    for epoch in range(first_epoch, epochs):
        train_one_epoch(model)
        checkpoint.tick()

``save(path)`` writes everything needed to continue into the empty folder ``path`` and returns the progress it
reached: an int (``epoch``) or a dict (``{"epoch": 3, "step": 1200}``, most significant counter first). ``load(path)``
restores from such a folder. ``checkpoint(save=..., load=...)`` is the same call as ``checkpoint.register(...)``.

What the library does with them:

* **Resume.** If the platform continues the step from an earlier checkpoint, ``register`` loads the newest
  checkpoint that verifies and returns its progress (None on a first run).
* **The checkpoint folder.** The platform gives every step a folder, ``checkpoint.checkpoint_dir()``
  (``$KAOS_CHECKPOINT_DIR``), saves it every few minutes and before the wall time, and restores its newest verified
  copy there when the step continues. Registered saves are written into it; a step that never calls this library
  can simply point its framework at the folder.
* **Periodic checkpoints.** ``tick()`` saves every N minutes. N follows the measured save time so saving stays near
  10 % of the run time (never less than 5 or more than 60 minutes); ``checkpoint_every=`` sets minutes yourself and
  ``checkpoint_every=False`` turns periodic saving off.
* **Stop signal.** When the platform asks the step to stop before its wall time, the next ``tick()`` saves and ends
  the step with exit code 85 so it continues in a new job.
* **Safe writes.** A checkpoint is written to a temporary folder, listed in a manifest (sha256 and size of every
  file, progress, time) and only then moved into place. Loading skips a checkpoint whose files do not match its
  manifest and takes the previous one. The last two checkpoints are kept.

The older calls still work: ``stop_requested()``, ``save(save_fn)`` (saves and ends the step if a stop was
requested), ``is_resume()`` and ``resume_path()``.

Where no stop signal arrives and nothing is handed over (for example on your project's own machines), ``tick()``
still writes periodic checkpoints into the output folder; the same code runs everywhere.

Python standard library only; no framework code.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import signal
import sys
import tempfile
import threading
import time
import types
from typing import Any, Callable, List, Optional, Tuple

STOP_SIGNAL = signal.SIGUSR1
CONTINUE_EXIT_CODE = 85            # "saved, continue me"
OUTPUT_DIR_ENV = "KAOS_OUTPUT_DIR"
RESUME_PATH_ENV = "KAOS_RESUME_PATH"
CHECKPOINT_DIR_ENV = "KAOS_CHECKPOINT_DIR"  # the folder the platform keeps safe and restores on a continuation
HOOKS_ENV = "KAOS_CHECKPOINT_HOOKS"        # set to 0 to turn the automatic framework hooks off
DEFAULT_OUTPUT_DIR = "/work/output"
CHECKPOINT_DIR = "checkpoint"
MANIFEST_NAME = "manifest.json"
VERSION_PREFIX = "ckpt-"
KEEP_CHECKPOINTS = 2               # the newest one and the one before it
DEFAULT_EVERY_SECONDS = 15 * 60    # until a save has been measured
MIN_EVERY_SECONDS = 5 * 60
MAX_EVERY_SECONDS = 60 * 60
SAVE_OVERHEAD = 0.10               # saving should take about this share of the run time

_state = {"requested": False}
_clock: Callable[[], float] = time.monotonic     # replaced in tests


def _on_stop_signal(signum, frame) -> None:
    # Only record it: saving belongs at a safe point in the step's own code, not in the middle of a batch.
    _state["requested"] = True


def _install() -> None:
    if threading.current_thread() is threading.main_thread():
        signal.signal(STOP_SIGNAL, _on_stop_signal)


_install()


def hooks_enabled() -> bool:
    """True when the platform set ``KAOS_CHECKPOINT_DIR`` and ``KAOS_CHECKPOINT_HOOKS`` is not 0/false/off."""
    if not os.environ.get(CHECKPOINT_DIR_ENV):
        return False
    return os.environ.get(HOOKS_ENV, "1").strip().lower() not in ("0", "false", "off", "no")


def _on_terminate(signum, frame) -> None:
    """SIGTERM (a node being drained, a spot node reclaimed, a pod evicted): record it as a stop request when
    something is going to save at a safe point; otherwise behave exactly as without the library."""
    if _reg is None:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTERM)
        return
    _state["requested"] = True


def activate() -> bool:
    """Called when ``kaos_lib`` is imported. Where the platform set ``KAOS_CHECKPOINT_DIR`` (and hooks are not
    turned off) it makes SIGTERM a stop request too and attaches the framework hooks (see ``kaos_lib.frameworks``);
    those touch a framework only if the step imports it. Returns whether it activated. Never raises."""
    if not hooks_enabled():
        return False
    try:
        if threading.current_thread() is threading.main_thread() and \
                signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None):
            signal.signal(signal.SIGTERM, _on_terminate)
        from . import frameworks
        frameworks.install()
    except Exception as exc:                    # the hooks must never break an import
        print("kaos-lib: checkpoint hooks not attached: %s" % exc, file=sys.stderr, flush=True)
        return False
    return True


def stop_requested() -> bool:
    """True once the platform asked the step to stop before its wall time."""
    return _state["requested"]


def resume_path() -> Optional[pathlib.Path]:
    """The folder holding the checkpoint(s) this step continues from, or None on a first run."""
    path = os.environ.get(RESUME_PATH_ENV)
    if path and pathlib.Path(path).is_dir():
        return pathlib.Path(path)
    folder = os.environ.get(CHECKPOINT_DIR_ENV)
    if folder and pathlib.Path(folder).is_dir() and candidates(pathlib.Path(folder)):
        return pathlib.Path(folder)          # the platform restored an earlier copy into the folder
    return None


def is_resume() -> bool:
    """True when this step continues from a checkpoint."""
    return resume_path() is not None


def output_dir() -> pathlib.Path:
    """The step's output folder, which the platform uploads when the step ends."""
    return pathlib.Path(os.environ.get(OUTPUT_DIR_ENV) or DEFAULT_OUTPUT_DIR)


def checkpoint_dir() -> pathlib.Path:
    """The folder checkpoints are kept in: ``$KAOS_CHECKPOINT_DIR`` where the platform sets it (it saves this folder
    every few minutes and restores it when the step continues), else ``<output folder>/checkpoint``."""
    env = os.environ.get(CHECKPOINT_DIR_ENV)
    return pathlib.Path(env) if env else output_dir() / CHECKPOINT_DIR


# ---------------------------------------------------------------------------------------------- progress

def progress_values(progress: Any) -> List[int]:
    """The numbers a progress value is compared by: an int is itself, a dict gives its numeric values in key order
    (most significant counter first), None gives nothing."""
    if progress is None:
        return []
    if isinstance(progress, bool):
        raise TypeError("progress must be an int or a dict of numbers, not a bool")
    if isinstance(progress, (int, float)):
        return [int(progress)]
    if isinstance(progress, dict):
        out = []
        for key, value in progress.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("progress[%r] must be a number, got %s" % (key, type(value).__name__))
            out.append(int(value))
        return out
    raise TypeError("progress must be an int or a dict of numbers, got %s" % type(progress).__name__)


def progress_text(progress: Any) -> str:
    """A short readable form of a progress value: ``epoch=3 step=1200`` or ``7``."""
    if isinstance(progress, dict):
        return " ".join("%s=%s" % (k, v) for k, v in progress.items())
    return "" if progress is None else str(progress)


# ---------------------------------------------------------------------------------------------- manifest

def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: pathlib.Path) -> None:
    with open(path, "rb") as fh:
        os.fsync(fh.fileno())


def _sync(folder: pathlib.Path) -> None:
    """Flush every file of the checkpoint to disk before it is published."""
    for path in folder.rglob("*"):
        if path.is_file():
            _fsync_file(path)


def _write_manifest(folder: pathlib.Path, progress: Any, save_seconds: float, seq: int) -> None:
    files = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not (path.parent == folder and path.name == MANIFEST_NAME):
            files[path.relative_to(folder).as_posix()] = {"sha256": _sha256(path), "size": path.stat().st_size}
    manifest = {"version": 1, "seq": seq, "time": time.time(), "progress": progress,
                "progress_values": progress_values(progress), "progress_text": progress_text(progress),
                "save_seconds": round(save_seconds, 3), "bytes": sum(f["size"] for f in files.values()),
                "files": files}
    target = folder / MANIFEST_NAME
    target.write_text(json.dumps(manifest, sort_keys=True))
    _fsync_file(target)


def read_manifest(folder: pathlib.Path) -> Optional[dict]:
    """The manifest of a checkpoint folder, or None when it has none or it is unreadable."""
    try:
        data = json.loads((folder / MANIFEST_NAME).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None


def verify(folder: pathlib.Path) -> Tuple[bool, str]:
    """(True, "") when every file listed in the folder's manifest exists with the recorded size and sha256."""
    manifest = read_manifest(folder)
    if manifest is None:
        return False, "no readable manifest"
    if not manifest["files"]:
        return False, "the manifest lists no files"
    for name, meta in manifest["files"].items():
        path = folder / name
        try:
            if not path.is_file() or path.stat().st_size != meta["size"]:
                return False, "%s is missing or has another size" % name
            if _sha256(path) != meta["sha256"]:
                return False, "%s does not match its checksum" % name
        except (OSError, KeyError, TypeError) as exc:
            return False, "%s cannot be checked: %s" % (name, exc)
    return True, ""


def candidates(root: pathlib.Path) -> List[pathlib.Path]:
    """The checkpoints under ``root``, newest first: its ``ckpt-*`` subfolders, then ``root`` itself when it holds a
    checkpoint directly (the layout of ``save(save_fn)`` and of earlier library versions)."""
    if not root.is_dir():
        return []
    found = sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(VERSION_PREFIX)),
                   key=lambda p: p.name, reverse=True)
    if (root / MANIFEST_NAME).exists() or (not found and any(not p.name.startswith(".") for p in root.iterdir())):
        found.append(root)
    return found


def loadable(root: pathlib.Path) -> List[pathlib.Path]:
    """The checkpoints under ``root`` that may be loaded, newest first: those whose manifest verifies, and a lone
    checkpoint without a manifest (written before manifests existed). Others are skipped with a message."""
    found, out = candidates(root), []
    for folder in found:
        ok, why = verify(folder)
        if ok or (read_manifest(folder) is None and folder == root and len(found) == 1):
            out.append(folder)
        else:
            print("kaos-lib: skipping checkpoint %s: %s" % (folder, why), file=sys.stderr, flush=True)
    return out


def newest_valid(root: pathlib.Path) -> Optional[pathlib.Path]:
    """The newest checkpoint under ``root`` that verifies, else the previous good one; None when none does."""
    folders = loadable(root)
    return folders[0] if folders else None


# ---------------------------------------------------------------------------------------------- writing

def _next_seq(root: pathlib.Path) -> int:
    seqs = [int(p.name[len(VERSION_PREFIX):]) for p in root.iterdir()
            if p.is_dir() and p.name.startswith(VERSION_PREFIX) and p.name[len(VERSION_PREFIX):].isdigit()]
    return max(seqs, default=0) + 1


def _prune(root: pathlib.Path) -> None:
    """Keep the newest KEEP_CHECKPOINTS versions; older ones are not needed once a newer one is in place."""
    versions = sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(VERSION_PREFIX)),
                      key=lambda p: p.name, reverse=True)
    for old in versions[KEEP_CHECKPOINTS:]:
        shutil.rmtree(old, ignore_errors=True)


def _call_save(save_fn: Callable[[pathlib.Path], Any], tmp: pathlib.Path) -> Tuple[Any, float]:
    started = _clock()
    progress = save_fn(tmp)
    seconds = _clock() - started
    if not any(tmp.iterdir()):
        raise RuntimeError("the save function wrote nothing into " + str(tmp))
    progress_values(progress)           # reject a progress value that cannot be compared, before publishing
    return progress, seconds


def write_versioned(save_fn: Callable[[pathlib.Path], Any]) -> pathlib.Path:
    """Write one checkpoint as ``<checkpoint folder>/ckpt-<n>``: into a temporary folder, manifest last, one rename.
    Returns its folder; on any error nothing is left behind and the error propagates."""
    root = checkpoint_dir()
    root.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=".tmp-", dir=root))
    try:
        progress, seconds = _call_save(save_fn, tmp)
        _sync(tmp)
        seq = _next_seq(root)
        _write_manifest(tmp, progress, seconds, seq)
        final = root / ("%s%06d" % (VERSION_PREFIX, seq))
        os.replace(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _prune(root)
    return final


def write_flat(save_fn: Callable[[pathlib.Path], Any]) -> pathlib.Path:
    """Write a checkpoint as ``<output>/checkpoint`` itself (what ``save(save_fn)`` always did), now with a manifest."""
    out = output_dir()
    out.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=".checkpoint-", dir=out))
    try:
        progress, seconds = _call_save(save_fn, tmp)
        _sync(tmp)
        _write_manifest(tmp, progress, seconds, 0)
        final = out / CHECKPOINT_DIR
        old = None
        if final.exists():                      # a directory cannot be renamed over a non-empty one
            old = out / (".checkpoint-old-%d" % os.getpid())
            os.replace(final, old)
        os.replace(tmp, final)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def _end_step(final: pathlib.Path) -> None:
    print("kaos-lib: checkpoint saved to %s; ending the step with exit code %d so it continues in a new job"
          % (final, CONTINUE_EXIT_CODE), file=sys.stderr, flush=True)
    sys.stdout.flush()
    raise SystemExit(CONTINUE_EXIT_CODE)


def save(save_fn: Optional[Callable[[pathlib.Path], Any]] = None) -> bool:
    """Save the checkpoint and end the step, if a stop was requested; otherwise do nothing and return False.

    ``save_fn(path)`` writes the checkpoint into ``path``, an empty folder (default: the function given to
    ``register``). What it wrote replaces ``<output folder>/checkpoint`` in one rename, then the step exits with
    ``CONTINUE_EXIT_CODE``. If ``save_fn`` raises or writes nothing, no checkpoint is left and the error propagates.
    """
    if not stop_requested():
        return False
    if save_fn is None:
        if _reg is None:
            raise TypeError("save() needs a save function, or call register(save=..., load=...) first")
        _end_step(_save_registered())
    _end_step(write_flat(save_fn))
    return True


# ---------------------------------------------------------------------------------------------- registration

class _Registration:
    def __init__(self, save_fn, load_fn, every):
        self.save, self.load, self.every = save_fn, load_fn, every
        self.last_save_at = _clock()
        self.save_seconds: List[float] = []
        self.framework = False

    def interval_seconds(self) -> Optional[float]:
        """Seconds between periodic checkpoints: yours, or ten times the slowest save so far, kept in bounds."""
        if self.every is False or self.every == 0:
            return None
        if self.every is not None:
            return float(self.every) * 60
        if not self.save_seconds:
            return DEFAULT_EVERY_SECONDS
        return min(max(max(self.save_seconds) / SAVE_OVERHEAD, MIN_EVERY_SECONDS), MAX_EVERY_SECONDS)


_reg: Optional[_Registration] = None


def attach(save: Callable[[pathlib.Path], Any], every: Any = None) -> Optional[_Registration]:
    """For the framework hooks: arm ``tick()`` with a framework's own save, unless the step registered its own
    save and load (then the step's wins and None is returned)."""
    global _reg
    if _reg is not None and not _reg.framework:
        return None
    _reg = _Registration(save, lambda path: None, every)
    _reg.framework = True
    return _reg


def is_due() -> bool:
    """True when a periodic checkpoint is due (for hooks that save from a framework callback)."""
    if _reg is None:
        return False
    interval = _reg.interval_seconds()
    return interval is not None and _clock() - _reg.last_save_at >= interval


def save_now() -> pathlib.Path:
    """Write a checkpoint with the registered save now; if a stop was requested, end the step (exit 85) after it."""
    if _reg is None:
        raise RuntimeError("checkpoint.save_now() needs checkpoint.register(save=..., load=...) first")
    folder = _save_registered()
    if stop_requested():
        _end_step(folder)
    return folder


def _save_registered() -> pathlib.Path:
    assert _reg is not None
    started = _clock()
    folder = write_versioned(_reg.save)
    _reg.save_seconds.append((read_manifest(folder) or {}).get("save_seconds") or (_clock() - started))
    _reg.last_save_at = _clock()
    return folder


def register(save: Callable[[pathlib.Path], Any], load: Callable[[pathlib.Path], Any],
             checkpoint_every: Any = None) -> Any:
    """Tell the library how your step saves and loads its state; call it once, after the state exists.

    Loads the newest verified checkpoint when this step continues from one and returns its progress (None on a first
    run), and arms ``tick()``. ``checkpoint_every`` is the
    number of minutes between periodic checkpoints, None for the adaptive default, False to turn them off.
    """
    global _reg
    if checkpoint_every not in (None, False) and not (
            isinstance(checkpoint_every, (int, float)) and checkpoint_every >= 0):
        raise ValueError("checkpoint_every must be minutes (a number), None or False")
    _reg = _Registration(save, load, checkpoint_every)
    resumed = _resume(_reg)
    _reg.last_save_at = _clock()
    return resumed


def _resume(reg: _Registration) -> Any:
    """Load the newest checkpoint that verifies and that ``load`` accepts; the progress it recorded, or None."""
    root = resume_path()
    if root is None:
        return None
    last_error: Optional[BaseException] = None
    for folder in loadable(root):
        try:
            reg.load(folder)
        except Exception as exc:                     # a load that fails on this one may accept the previous
            last_error = exc
            print("kaos-lib: loading %s failed (%s); trying the previous checkpoint" % (folder, exc),
                  file=sys.stderr, flush=True)
            continue
        manifest = read_manifest(folder) or {}
        print("kaos-lib: continuing from %s (%s)" % (folder.name, manifest.get("progress_text") or "no progress"),
              file=sys.stderr, flush=True)
        return manifest.get("progress")
    if last_error is not None:
        raise last_error
    raise RuntimeError("this step continues from %s, but no checkpoint there verifies" % root)


def tick() -> bool:
    """Call at a safe point of the loop. On a stop request: save and end the step (exit 85). Otherwise save when a
    periodic checkpoint is due. Returns True if a periodic checkpoint was written. Needs ``register`` first."""
    if _reg is None:
        raise RuntimeError("checkpoint.tick() needs checkpoint.register(save=..., load=...) first")
    if stop_requested():
        _end_step(_save_registered())           # a failing save here propagates: the step ends failed, not continued
    interval = _reg.interval_seconds()
    if interval is None or _clock() - _reg.last_save_at < interval:
        return False
    try:
        _save_registered()
    except Exception as exc:                    # a periodic save must never kill a healthy run
        print("kaos-lib: periodic checkpoint failed: %s" % exc, file=sys.stderr, flush=True)
        _reg.last_save_at = _clock()
        return False
    return True


class _CallableModule(types.ModuleType):
    """Lets ``checkpoint(save=..., load=...)`` mean ``checkpoint.register(save=..., load=...)``."""

    def __call__(self, *args, **kwargs):
        return register(*args, **kwargs)


sys.modules[__name__].__class__ = _CallableModule
