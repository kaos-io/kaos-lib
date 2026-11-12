"""Is this kaos-lib still supported? One check against the newest release's metadata (``release.json``).

``release.json`` ships with every release (packaged as ``kaos_lib/_release.json`` and attached to the GitHub
release ``kaos-io/kaos-lib`` vX.Y.Z)::

    {"version": "0.4.0", "supported": ">=0.3",
     "deprecated": [{"range": "<0.3", "unsupported_after": "YYYY-MM-DD"}],
     "breaking": false, "migration": "<url>"}

``supported`` and ``range`` are PEP 440 specifiers. The NEWEST release's metadata is the policy; the platform
hands it to steps as env ``KAOS_LIB_SUPPORT`` and to people through the project's lakeFS (``/kaos/v1/ui`` key
``kaos_lib_support``).

Verdicts: ``current`` (installed >= newest), ``behind`` (older but supported), ``deprecated`` (outside
``supported`` but inside a deprecated range whose deadline has not passed, or that sets none), ``unsupported``
(outside ``supported`` and past any deadline). Metadata that cannot be read gives ``unknown``: a warning, never
a failure. Nothing here fails before a declared deadline.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import sys
from typing import Optional, Union

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .errors import UnsupportedVersion

CURRENT, BEHIND, DEPRECATED, UNSUPPORTED, UNKNOWN = "current", "behind", "deprecated", "unsupported", "unknown"
ENV = "KAOS_LIB_SUPPORT"
UI_PATH, UI_KEY = "/kaos/v1/ui", "kaos_lib_support"
MLFLOW_TAG = "kaos_lib.support"
PACKAGED = pathlib.Path(__file__).with_name("_release.json")
_REQUIRED = {"version": str, "supported": str, "deprecated": list, "breaking": bool, "migration": str}


def _date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def validate_release(meta) -> list:
    """Problems with a ``release.json`` (empty when valid): every key present and well-formed."""
    if not isinstance(meta, dict):
        return ["release.json must be a JSON object"]
    errors = [f"{key}: required, a {kind.__name__}" for key, kind in _REQUIRED.items()
              if not isinstance(meta.get(key), kind)]
    if isinstance(meta.get("version"), str):
        try:
            Version(meta["version"])
        except InvalidVersion:
            errors.append(f"version: {meta['version']!r} is not a PEP 440 version")
    if isinstance(meta.get("supported"), str):
        try:
            SpecifierSet(meta["supported"])
        except InvalidSpecifier:
            errors.append(f"supported: {meta['supported']!r} is not a PEP 440 specifier")
    for i, entry in enumerate(meta.get("deprecated") if isinstance(meta.get("deprecated"), list) else []):
        if not isinstance(entry, dict) or not isinstance(entry.get("range"), str):
            errors.append(f"deprecated[{i}]: needs a range (PEP 440 specifier)")
            continue
        try:
            SpecifierSet(entry["range"])
        except InvalidSpecifier:
            errors.append(f"deprecated[{i}].range: {entry['range']!r} is not a PEP 440 specifier")
        if "unsupported_after" in entry:
            try:
                _date(entry["unsupported_after"])
            except (TypeError, ValueError):
                errors.append(f"deprecated[{i}].unsupported_after: {entry['unsupported_after']!r} is not YYYY-MM-DD")
    return errors


def _result(verdict: str, message: str, fix: str = "") -> dict:
    return {"verdict": verdict, "message": message, "fix": fix}


def check(installed: str, support_json: Union[str, dict, None], today: Optional[dt.date] = None) -> dict:
    """``{verdict, message, fix}`` for ``installed`` under the newest release's metadata. Never raises."""
    if isinstance(support_json, str):
        try:
            support_json = json.loads(support_json)
        except ValueError:
            return _result(UNKNOWN, f"cannot tell whether kaos-lib {installed} is supported: "
                                    "the support metadata is not valid JSON")
    if not isinstance(support_json, dict):
        return _result(UNKNOWN, f"cannot tell whether kaos-lib {installed} is supported: no support metadata")
    try:
        mine = Version(installed)
        newest = Version(str(support_json["version"]))
        supported = SpecifierSet(str(support_json["supported"]))
        ranges = []
        for entry in support_json.get("deprecated") or []:
            deadline = entry.get("unsupported_after")
            ranges.append((SpecifierSet(str(entry["range"])), _date(deadline) if deadline else None))
    except (KeyError, TypeError, AttributeError, ValueError, InvalidVersion, InvalidSpecifier) as exc:
        return _result(UNKNOWN, f"cannot tell whether kaos-lib {installed} is supported: "
                                f"malformed support metadata ({exc.__class__.__name__}: {exc})")
    migration = str(support_json.get("migration") or "")
    upgrade = f"pip install --upgrade 'kaos-lib>={newest}'" + (f" (migration: {migration})" if migration else "")
    if supported.contains(mine, prereleases=True):
        if mine >= newest:
            return _result(CURRENT, f"kaos-lib {mine} is current")
        return _result(BEHIND, f"kaos-lib {mine} is supported; {newest} is available", upgrade)
    deadlines = [deadline for spec, deadline in ranges if spec.contains(mine, prereleases=True)]
    if deadlines:
        today = today or dt.date.today()
        if None in deadlines:
            return _result(DEPRECATED, f"kaos-lib {mine} is deprecated (no removal date set yet)", upgrade)
        last = max(deadlines)
        if today <= last:
            return _result(DEPRECATED, f"kaos-lib {mine} is deprecated and unsupported after {last}", upgrade)
        return _result(UNSUPPORTED, f"kaos-lib {mine} is unsupported since {last} (supported: {supported})",
                       upgrade)
    return _result(UNSUPPORTED, f"kaos-lib {mine} is unsupported (supported: {supported})", upgrade)


def packaged() -> Optional[dict]:
    """This release's own ``_release.json``, or None if it cannot be read."""
    try:
        return json.loads(PACKAGED.read_text())
    except (OSError, ValueError):
        return None


def from_lakefs(client) -> Union[str, dict, None]:
    """The platform's support metadata from the project lakeFS (``/kaos/v1/ui`` key ``kaos_lib_support``), or None."""
    try:
        resp = client.session.get(client.base_url + UI_PATH, timeout=10, allow_redirects=False)
        value = resp.json().get(UI_KEY) if resp.status_code == 200 else None
        return value if isinstance(value, (str, dict)) else None   # a malformed value is check()'s "unknown"
    except Exception:  # noqa: BLE001 - offline or an older kaos-lake: the caller falls back, never fails
        return None


def _tag_mlflow(verdict: str) -> None:
    """Tag the active MLflow run (or ``$MLFLOW_RUN_ID``); quietly skipped when MLflow is not in use."""
    try:
        mlflow = sys.modules.get("mlflow")
        if mlflow is not None and mlflow.active_run() is not None:
            mlflow.set_tag(MLFLOW_TAG, verdict)
        elif os.environ.get("MLFLOW_RUN_ID"):
            from mlflow.tracking import MlflowClient
            MlflowClient().set_tag(os.environ["MLFLOW_RUN_ID"], MLFLOW_TAG, verdict)
    except Exception:  # noqa: BLE001 - a tag is observability; it never fails a step
        pass


STEP_FIX = ("This step's image must be rebuilt with a newer kaos-lib. If its Dockerfile declares ARG KAOS_LIB_PACKAGE, "
            "the platform installs kaos-lib and rebuilds the image: tell the platform team. If the Dockerfile pins "
            "kaos-lib itself, raise that pin and push.")


def _breaking_fix(raw: str) -> str:
    """What to do when the newest release changed the contract of a step (``breaking``), else ''."""
    try:
        policy = json.loads(raw)
    except ValueError:
        return ""
    if not isinstance(policy, dict) or policy.get("breaking") is not True:
        return ""
    guide = f" Follow the migration guide: {policy['migration']}." if policy.get("migration") else ""
    return (f"The newest kaos-lib ({policy.get('version')}) changed how a step is written, so this app's code has "
            f"to change before it can run on it: rebuilding the image with a newer kaos-lib is not enough.{guide}")


def at_step_start(installed: str, environ=os.environ) -> Optional[dict]:
    """Pipeline steps (``$KAOS_LIB_SUPPORT`` set by the platform): log the verdict, tag MLflow, stop if unsupported."""
    raw = environ.get(ENV)
    if not raw:
        return None
    result = check(installed, raw)
    verdict = result["verdict"]
    # A step's image is built by the platform, with the kaos-lib the platform chose: the person reading this
    # log cannot `pip install` anything. Older but supported says so in one neutral line; only deprecated and
    # unsupported say what has to happen, and who does it.
    line = f"kaos-lib {installed}: {verdict}: {result['message']}"
    if verdict == BEHIND:
        line += ". Nothing to do: a platform update brings the newer version"
    elif verdict in (DEPRECATED, UNSUPPORTED):
        line += ". " + (_breaking_fix(raw) or STEP_FIX)
    print(line, file=sys.stderr)
    _tag_mlflow(verdict)
    if verdict == UNSUPPORTED:
        raise UnsupportedVersion(f"{result['message']}. {_breaking_fix(raw) or STEP_FIX}")
    return result
