"""Checkpoints for long runs: one folder, kept safe by the platform, whatever framework you use.

Four ways, simplest first (all work the same on every backend)::

    from kaos_lib import checkpoint

    # 1. Point any framework at the folder; the platform saves it, verifies it and restores it when the step continues.
    YOLO("yolo11n.pt").train(project=str(checkpoint.dir()), name="run", exist_ok=True)

    # 2. Or save and load your own state in a few lines.
    state = checkpoint.load("state", default={"epoch": 0})
    for epoch in range(state["epoch"], epochs):
        train_one_epoch(); checkpoint.save({"epoch": epoch + 1})

    # 3. Stop cleanly when the platform asks (a reclaimed node, a drain, the wall time).
    if checkpoint.stop_requested():
        checkpoint.save({"epoch": epoch + 1}); checkpoint.exit_for_restart()

    # 4. Ultralytics, PyTorch Lightning and Hugging Face are hooked automatically (no code, see kaos_lib.frameworks).

``dir()`` is the platform's ``$KAOS_CHECKPOINT_DIR`` (a fresh temporary folder on your own machine, where nothing is
restored). ``save(obj, name)`` writes bytes, JSON-able data (dict, list, numbers, text) or any picklable object
atomically into it; ``load(name, default)`` reads it back; ``progress(n)`` optionally tells the platform how far you
are (an int, or a dict such as ``{"epoch": 3, "step": 1200}``, most significant counter first) so it can stop a
continuation that gets nowhere. ``stop_requested()`` becomes true on SIGTERM or SIGUSR1.

Python standard library only; no framework code. ``load`` unpickles what ``save`` pickled: only use it on your own folder.

Advanced and older calls, kept working: ``register(save=, load=)`` + ``tick()`` (periodic, versioned, checksum-verified
checkpoints of custom state with progress), ``save(save_fn)`` (save and end the step once a stop was requested),
``is_resume()`` and ``resume_path()``.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import pathlib
import shutil
import signal
import sys
import tempfile
import threading
import time
import types
from typing import Any, Callable, List, Optional, Tuple

from . import runtime

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
    if _reg is None and not _state.get("polled"):        # nobody saves or even looks: as without the library
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
    """True once the platform asked the step to stop (SIGTERM or SIGUSR1: a reclaimed or drained node, the wall
    time of an HPC job). Check it at a safe point, save, then ``exit_for_restart()``."""
    _state["polled"] = True                    # a loop that looks is a loop that will save: SIGTERM is then a request
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
    sys.exit(CONTINUE_EXIT_CODE)


_MISSING = object()
_temp_dir: Optional[pathlib.Path] = None
PROGRESS_FILE = "kaos-progress.json"
_EXTENSIONS = (".json", ".pkl", ".bin")


def dir() -> pathlib.Path:  # noqa: A001 - the documented name
    """The checkpoint folder: ``$KAOS_CHECKPOINT_DIR`` on the platform, else a temporary folder for this process
    (created on first use, so a run on your own machine starts fresh). Point any framework's checkpoint or output
    directory at it; whatever is in it is kept safe and restored when the step continues."""
    global _temp_dir
    env = os.environ.get(CHECKPOINT_DIR_ENV)
    if env:
        path = pathlib.Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path
    if _temp_dir is None or not _temp_dir.is_dir():
        _temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="kaos-checkpoint-"))
    return _temp_dir


def _atomic_write(path: pathlib.Path, data: bytes) -> None:
    """Write ``data`` so that ``path`` is either the old content or the new, never half: temp file, fsync, rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _encode(obj: Any) -> Tuple[str, bytes]:
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return ".bin", bytes(obj)
    try:
        return ".json", json.dumps(obj, sort_keys=True).encode()
    except (TypeError, ValueError):
        return ".pkl", pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)


def _write_state(obj: Any, name: str) -> pathlib.Path:
    if not name or "/" in name or name.startswith("."):
        raise ValueError("name must be a plain file name, got %r" % name)
    ext, data = _encode(obj)
    folder = dir()
    target = folder / (name + ext)
    _atomic_write(target, data)
    for other in _EXTENSIONS:                   # one format per name: a newer save of another kind replaces it
        if other != ext:
            try:
                (folder / (name + other)).unlink()
            except OSError:
                pass
    return target


def save(obj: Any = _MISSING, name: str = "state") -> Any:
    """Save ``obj`` as ``name`` in the checkpoint folder, atomically, and return its path.

    ``obj`` may be bytes, anything JSON can hold (dict, list, numbers, text) or any picklable object. Called with
    a function instead (``save(save_fn)``, the older form) or with nothing (after ``register``), it saves and ends
    the step once a stop was requested, as before."""
    if obj is _MISSING or (callable(obj) and not isinstance(obj, type) and name == "state"):
        return _save_and_end(None if obj is _MISSING else obj)
    return _write_state(obj, name)


def load(name: str = "state", default: Any = None) -> Any:
    """What ``save(obj, name)`` stored in the checkpoint folder (the newest file of that name), else ``default``
    (a first run, or nothing saved yet). A file that cannot be read is skipped with a message, not trusted."""
    folder = dir()
    found = sorted((folder / (name + ext) for ext in _EXTENSIONS if (folder / (name + ext)).is_file()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for path in found:
        try:
            raw = path.read_bytes()
            if path.suffix == ".json":
                return json.loads(raw.decode())
            return pickle.loads(raw) if path.suffix == ".pkl" else raw
        except Exception as exc:
            print("kaos-lib: cannot read %s (%s)" % (path, exc), file=sys.stderr, flush=True)
    return default


def progress(value: Any) -> None:
    """Tell the platform how far the step is (an int, or a dict such as ``{"epoch": 3, "step": 1200}``, most
    significant counter first). Optional: without it, any change in the folder counts as progress."""
    values = progress_values(value)
    if not values:
        raise ValueError("progress needs a number or a dict of numbers")
    body = json.dumps({"values": values, "text": progress_text(value)}).encode()
    _atomic_write(dir() / PROGRESS_FILE, body)


def exit_for_restart() -> None:
    """End the step so it is continued: exit code 85. Call it after ``save`` when ``stop_requested()`` is true."""
    sys.stdout.flush()
    sys.exit(CONTINUE_EXIT_CODE)


def _save_and_end(save_fn: Optional[Callable[[pathlib.Path], Any]]) -> bool:
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
        asked = runtime.checkpoint_every_minutes()      # the run form's `<step>-checkpoint-every`
        if asked:
            return float(asked) * 60
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
