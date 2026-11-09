"""The catalogue: the facts some rules need and a pipeline file cannot give (compute classes, the longest HPC
(Slurm) run, the continuation cap).

Why: the same files must always give the same findings, so these facts are an explicit input. Offline the built-in
default holds only what is true for every project; CI builds the catalogue from the project's platform context;
a rule whose fact is missing is reported as skipped, never as passed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import yaml

from .constants import (DEFAULT_LANE_MAX_MINUTES, DEFAULT_LIMIT_MINUTES, DEFAULT_MAX_CONTINUATIONS, MAX_FILE_BYTES,
                        MAX_REASON_CHARS)

SOURCE_DEFAULT = "built-in default"
SOURCE_CONTEXT = "platform context"
SOURCE_FILE = "catalogue file"
SOURCE_NONE = "none"


class CatalogueError(ValueError):
    """The catalogue input is unreadable or not shaped like a catalogue."""


@dataclass(frozen=True)
class HpcFacts:
    """What the project's HPC (Slurm) site allows. lane_max_minutes is the longest run of a step on it."""
    lane_max_minutes: int
    default_limit_minutes: int = DEFAULT_LIMIT_MINUTES


@dataclass(frozen=True)
class StepEvidence:
    """What the platform recorded about one step of the app: did a continuation load its checkpoint and get past it.

    verified False carries the platform's reason in words (for example "NoProgress: ..."). Only the step's name, the
    verdict, when it was recorded and that reason are kept: nothing about the jobs themselves.
    """
    name: str
    verified: bool
    since: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "verified": self.verified, "since": self.since, "reason": self.reason}


@dataclass(frozen=True)
class Catalogue:
    """Facts for the rules that need them. None means unknown: the rules that need it are skipped."""
    source: str
    classes: Optional[tuple] = None            # every compute class name the project can use
    hpc: Optional[HpcFacts] = None             # None: unknown, or the project has no HPC (Slurm) site
    max_continuations: Optional[int] = None
    hpc_note: str = ""                         # why hpc is None, for the skipped-rule message
    steps: Optional[tuple] = None              # StepEvidence per step the platform has evidence for; None: none given

    def evidence(self, step_name) -> Optional[StepEvidence]:
        """The platform's evidence for the step, or None (no evidence is never read as "not resumable")."""
        return next((e for e in self.steps or () if e.name == step_name), None)

    def to_dict(self) -> dict:
        hpc = None if self.hpc is None else {"laneMaxMinutes": self.hpc.lane_max_minutes,
                                             "defaultLimitMinutes": self.hpc.default_limit_minutes}
        return {"source": self.source, "classes": None if self.classes is None else sorted(self.classes),
                "hpc": hpc, "maxContinuations": self.max_continuations,
                "resumableSteps": None if self.steps is None else [e.to_dict() for e in
                                                                   sorted(self.steps, key=lambda e: e.name)]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"


def default_catalogue() -> Catalogue:
    """The offline catalogue: the continuation cap and the default HPC (Slurm) lane; no class names."""
    return Catalogue(SOURCE_DEFAULT, None, HpcFacts(DEFAULT_LANE_MAX_MINUTES), DEFAULT_MAX_CONTINUATIONS)


def empty_catalogue() -> Catalogue:
    """No facts at all: every rule that needs the catalogue is skipped."""
    return Catalogue(SOURCE_NONE, None, None, None, "no catalogue was given")


def from_dict(d: dict, source: str = SOURCE_FILE) -> Catalogue:
    """A catalogue from its JSON shape (what `to_dict` writes)."""
    if not isinstance(d, dict):
        raise CatalogueError("a catalogue is a JSON object")
    classes = d.get("classes")
    if classes is not None and not (isinstance(classes, list) and all(isinstance(c, str) for c in classes)):
        raise CatalogueError("catalogue 'classes' must be a list of names or null")
    hpc = d.get("hpc")
    facts = None
    if hpc is not None:
        if not isinstance(hpc, dict) or not isinstance(hpc.get("laneMaxMinutes"), int) or hpc["laneMaxMinutes"] <= 0:
            raise CatalogueError("catalogue 'hpc' needs a positive integer 'laneMaxMinutes' (or be null)")
        facts = HpcFacts(hpc["laneMaxMinutes"], int(hpc.get("defaultLimitMinutes", DEFAULT_LIMIT_MINUTES)))
    cont = d.get("maxContinuations")
    if cont is not None and not (isinstance(cont, int) and cont >= 0):
        raise CatalogueError("catalogue 'maxContinuations' must be a non-negative integer or null")
    # An exported catalogue keeps where its facts came from, so a report reads the same whether it was made from the
    # context or from the file written from it.
    named = d.get("source") if isinstance(d.get("source"), str) and d.get("source") else source
    return Catalogue(named, None if classes is None else tuple(classes), facts, cont,
                     "" if facts else "the catalogue lists no HPC (Slurm) site",
                     _evidence(d.get("resumableSteps"), CatalogueError))


def _evidence(raw, error) -> Optional[tuple]:
    """StepEvidence from a `resumableSteps` list: [{name, verified, since, reason}]. None when no list is given.

    Entries that are not shaped so are an error in a catalogue file (it is machine-written) and are ignored in a
    context (a bad entry must not stop a pull request check). One entry per step: the latest `since` wins.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        if error is CatalogueError:
            raise CatalogueError("catalogue 'resumableSteps' must be a list or null")
        return None
    best = {}
    for item in raw:
        ok = isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"] \
            and isinstance(item.get("verified"), bool)
        if not ok:
            if error is CatalogueError:
                raise CatalogueError("each catalogue 'resumableSteps' entry needs a 'name' and a boolean 'verified'")
            continue
        since = item.get("since")
        reason = item.get("reason")
        e = StepEvidence(item["name"], item["verified"], since if isinstance(since, str) else "",
                         reason[:MAX_REASON_CHARS] if isinstance(reason, str) else "")
        if e.name not in best or e.since >= best[e.name].since:
            best[e.name] = e
    return tuple(best[n] for n in sorted(best))


def from_context(ctx: dict) -> Catalogue:
    """The catalogue a project's platform context (pipeline-context.yaml) carries.

    Reads only computeClasses.all, hpc.enabled, hpc.limits.maxTimeLimitMinutes, hpc.classes[] and
    hpc.resumableSteps[] (the platform's evidence per step: name, verified, since, reason); it needs nothing else and
    keeps none of the rest. A context with no `hpc` block gets the built-in default lane; one that says the
    project has no HPC (Slurm) site gets none (the HPC rules are skipped).
    """
    if not isinstance(ctx, dict):
        raise CatalogueError("the platform context is not a mapping")
    names = [c["name"] for c in ((ctx.get("computeClasses") or {}).get("all") or [])
             if isinstance(c, dict) and isinstance(c.get("name"), str)]
    hpc = ctx.get("hpc")
    facts, note, steps = HpcFacts(DEFAULT_LANE_MAX_MINUTES), "", None
    if isinstance(hpc, dict):
        steps = _evidence(hpc.get("resumableSteps"), ValueError)
        if hpc.get("enabled") is True:
            hpc_classes = [c for c in (hpc.get("classes") or []) if isinstance(c, dict)]
            names += [c["name"] for c in hpc_classes if isinstance(c.get("name"), str)]
            facts = HpcFacts(_lane_max(hpc, hpc_classes))
        else:
            facts, note = None, "the project has no HPC (Slurm) site"
    return Catalogue(SOURCE_CONTEXT, tuple(sorted(set(names))) if names else None, facts,
                     DEFAULT_MAX_CONTINUATIONS, note, steps)


def _lane_max(hpc: dict, classes: list) -> int:
    """The longest run a step may ask for: the project's limit, else the longest class limit, else the default."""
    limit = (hpc.get("limits") or {}).get("maxTimeLimitMinutes")
    if isinstance(limit, int) and limit > 0:
        return limit
    longest = [c["maxTimeLimitMinutes"] for c in classes
               if isinstance(c.get("maxTimeLimitMinutes"), int) and c["maxTimeLimitMinutes"] > 0]
    return max(longest) if longest else DEFAULT_LANE_MAX_MINUTES


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
