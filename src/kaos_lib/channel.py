"""Which release channel this kaos-lib came from, and the platform's recommended spec (``kaos-cli upgrade``).

Releases are GitHub Releases of kaos-io/kaos-lib, in two channels:

- prerelease: ``vX.Y.Z-rc.N``, cut by the platform CI on every merge to ``main``;
- stable: ``vX.Y.Z``, promoted by the platform's release train from an rc that passed (the same wheel bytes).

The channel is read from how pip installed the package (PEP 610 ``direct_url.json``): a release asset or tag
archive URL names its tag. The version alone cannot tell: an rc carries the version it will be promoted as.

Each platform's lakeFS publishes ``kaos_lib_support`` at ``/kaos/v1/ui``; its ``recommended`` key is the pip
spec that platform wants (``==X.Y.Z``, ``@ <url>``, or a whole ``kaos-lib[...] @ <url>`` requirement).
"""
from __future__ import annotations

import json
import re
import sys
from importlib import metadata
from typing import Optional

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from .errors import ConfigError

DIST = "kaos-lib"
RC_TAG = re.compile(r"^v\d+\.\d+\.\d+-rc\.\d+$")
STABLE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
_TAG_IN_URL = (re.compile(r"/releases/download/(v[^/]+)/"),
               re.compile(r"/archive/refs/tags/(v[^/]+?)\.(?:zip|tar\.gz)$"))
_COMMIT_IN_URL = re.compile(r"/archive/([0-9a-f]{7,40})\.(?:zip|tar\.gz)$")


def channel_of_tag(tag: str) -> str:
    return "prerelease" if RC_TAG.match(tag) else "stable" if STABLE_TAG.match(tag) else "unknown"


def channel_of(direct_url: Optional[dict]) -> dict:
    """``{channel, tag, url}`` from a PEP 610 record. channel: prerelease | stable | commit | local | index | unknown."""
    if not direct_url:
        return {"channel": "index", "tag": None, "url": None}      # from a package index, not a URL
    url = str(direct_url.get("url") or "")
    if (direct_url.get("dir_info") or {}).get("editable") or url.startswith("file:"):
        return {"channel": "local", "tag": None, "url": url}
    for pattern in _TAG_IN_URL:
        found = pattern.search(url)
        if found:
            return {"channel": channel_of_tag(found.group(1)), "tag": found.group(1), "url": url}
    found = _COMMIT_IN_URL.search(url)
    if found:
        return {"channel": "commit", "tag": found.group(1)[:12], "url": url}
    return {"channel": "unknown", "tag": None, "url": url}


def installed() -> dict:
    """``channel_of`` for the installed distribution; ``unknown`` when it is not installed (source tree)."""
    try:
        raw = metadata.distribution(DIST).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return {"channel": "unknown", "tag": None, "url": None}
    try:
        return channel_of(json.loads(raw) if raw else None)
    except ValueError:
        return {"channel": "unknown", "tag": None, "url": None}


def describe(info: dict) -> str:
    """``prerelease v0.3.0-rc.2`` / ``stable v0.3.0`` / ``commit 1a2b3c4d5e6f`` / ``local install`` ..."""
    if info["channel"] == "local":
        return "local install"
    if info["channel"] == "index":
        return "from a package index"
    return f"{info['channel']} {info['tag']}" if info.get("tag") else info["channel"]


def recommended(support_value) -> Optional[str]:
    """The ``recommended`` spec inside a platform's ``kaos_lib_support`` (dict or JSON string), or None."""
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


def is_current(req: Requirement, info: dict, version: str) -> bool:
    """Is the installed kaos-lib already what ``req`` asks for?"""
    if req.url:
        return bool(info.get("url")) and info["url"] == req.url
    return bool(req.specifier) and req.specifier.contains(version, prereleases=True) and \
        all(s.operator in ("==", "===") for s in req.specifier)


def pip_command(req: Requirement) -> list:
    return [sys.executable, "-m", "pip", "install", "--upgrade", str(req)]
