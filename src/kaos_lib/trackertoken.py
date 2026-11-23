"""The experiment tracker's bearer, kept fresh from a file.

When ``MLFLOW_TRACKING_TOKEN_FILE`` names a readable file, its content is the bearer. ``refresh()`` reads it and
sets ``MLFLOW_TRACKING_TOKEN`` to it, so the library's own calls and code that uses the ``mlflow`` client directly
(which reads that variable at every request) send the current one. The library calls ``refresh()`` before each call
of its own, and a daemon thread calls it every minute while a step runs. A file that is missing, unreadable or empty
leaves the last good value in place. Without the file variable nothing here does anything.

Python standard library only.
"""
from __future__ import annotations

import os
import threading

TOKEN_ENV = "MLFLOW_TRACKING_TOKEN"
FILE_ENV = "MLFLOW_TRACKING_TOKEN_FILE"
EVERY_SECONDS = 60
THREAD_NAME = "kaos-tracker-token"

_stop = threading.Event()
_thread = None


def refresh() -> None:
    """Set ``MLFLOW_TRACKING_TOKEN`` to the content of the file ``MLFLOW_TRACKING_TOKEN_FILE`` names, when it holds one."""
    path = os.environ.get(FILE_ENV)
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as handle:
            found = handle.read().strip()
    except (OSError, ValueError):       # not there, not readable, not text: the last good value stays
        return
    if found:
        os.environ[TOKEN_ENV] = found


def _keep_fresh(stop: threading.Event) -> None:
    while not stop.wait(EVERY_SECONDS):
        refresh()


def watch() -> bool:
    """Start the refresher thread once, when the file variable is set. True when this call started it."""
    global _thread
    if not os.environ.get(FILE_ENV) or (_thread is not None and _thread.is_alive()):
        return False
    refresh()
    _stop.clear()
    _thread = threading.Thread(target=_keep_fresh, args=(_stop,), name=THREAD_NAME, daemon=True)
    _thread.start()
    return True


def unwatch() -> None:
    """Stop the refresher thread."""
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    _thread = None
