"""Which kaos-lib a local environment or build installs.

Why: CI installs the version the platform chose (`ARG KAOS_LIB_PACKAGE`, passed by the build). A laptop does not have
the platform's choice, so the order is: what you pass (`--kaos-lib`), the platform's pipeline-context file when you
have one (`kaosLib.spec`), the version your platform recommends (kept when you signed in), the default your
Dockerfile declares (what a plain local build installs), then this kaosctl's own version from your platform's package
index. The first that exists wins, and the command says which one it used. No address of any platform is built into
kaosctl: the index comes from `kaos_lib.addresses` (environment, the context file, what the platform published).
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

import yaml

from .. import __version__, addresses, channel
from ..errors import ConfigError, KaosLibError


@dataclass
class KaosLibSpec:
    """The kaos-lib to install: the whole pip requirement, the index lines it needs and where the choice came from."""
    requirement: str
    index_urls: list
    source: str


def _context_spec(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        doc = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise KaosLibError(f"cannot read the context file {path}: {exc}") from None
    spec = (doc.get("kaosLib") or {}).get("spec") if isinstance(doc, dict) else None
    return spec.strip() if isinstance(spec, str) and spec.strip() else None


def _indexes_for(requirement, index_url: Optional[str]) -> list:
    """The package index a requirement needs: none for a URL, else the platform's (none when none is known)."""
    return [] if requirement.url or not index_url else [index_url]


def _local(text: Optional[str]) -> Optional[KaosLibSpec]:
    """``--kaos-lib`` naming a checkout, a wheel or an archive on this machine: the spec that installs it. It is the
    person's own file, so unlike a spec the platform recommends it may be a ``file:`` address."""
    path = pathlib.Path(text).expanduser() if text else None
    if path is None or not path.exists():
        return None
    return KaosLibSpec(f"{channel.DIST}[zitadel] @ {path.resolve().as_uri()}", [], "--kaos-lib (a path on this machine)")


def resolve(flag: Optional[str] = None, context: Optional[str] = None, dockerfile_default: Optional[str] = None) -> KaosLibSpec:
    """Choose the kaos-lib requirement (see the module text for the order)."""
    if _local(flag):
        return _local(flag)
    found = addresses.resolve(context)
    recommended = addresses.cached_recommended()
    for text, source in ((flag, "--kaos-lib"), (_context_spec(context), f"the context file {context}"),
                         (recommended, "the version your platform recommends (kept when you signed in)"),
                         (dockerfile_default, "the default of ARG KAOS_LIB_PACKAGE in the Dockerfile")):
        if text:
            try:
                req = channel.requirement(text, zitadel=True)
            except ConfigError as exc:
                raise KaosLibError(f"{source}: {exc}") from None
            return KaosLibSpec(str(req), _indexes_for(req, found.index_url), source)
    if not found.index_url:
        raise KaosLibError(
            f"no kaos-lib to install: none was named (--kaos-lib), the context file has none, your platform has "
            f"recommended none, the Dockerfile declares no default, and this machine knows no package index to "
            f"install kaosctl's own version {__version__} from (kaosctl carries no address of any platform). "
            "Pass --kaos-lib <requirement or path>, sign in with `kaosctl login`, or set KAOS_LIB_INDEX_URL.")
    req = channel.requirement(f"=={__version__}", zitadel=True)
    return KaosLibSpec(str(req), _indexes_for(req, found.index_url),
                       f"this kaosctl's own version ({__version__}), from the package index named by {found.describe('index_url')}")
