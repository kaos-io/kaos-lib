"""Dataset layouts: declarative specs (``layout.yaml``) that say what a dataset holds, how a new one starts,
what makes it valid and what a pull downloads.

A layout comes from one of these sources, looked up in this order by name:

1. ``builtin``: shipped here (``yolo``, ``raw``), the same files kaos-lake serves.
2. ``installed``: a package's entry point in the group ``kaos_lib.layouts`` (a ``layout.yaml`` path, a folder
   holding one, a module whose folder holds one, a spec dict or a ``Layout``).
3. ``project``: the project's registry in kaos-lake (``GET /kaos/v1/dataset-templates``, from the ``layouts``
   repository of the project's lakeFS).

A path (``./my-layout``, ``layouts/x.yaml``: anything with a ``/`` or ending in ``.yaml``) is read as is
(source ``local``).

    from kaos_lib import layouts
    yolo = layouts.load("yolo")
    yolo.skeleton("dataset-cars", values={"classes": ["car"]})   # {path: bytes}
    yolo.validate("./cars")                                       # ValidationReport (rules + the hook)
    yolo.materialize(ref)                                         # the hook's entry (data.yaml), else the folder

An optional Python ``hook`` (``module`` or ``module:object``) adds ``validate(root, layout) -> [problems]``
and/or ``materialize(data_dir, out_dir, layout) -> Path``. Only kaos-lib runs hooks; kaos-lake checks the
declarative rules only.
"""
from __future__ import annotations

import copy
import importlib
import os
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import datasets
from ..errors import DatasetError, KaosLibError, ValidationFailed
from ..lakefs import LakeFS
from ..transfer import local_files
from . import local, render, rules, spec as _spec
from .render import TemplateError, ValuesError
from .spec import SpecError

__all__ = ["Layout", "ValidationReport", "SpecError", "TemplateError", "ValuesError", "load", "available",
           "builtin_names", "canonical", "ENTRY_POINT_GROUP", "LAYOUTS_REPOSITORY"]

ENTRY_POINT_GROUP = "kaos_lib.layouts"
LAYOUTS_REPOSITORY = "layouts"   # the project's registry in its lakeFS: main holds <name>/layout.yaml
BUILTIN, INSTALLED, PROJECT, LOCAL = "builtin", "installed", "project", "local"
MAX_SHOWN = 30
# Ids datasets may still carry from before a layout got its current name; read as that layout, never listed.
_LEGACY = {"ultralytics": "yolo", "empty": "raw"}


def canonical(name: str) -> str:
    """The current name of a layout id (an old id reads as its layout's current name)."""
    return _LEGACY.get(name, name)


@dataclass
class ValidationReport:
    """Every problem found in a local dataset (aggregated, never first-error-only)."""
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def format(self) -> str:
        shown = self.errors[:MAX_SHOWN]
        lines = [f"  - {e}" for e in shown]
        if len(self.errors) > len(shown):
            lines.append(f"  ... and {len(self.errors) - len(shown)} more")
        return "\n".join(lines) if lines else "dataset is valid"


@dataclass(frozen=True)
class Layout:
    """A checked layout spec and where it came from (``source``: builtin, installed, project or local)."""
    spec: dict
    source: str = LOCAL
    origin: str = ""

    @property
    def name(self) -> str:
        return self.spec["name"]

    @property
    def title(self) -> str:
        return self.spec["title"]

    @property
    def description(self) -> str:
        return self.spec.get("description", "")

    @property
    def version(self) -> str:
        return self.spec.get("version", "")

    @property
    def parameters(self) -> list:
        return self.spec.get("parameters", [])

    @property
    def include(self) -> Optional[list]:
        """What a pull downloads (patterns), or None for the whole tree."""
        return self.spec.get("materialize", {}).get("include")

    # ---- hook
    def hook(self) -> Any:
        """The hook object (a module or an attribute of one), or None when the layout has none.

        A project layout's hook runs only when its package is installed here; otherwise a warning says the
        hook's checks are skipped. Any other layout's hook must import.
        """
        ref = self.spec.get("hook")
        if not ref:
            return None
        module, _, attr = ref.partition(":")
        try:
            obj = importlib.import_module(module)
            return getattr(obj, attr) if attr else obj
        except (ImportError, AttributeError) as exc:
            if self.source == PROJECT:
                print(f"WARNING: layout {self.name}: its hook {ref} is not installed here ({exc}); only the "
                      "declarative rules are checked.", file=sys.stderr)
                return None
            raise DatasetError(f"layout {self.name}: cannot load its hook {ref}: {exc}") from None

    def _hook_fn(self, name: str):
        h = self.hook()
        fn = getattr(h, name, None) if h is not None else None
        return fn if callable(fn) else None

    # ---- create
    def skeleton(self, name: str, description: str = "", values: Optional[dict] = None) -> dict:
        """Files of a new dataset ``name``: ``{repo path: bytes}`` (empty folders as ``<folder>/.keep``)."""
        return {p: t.encode() for p, t in render.render(self.spec, name, description, values).items()}

    def parse(self, content: str) -> dict:
        """The parameter values the layout's ``form_file`` holds (for editing an existing dataset)."""
        return render.parse_form(self.spec, content)

    # ---- validate
    def check(self, local_dir) -> list:
        """Problems the declarative rules find in ``local_dir`` (what kaos-lake checks too)."""
        root = pathlib.Path(local_dir)
        files = local_files(root)
        return rules.check(self.spec, files, lambda p: files[p].read_bytes())

    def validate(self, local_dir) -> ValidationReport:
        """Every problem of ``local_dir``: the declarative rules, then the hook's ``validate``."""
        root = pathlib.Path(local_dir)
        if not root.is_dir():
            return ValidationReport([f"{root} is not a directory"])
        errors = self.check(root)
        fn = self._hook_fn("validate")
        if fn:
            errors += [str(e) for e in fn(root, self)]
        return ValidationReport(errors)

    def publish(self, local_dir, repo: str, message: str, via_pull_request: bool = True,
                description: str = "", validate_first: bool = True, metadata: Optional[dict] = None,
                client: Optional[LakeFS] = None) -> datasets.PublishResult:
        """Validate, then upload ``local_dir`` to ``repo`` through a draft branch and a pull request.

        Creates ``repo`` first when missing (labels kaos.kind=dataset, kaos.template=<this layout>). Raises
        ValidationFailed with every problem when the dataset is invalid (``validate_first=False`` skips the
        check). ``metadata`` is recorded on the commit. A dataset another project shares is refused first.
        """
        datasets.refuse_shared(repo, "push to")
        if validate_first:
            report = self.validate(local_dir)
            if not report.ok:
                raise ValidationFailed(report.errors)
        labels = {datasets.LABEL_KIND: "dataset", datasets.LABEL_TEMPLATE: self.name}
        if description:
            labels[datasets.LABEL_DESCRIPTION] = description
        return datasets.publish_tree(local_dir, repo, message, via_pull_request, labels, client, metadata)

    # ---- read
    def materialize(self, ref: datasets.DatasetRef, dest=None, client: Optional[LakeFS] = None,
                    commit: Optional[str] = None, prefix: Optional[str] = None) -> pathlib.Path:
        """A local copy of ``ref`` at its pinned commit; returns the hook's entry (yolo: ``data.yaml``) or the folder.

        Downloads what ``materialize.include`` names (default: the whole tree), cached by (owner, repo, commit,
        prefix) in ``dest`` (default: the cache); a second call is free. A whole staged copy of the commit (a
        folder under KAOS_STAGED_ROOT) is used in place. ``prefix`` (one folder, stripped) works only for layouts that download the
        whole tree with no materialize hook. A shared reference (``<owner>/dataset-x@v1``) is read from the owner.
        """
        entry = self._hook_fn("materialize")
        if prefix and (self.include or entry):
            raise DatasetError(f"prefix= only works with layouts that download the whole tree (raw); "
                               f"{self.name} does not.")
        ref, client = datasets.source(ref, client)
        commit = datasets.resolve(ref, client, commit)
        pre = (prefix.strip("/") + "/") if prefix and prefix.strip("/") else None
        target = pathlib.Path(dest) if dest else local.cache_dir(ref.repo, commit, pre, ref.owner)
        staged = local.staged_dir(commit, repo=ref.repo, owner=ref.owner)
        if staged and (not pre or (staged / pre).is_dir()):
            data = staged / pre if pre else staged
        elif local.marker_matches(target, ref.repo, commit, pre, owner=ref.owner, include=self.include):
            data = target
        else:
            include = self.include
            prefixes = [rules.list_prefix(g) for g in include] if include else [pre or ""]
            keep = (lambda p: any(rules.matches(g, p) for g in include)) if include else None
            what = f" ({', '.join(include)})" if include else (f" under {pre}" if pre else "")
            local.fetch(client, ref.repo, commit, prefixes, target, pre, strip=pre or "", owner=ref.owner,
                        include=include, keep=keep, empty_message=f"{ref} holds no files{what}.")
            data = target
        entry = self.entry_of(data, target)
        if data == target:
            local.restamp(target)
        return entry

    def entry_of(self, data: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        """The entry of a copy that is already on disk in ``data``: the hook's (written into ``target``), or ``data``."""
        entry = self._hook_fn("materialize")
        return pathlib.Path(entry(data, target, self)) if entry else data


# ------------------------------------------------------------------ sources
def builtin_names() -> list:
    return sorted(p.name for p in (_spec.SHARED / "builtin").iterdir() if (p / "layout.yaml").is_file())


_BUILTIN: dict = {}


def _builtin(name: str) -> Layout:
    if name not in _BUILTIN:
        path = _spec.SHARED / "builtin" / name / "layout.yaml"
        _BUILTIN[name] = Layout(_spec.read(path, f"built-in layout {name}"), BUILTIN, str(path))
    return _BUILTIN[name]


def _entry_points() -> list:
    from importlib.metadata import entry_points
    eps = entry_points()
    return list(eps.select(group=ENTRY_POINT_GROUP) if hasattr(eps, "select") else eps.get(ENTRY_POINT_GROUP, []))


def _from_object(obj: Any, origin: str) -> Layout:
    if isinstance(obj, Layout):
        return Layout(obj.spec, INSTALLED, obj.origin or origin)
    if isinstance(obj, dict):
        return Layout(_spec.from_value(copy.deepcopy(obj), origin), INSTALLED, origin)
    if isinstance(obj, (str, os.PathLike)):
        return Layout(_spec.read(pathlib.Path(obj), origin), INSTALLED, str(obj))
    if getattr(obj, "__file__", None):   # a module: its folder holds layout.yaml
        path = pathlib.Path(obj.__file__).parent / "layout.yaml"
        return Layout(_spec.read(path, origin), INSTALLED, str(path))
    raise SpecError(f"{origin}: an entry point must give a layout.yaml path, a folder, a module, a dict or a Layout")


def installed() -> list:
    """Layouts installed packages publish (entry point group ``kaos_lib.layouts``); broken ones are warned about."""
    out = []
    for ep in _entry_points():
        origin = f"entry point {ep.name} = {ep.value}"
        try:
            out.append(_from_object(ep.load(), origin))
        except Exception as exc:  # noqa: BLE001 - one broken package must not hide the others
            print(f"WARNING: skipping layout {origin}: {exc}", file=sys.stderr)
    return out


def project(client: LakeFS) -> list:
    """The project's own layouts, as kaos-lake serves them (none from a kaos-lake that has no registry)."""
    out = []
    for entry in (client.dataset_templates() or {}).get("templates", []):
        if not isinstance(entry, dict) or entry.get("source") != PROJECT or not isinstance(entry.get("spec"), dict):
            continue
        origin = f"project layout {entry['spec'].get('name')} ({client.base_url})"
        try:
            out.append(Layout(_spec.from_value(entry["spec"], origin), PROJECT, origin))
        except SpecError as exc:
            print(f"WARNING: skipping {exc}", file=sys.stderr)
    return out


def _looks_like_path(name: str) -> bool:
    return "/" in name or os.sep in name or name.endswith((".yaml", ".yml")) or name in (".", "..")


def _project_client(client: Optional[LakeFS]) -> Optional[LakeFS]:
    if client is not None:
        return client
    try:
        return LakeFS.connect()
    except KaosLibError:
        return None


def load(name, client: Optional[LakeFS] = None) -> Layout:
    """The layout ``name`` (a ``Layout``, a path, or a name: builtin, then installed, then the project's).

    The project registry is asked only when no local layout has the name; without ``client`` the default
    connection is tried, and skipped when there is none.
    """
    if isinstance(name, Layout):
        return name
    name = canonical(str(name))
    if _looks_like_path(name):
        path = pathlib.Path(name)
        if not path.exists():
            raise DatasetError(f"no layout at {name}: give a layout.yaml file or a folder holding one.")
        return Layout(_spec.read(path), LOCAL, str(path))
    if name in builtin_names():
        return _builtin(name)
    for layout in installed():
        if layout.name == name:
            return layout
    c = _project_client(client)
    for layout in project(c) if c else []:
        if layout.name == name:
            return layout
    known = sorted({lay.name for lay in available(c, warn=False)})
    hint = "" if c else " (not signed in: the project's layouts were not looked up)"
    raise DatasetError(f"unknown layout {name!r}. Known: {', '.join(known)}{hint}.")


def available(client: Optional[LakeFS] = None, warn: bool = True) -> list:
    """Every layout by source: builtin, installed, then the project's (when ``client`` is given).

    A name already taken by an earlier source is left out of later ones (``load`` would never pick it);
    with ``warn`` a note says so.
    """
    out, seen = [], set()
    candidates = [_builtin(n) for n in builtin_names()] + installed() + (project(client) if client else [])
    for layout in candidates:
        if layout.name in seen:
            if warn:
                print(f"NOTE: {layout.source} layout {layout.name} ({layout.origin}) is shadowed by an earlier "
                      "one with the same name.", file=sys.stderr)
            continue
        seen.add(layout.name)
        out.append(layout)
    return out
