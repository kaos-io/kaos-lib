"""The catalogue: the facts some rules need and a pipeline file cannot give (the compute classes a project can use).

Why: the same files must always give the same findings, so these facts are an explicit input. Offline the built-in
default holds only what is true for every project; CI builds the catalogue from the project's platform context;
a rule whose fact is missing is reported as skipped, never as passed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import yaml

from .constants import MAX_FILE_BYTES

SOURCE_DEFAULT = "built-in default"
SOURCE_CONTEXT = "platform context"
SOURCE_FILE = "catalogue file"
SOURCE_NONE = "none"


class CatalogueError(ValueError):
    """The catalogue input is unreadable or not shaped like a catalogue."""


@dataclass(frozen=True)
class Catalogue:
    """Facts for the rules that need them. None means unknown: the rules that need it are skipped."""
    source: str
    classes: Optional[tuple] = None            # every compute class name the project can use

    def to_dict(self) -> dict:
        return {"source": self.source, "classes": None if self.classes is None else sorted(self.classes)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


def default_catalogue() -> Catalogue:
    """The offline catalogue: no class names."""
    return Catalogue(SOURCE_DEFAULT)


def empty_catalogue() -> Catalogue:
    """No facts at all: every rule that needs the catalogue is skipped."""
    return Catalogue(SOURCE_NONE)


def from_dict(d: dict, source: str = SOURCE_FILE) -> Catalogue:
    """A catalogue from its JSON shape (what `to_dict` writes)."""
    if not isinstance(d, dict):
        raise CatalogueError("a catalogue is a JSON object")
    classes = d.get("classes")
    if classes is not None and not (isinstance(classes, list) and all(isinstance(c, str) for c in classes)):
        raise CatalogueError("catalogue 'classes' must be a list of names or null")
    # An exported catalogue keeps where its facts came from, so a report reads the same whether it was made from the
    # context or from the file written from it.
    named = d.get("source") if isinstance(d.get("source"), str) and d.get("source") else source
    return Catalogue(named, None if classes is None else tuple(classes))


def from_context(ctx: dict) -> Catalogue:
    """The catalogue a project's platform context (pipeline-context.yaml) carries.

    Reads only computeClasses.all, hpc.enabled and hpc.classes[]; it needs nothing else and keeps none of the rest.
    """
    if not isinstance(ctx, dict):
        raise CatalogueError("the platform context is not a mapping")
    names = [c["name"] for c in ((ctx.get("computeClasses") or {}).get("all") or [])
             if isinstance(c, dict) and isinstance(c.get("name"), str)]
    hpc = ctx.get("hpc")
    if isinstance(hpc, dict) and hpc.get("enabled") is True:
        names += [c["name"] for c in (hpc.get("classes") or []) if isinstance(c, dict) and isinstance(c.get("name"), str)]
    return Catalogue(SOURCE_CONTEXT, tuple(sorted(set(names))) if names else None)


def read_file(path: str) -> Catalogue:
    """A catalogue from a JSON file written by `kaosctl lint --export-catalogue` (or by hand)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise CatalogueError(f"{path} is larger than {MAX_FILE_BYTES} bytes")
        return from_dict(json.loads(raw.decode("utf-8")))
    except (OSError, ValueError) as exc:
        if isinstance(exc, CatalogueError):
            raise
        raise CatalogueError(f"cannot read the catalogue {path}: {exc}") from exc


def read_context(path: str) -> Catalogue:
    """A catalogue from a platform context file (pipeline-context.yaml, a ConfigMap wrapping it, or the local one)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise CatalogueError(f"{path} is larger than {MAX_FILE_BYTES} bytes")
        doc = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        if isinstance(exc, CatalogueError):
            raise
        raise CatalogueError(f"cannot read the context {path}: {exc}") from exc
    if isinstance(doc, dict) and doc.get("kind") == "ConfigMap" and isinstance(doc.get("data"), dict):
        data = doc["data"]
        key = "context.yaml" if "context.yaml" in data else next(iter(data), None)
        doc = yaml.safe_load(data[key]) if key else {}
    return from_context(doc or {})
