"""The VS Code interpreter hint of a step folder.

Why: opening a step folder in VS Code should pick the step's virtual environment by itself. The file is merged, never
replaced, and left alone when it cannot be read (VS Code allows comments in it, which a JSON parser refuses).
"""
from __future__ import annotations

import json
import os
import pathlib

from .constants import SETTINGS_DIR, SETTINGS_FILE, VENV_DIR

INTERPRETER_KEY = "python.defaultInterpreterPath"


def interpreter_value() -> str:
    """The workspace-relative interpreter path for this OS (the folder opened in VS Code is the step folder)."""
    tail = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return f"${{workspaceFolder}}/{VENV_DIR}/{tail}"


def write_interpreter_hint(step_dir: pathlib.Path) -> str:
    """Write `.vscode/settings.json` in the step folder. Returns 'written', 'unchanged' or a reason it was left alone."""
    path = step_dir / SETTINGS_DIR / SETTINGS_FILE
    settings = {}
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return f"left {path.relative_to(step_dir)} alone: it is not plain JSON; set {INTERPRETER_KEY} yourself"
        if not isinstance(settings, dict):
            return f"left {path.relative_to(step_dir)} alone: it is not a JSON object"
    if settings.get(INTERPRETER_KEY) == interpreter_value():
        return "unchanged"
    settings[INTERPRETER_KEY] = interpreter_value()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=4) + "\n", encoding="utf-8")
    return "written"
