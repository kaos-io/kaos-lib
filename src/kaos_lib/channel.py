"""Which release channel this kaos-lib is, and the recommended spec (``kaosctl upgrade``).

kaos-lib is published by the platform's CI to two PUBLIC Python repositories (Artifact Registry), not PyPI:

- prerelease ``X.Y.ZrcN`` in ``kaos-lib-rc``: every merge to ``main``;
- stable ``X.Y.Z`` in ``kaos-lib``: only what the platform's release train promoted from an rc that passed.

The channel follows from the version (PEP 440: an rc is a pre-release). Each channel's newest release metadata is
public at ``<RELEASES_BASE>/<rc|stable>/release.json`` (support window, ``recommended`` spec, channel).

Each platform's lakeFS also publishes ``kaos_lib_support`` at ``/kaos/v1/ui``; its ``recommended`` key is the pip
spec that platform wants (``==X.Y.Z``, ``@ <url>``, or a whole ``kaos-lib[...] @ <url>`` requirement). The
platform's word wins; the public channel metadata is the fallback.
"""
from __future__ import annotations

import json
import os
import re
import sys
from importlib import metadata
from typing import Optional

import requests
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from .errors import ConfigError

DIST = "kaos-lib"
RELEASES_BASE = "https://storage.googleapis.com/kaos-dev-511509-kaos-lib"
INDEXES = {"prerelease": "https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib-rc/simple/",
           "stable": "https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/"}
PREFIX = {"prerelease": "rc", "stable": "stable"}
_COMMIT_IN_URL = re.compile(r"/archive/([0-9a-f]{7,40})\.(?:zip|tar\.gz)$")
_WHEEL_VERSION = re.compile(r"/kaos_lib-([^-/]+)-py3-none-any\.whl$")
TIMEOUT = 10


def tag_of(version: str) -> Optional[str]:
    """``0.3.0`` -> ``v0.3.0``; ``0.3.0rc2`` -> ``v0.3.0-rc.2``; None for anything else."""
    try:
        v = Version(version)
    except InvalidVersion:
        return None
    if v.dev is not None or v.post is not None or v.local:
        return None
    base = ".".join(map(str, v.release))
    if v.pre is None:
        return f"v{base}"
    return f"v{base}-rc.{v.pre[1]}" if v.pre[0] == "rc" else None


def channel_of_version(version: str) -> str:
    """prerelease for X.Y.ZrcN, stable for X.Y.Z, unknown otherwise."""
    tag = tag_of(version)
    return "unknown" if tag is None else "prerelease" if "-rc." in tag else "stable"


def channel_of(version: str, direct_url: Optional[dict] = None) -> dict:
    """``{channel, tag, url}``: local (editable or a file) and commit (a source archive) from the PEP 610 record,
    else the version's channel (prerelease | stable | unknown)."""
    url = str((direct_url or {}).get("url") or "") or None
    if direct_url and ((direct_url.get("dir_info") or {}).get("editable") or (url or "").startswith("file:")):
        return {"channel": "local", "tag": None, "url": url}
    found = _COMMIT_IN_URL.search(url or "")
    if found:
        return {"channel": "commit", "tag": found.group(1)[:12], "url": url}
    return {"channel": channel_of_version(version), "tag": tag_of(version), "url": url}


def installed(version: str) -> dict:
    """``channel_of`` for the installed distribution (``version`` is this kaos-lib's)."""
    try:
        raw = metadata.distribution(DIST).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return {"channel": "local", "tag": None, "url": None}      # a source tree on sys.path
    try:
        return channel_of(version, json.loads(raw) if raw else None)
    except ValueError:
        return channel_of(version)


def describe(info: dict) -> str:
    """``prerelease v0.3.0-rc.2`` / ``stable v0.3.0`` / ``commit 1a2b3c4d5e6f`` / ``local install`` ..."""
    if info["channel"] == "local":
        return "local install"
    return f"{info['channel']} {info['tag']}" if info.get("tag") else info["channel"]


def public_release(channel: str) -> Optional[dict]:
    """The channel's newest release.json from the public bucket, or None (offline, not published yet)."""
    if channel not in PREFIX:
        return None
    base = os.environ.get("KAOS_LIB_RELEASES_BASE") or RELEASES_BASE
    try:
        resp = requests.get(f"{base.rstrip('/')}/{PREFIX[channel]}/release.json", timeout=TIMEOUT,
                            headers={"Cache-Control": "no-cache"})
        body = resp.json() if resp.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None
    return body if isinstance(body, dict) else None


def recommended(support_value) -> Optional[str]:
    """The ``recommended`` spec inside a ``kaos_lib_support`` / release.json (dict or JSON string), or None."""
    if isinstance(support_value, str):
        try:
            support_value = json.loads(support_value)
        except ValueError:
            return None
    value = support_value.get("recommended") if isinstance(support_value, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def has_zitadel_extra() -> bool:
    try:
        import cryptography  # noqa: F401
        import jwt  # noqa: F401
    except ImportError:
        return False
    return True


def requirement(spec: str, zitadel: bool) -> Requirement:
    """The pip requirement for a recommended spec; refuses anything that is not kaos-lib from an https URL or ==."""
    whole = bool(re.match(r"[A-Za-z0-9]", spec))          # a whole requirement names its package first
    text = spec if whole else DIST + ("[zitadel]" if zitadel else "") + " " + spec
    try:
        req = Requirement(text)
    except InvalidRequirement as exc:
        raise ConfigError(f"the platform's recommended kaos-lib spec {spec!r} is not a pip requirement ({exc})") from None
    if canonicalize_name(req.name) != DIST:
        raise ConfigError(f"the platform recommends {req.name!r}, not kaos-lib: refusing to install it")
    if req.url and not req.url.startswith("https://"):
        raise ConfigError(f"the platform's recommended kaos-lib URL is not https ({req.url}): refusing it")
    if zitadel and "zitadel" not in req.extras:
        req.extras.add("zitadel")                          # keep what this install already has
    return req


def _strip(url: Optional[str]) -> str:
    return (url or "").split("#", 1)[0]


def is_current(req: Requirement, info: dict, version: str) -> bool:
    """Is the installed kaos-lib already what ``req`` asks for?"""
    if req.url:
        if info.get("url") and _strip(info["url"]) == _strip(req.url):
            return True
        found = _WHEEL_VERSION.search(_strip(req.url))     # a registry wheel names its version
        return bool(found) and found.group(1) == version and info.get("channel") in ("prerelease", "stable")
    return bool(req.specifier) and req.specifier.contains(version, prereleases=True) and \
        all(s.operator in ("==", "===") for s in req.specifier)


def pip_command(req: Requirement) -> list:
    return [sys.executable, "-m", "pip", "install", "--upgrade", str(req)]
