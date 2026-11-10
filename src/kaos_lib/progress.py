"""Progress of a step: how far it is, for the run page.

``report(done, total, unit="epoch")`` prints one line the platform reads from the step's log, on a cluster and on
HPC alike::

    KAOS_PROGRESS {"v":1,"done":34,"total":100,"unit":"epoch","t":1731240000}

Ultralytics, PyTorch Lightning and Hugging Face Trainer report by themselves inside a pipeline run (see
``kaos_lib.frameworks``); call ``report`` for anything else: your own training loop, or a data step
("file 300 of 1200"). ``total`` is optional when it is not known.

It is for display only. A call never fails the step: a value that is not a number is reported once on stderr and
dropped. Lines are limited to one every ``MIN_INTERVAL_S`` seconds; the first, a new unit and the last one
(``done == total``) are always printed. When the step has an active MLflow run, the same values are set as its tags
``kaos.progress.done``, ``kaos.progress.total`` and ``kaos.progress.unit``.
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
from typing import Any, Optional

MARKER = "KAOS_PROGRESS"
VERSION = 1
MIN_INTERVAL_S = 10.0
OFF_ENV = "KAOS_PROGRESS"            # set to 0 to print nothing (the framework hooks then report nothing either)
TAG_PREFIX = "kaos.progress."
UNIT_MAX = 24

_guard = threading.Lock()
_state = {"at": None, "unit": None, "done": None, "warned": False}


def enabled() -> bool:
    return os.environ.get(OFF_ENV, "1").strip().lower() not in ("0", "false", "off", "no")


def reset() -> None:
    """Forget what was reported (tests; a process that runs several trainings in a row)."""
    with _guard:
        _state.update(at=None, unit=None, done=None, warned=False)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def _plain(value: float):
    return int(value) if value == int(value) else round(value, 4)


def _warn_once(message: str) -> None:
    if not _state["warned"]:
        _state["warned"] = True
        print("kaos-lib: progress not reported: %s" % message, file=sys.stderr, flush=True)


def record(done: Any, total: Any = None, unit: str = "step") -> Optional[dict]:
    """The record ``report`` would print, or None when the values cannot be shown (and why, once, on stderr)."""
    d = _number(done)
    if d is None:
        _warn_once("done must be a number that is 0 or more, got %r" % (done,))
        return None
    t = None
    if total is not None:
        t = _number(total)
        if t is None or t == 0:
            _warn_once("total must be a number above 0 (or left out), got %r" % (total,))
            return None
        d = min(d, t)                              # a loop that counts one past the end is still "done"
    unit = "".join(c for c in str(unit or "step").strip().lower() if c.isalnum() or c in "-_")[:UNIT_MAX] or "step"
    out = {"v": VERSION, "done": _plain(d), "unit": unit, "t": int(time.time())}
    if t is not None:
        out["total"] = _plain(t)
    return out


def report(done: Any, total: Any = None, unit: str = "step") -> bool:
    """Tell the platform the step is at ``done`` of ``total`` ``unit``s. Returns whether a line was printed.

    Never raises. Safe to call on every batch: at most one line every ``MIN_INTERVAL_S`` seconds.
    """
    try:
        if not enabled():
            return False
        with _guard:
            rec = record(done, total, unit)
            if rec is None:
                return False
            now = time.monotonic()
            final = "total" in rec and rec["done"] == rec["total"]
            fresh = _state["at"] is None or rec["unit"] != _state["unit"]
            if not (final or fresh) and now - _state["at"] < MIN_INTERVAL_S:
                return False
            if rec["unit"] == _state["unit"] and rec["done"] == _state["done"]:
                return False                       # nothing new to say
            _state.update(at=now, unit=rec["unit"], done=rec["done"])
        print("%s %s" % (MARKER, json.dumps(rec, separators=(",", ":"), sort_keys=True)), flush=True)
        _tag(rec)
        return True
    except Exception as exc:                       # display only: a progress line must never end a training
        try:
            _warn_once(str(exc))
        except Exception:
            pass
        return False


def _tag(rec: dict) -> None:
    """The same values on the step's active MLflow run, when it has one. Nothing is imported or started here."""
    mlflow = sys.modules.get("mlflow")
    try:
        run = mlflow.active_run() if mlflow else None
        if run is None:
            return
        tags = {TAG_PREFIX + k: str(rec[k]) for k in ("done", "total", "unit") if k in rec}
        mlflow.set_tags(tags)
    except Exception:
        pass


def parse(line: str) -> Optional[dict]:
    """The record of a progress line, or None when ``line`` is not one (what a log reader uses)."""
    text = (line or "").strip()
    at = text.find(MARKER + " {")
    if at < 0:
        return None
    try:
        rec = json.loads(text[at + len(MARKER) + 1:])
    except ValueError:
        return None
    if not isinstance(rec, dict) or rec.get("v") != VERSION or _number(rec.get("done")) is None:
        return None
    if "total" in rec and not _number(rec["total"]):
        return None
    return rec
