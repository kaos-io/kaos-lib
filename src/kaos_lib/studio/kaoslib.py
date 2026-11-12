"""Which kaos-lib a local environment or build installs.

Why: CI installs the version the platform chose (`ARG KAOS_LIB_PACKAGE`, passed by the build). A laptop does not have
the platform's choice, so the order is: what you pass (`--kaos-lib`), the platform's pipeline-context file when you
have one (`kaosLib.spec`), the default your Dockerfile declares (what a plain local build installs), then this
kaosctl's own version. The first that exists wins, and the command says which one it used.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

import yaml

from .. import __version__, channel
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


def _indexes_for(requirement) -> list:
    """The package indexes a requirement needs: none for a URL, else the channel of its version (both when unclear)."""
    if requirement.url:
        return []
    pins = [s.version for s in requirement.specifier if s.operator in ("==", "===")]
    kind = channel.channel_of_version(pins[0]) if pins else "unknown"
    return [channel.INDEXES[kind]] if kind in channel.INDEXES else list(channel.INDEXES.values())


def _local(text: Optional[str]) -> Optional[str]:
    """``--kaos-lib`` naming a checkout, a wheel or an archive on this machine: the requirement that installs it."""
    path = pathlib.Path(text).expanduser() if text else None
    return f"{channel.DIST}[zitadel] @ {path.resolve().as_uri()}" if path is not None and path.exists() else text


def resolve(flag: Optional[str] = None, context: Optional[str] = None, dockerfile_default: Optional[str] = None) -> KaosLibSpec:
    """Choose the kaos-lib requirement (see the module text for the order)."""
    for text, source in ((_local(flag), "--kaos-lib"), (_context_spec(context), f"the context file {context}"),
                         (dockerfile_default, "the default of ARG KAOS_LIB_PACKAGE in the Dockerfile")):
        if text:
            try:
                req = channel.requirement(text, zitadel=True)
            except ConfigError as exc:
                raise KaosLibError(f"{source}: {exc}") from None
            return KaosLibSpec(str(req), _indexes_for(req), source)
    req = channel.requirement(f"=={__version__}", zitadel=True)
    return KaosLibSpec(str(req), _indexes_for(req), f"this kaosctl's own version ({__version__})")
