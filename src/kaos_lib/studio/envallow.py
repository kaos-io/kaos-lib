"""The environment of a local run: an allowlist, never a copy (PRD-CONSOLE-1682 CON-16, AC-35).

Why: the platform injects endpoints, tokens and secret mounts into a running step; a laptop must hold none of them,
and a local run must not forward whatever the user's shell happens to export (an `MLFLOW_TRACKING_TOKEN`, AWS keys).
Only what is needed to start a program and reach the package index passes; everything else is dropped.
"""
from __future__ import annotations

import ast
import pathlib
import re

from .constants import ENV_ALLOW, ENV_ALLOW_PREFIXES, PLATFORM_ENV


def allowed(environ: dict) -> dict:
    """The variables of `environ` a local run may inherit."""
    return {k: v for k, v in environ.items() if k in ENV_ALLOW or k.startswith(ENV_ALLOW_PREFIXES)}


def _constants(path: pathlib.Path) -> set:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return set()
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def platform_services_read(step_dir: pathlib.Path, max_files: int = 300) -> list:
    """The platform-only environment variables the step's code names (read statically; the step is not run)."""
    found = set()
    for n, path in enumerate(sorted((step_dir / "app").rglob("*.py")) if (step_dir / "app").is_dir() else []):
        if n >= max_files:
            break
        found |= {c for c in _constants(path) if c in PLATFORM_ENV}
    return sorted(found)


_SECRET_NAME = re.compile(r"(TOKEN|SECRET|PASSWORD|KEY)", re.I)


def leaked(environ: dict) -> list:
    """Names in a run environment that look like platform-injected values: used by the tests to assert there are none."""
    return sorted(k for k in environ if k in PLATFORM_ENV or (_SECRET_NAME.search(k) and k not in ENV_ALLOW))
