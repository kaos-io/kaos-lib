"""Where this platform keeps its kaos-lib releases, package index and documentation: never a compiled default.

Why: one wheel runs on every platform (dev, stage, prod), so it must not carry the address of any of them. The
addresses come from the platform the person or the build is working with. For each of the four names the FIRST of
these that has it wins:

1. the environment: ``KAOS_LIB_RELEASES_BASE``, ``KAOS_LIB_INDEX_URL``, ``KAOS_LIB_DOCS_BASE``;
2. the context file (``pipeline-context.yaml``) when one is given: ``kaosLib.support.addresses``;
3. the platform's ``/kaos/v1/ui`` ``kaos_lib_support.addresses``, which ``kaosctl login`` and ``kaosctl upgrade``
   keep in a small file next to the login session;
4. none: the answer is None, and the caller says so. It never falls back to another platform's address.

The names (the same as the ``addresses`` object of a release record)::

    releases_base   https://<bucket>            consumers append <rc|stable>/<tag>/... (no trailing slash)
    index_url       https://<package index>/simple/
    docs_base       https://<bucket>/docs/<tag>/
    docs_current    https://<bucket>/docs/current/

Only the standard library and PyYAML: the standalone linter imports this without ``requests``.
"""
from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass, field
from typing import Optional

KEYS = ("releases_base", "index_url", "docs_base", "docs_current")
ENV = {"releases_base": "KAOS_LIB_RELEASES_BASE", "index_url": "KAOS_LIB_INDEX_URL", "docs_base": "KAOS_LIB_DOCS_BASE"}
CACHE_NAME = "platform-support.json"


@dataclass(frozen=True)
class Addresses:
    """The resolved addresses; a name nothing provided is None. ``source`` says where each one came from."""
    releases_base: Optional[str] = None
    index_url: Optional[str] = None
    docs_base: Optional[str] = None
    docs_current: Optional[str] = None
    source: dict = field(default_factory=dict)

    def describe(self, key: str) -> str:
        return self.source.get(key, "nowhere")


def clean(value, key: str = "") -> Optional[str]:
    """A published address: an https URL with no spaces, else None. releases_base has no trailing slash; the
    docs folders and the index keep theirs (they are folders)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("https://") or any(c.isspace() for c in text) or len(text) <= len("https://"):
        return None
    return text.rstrip("/") if key == "releases_base" else text


def from_block(block, source: str) -> dict:
    """The valid addresses of an ``addresses`` object (a dict or a JSON string), as {name: (url, source)}."""
    if isinstance(block, str):
        try:
            block = json.loads(block)
        except ValueError:
            return {}
    if not isinstance(block, dict):
        return {}
    out = {}
    for key in KEYS:
        url = clean(block.get(key), key)
        if url:
            out[key] = (url, source)
    return out


def from_env(environ=None) -> dict:
    env = os.environ if environ is None else environ
    out = {}
    for key, name in ENV.items():
        value = (env.get(name) or "").strip()
        if value:   # the person's own override: any address they name, as with any environment setting
            out[key] = (value.rstrip("/") if key == "releases_base" else value, f"the environment ({name})")
    return out


def _yaml_load(path: str):
    import yaml
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))


def from_context(path: Optional[str]) -> dict:
    """``kaosLib.support.addresses`` of the platform's context file; {} when there is no file or no block."""
    if not path:
        return {}
    try:
        doc = _yaml_load(path)
    except Exception:  # noqa: BLE001 - an unreadable file gives no addresses; the caller that needs the file says why
        return {}
    support = ((doc or {}).get("kaosLib") or {}).get("support") if isinstance(doc, dict) else None
    block = support.get("addresses") if isinstance(support, dict) else None
    return from_block(block, f"the context file {path}")


def cache_path() -> pathlib.Path:
    """Next to the login session (``~/.config/kubecore-ml``, or ``$KUBECORE_ML_HOME``)."""
    home = os.environ.get("KUBECORE_ML_HOME") or pathlib.Path.home() / ".config" / "kubecore-ml"
    return pathlib.Path(home) / CACHE_NAME


def _read_cache() -> dict:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_platform(base_url: str, support_value) -> None:
    """Keep the platform's ``kaos_lib_support`` (its ``recommended`` and ``addresses``) for ``base_url`` and make it
    the last one used. A platform that publishes none removes its entry. Never fails the command that calls it."""
    try:
        if isinstance(support_value, str):
            support_value = json.loads(support_value)
        base = base_url.rstrip("/")
        data = _read_cache()
        platforms: dict = data.get("platforms") if isinstance(data.get("platforms"), dict) else {}  # type: ignore[assignment]
        entry: dict = {}
        if isinstance(support_value, dict):
            if isinstance(support_value.get("addresses"), dict):
                entry["addresses"] = {k: v for k, v in support_value["addresses"].items() if k in KEYS}
            if isinstance(support_value.get("recommended"), str) and support_value["recommended"].strip():
                entry["recommended"] = support_value["recommended"].strip()
        if entry:
            platforms[base] = entry
        else:
            platforms.pop(base, None)
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last": base, "platforms": platforms}, indent=2))
    except Exception:  # noqa: BLE001 - a cache is a convenience
        pass


def platform_entry(base_url: Optional[str] = None) -> dict:
    """What login kept for ``base_url`` (else for the last platform signed in to): {addresses?, recommended?}."""
    data = _read_cache()
    platforms: dict = data.get("platforms") if isinstance(data.get("platforms"), dict) else {}  # type: ignore[assignment]
    key = (base_url or "").rstrip("/") or data.get("last")
    entry = platforms.get(key) if isinstance(key, str) else None
    return entry if isinstance(entry, dict) else {}


def from_cache(base_url: Optional[str] = None) -> dict:
    entry = platform_entry(base_url)
    return from_block(entry.get("addresses"), "the platform (kept at login)")


def cached_recommended(base_url: Optional[str] = None) -> Optional[str]:
    """The ``recommended`` kaos-lib spec the platform published when this machine last asked, or None."""
    value = platform_entry(base_url).get("recommended")
    return value if isinstance(value, str) and value else None


def resolve(context: Optional[str] = None, base_url: Optional[str] = None, environ=None) -> Addresses:
    """The addresses for this machine (see the module text for the order)."""
    layers = (from_env(environ), from_context(context), from_cache(base_url))
    values, source = {}, {}
    for key in KEYS:
        for layer in layers:
            if key in layer:
                values[key], source[key] = layer[key]
                break
    return Addresses(source=source, **values)


LINT_ENV = "KAOS_LIB_LINT_DOC_BASE"


def lint_doc_base(context: Optional[str] = None, environ=None) -> Optional[str]:
    """The folder of the rule pages, ending in ``/``: ``$KAOS_LIB_LINT_DOC_BASE``, else ``<docs_base>lint/`` from the
    environment or a context file, else None (a report then carries no rule links). The linter reads local files
    only, so it never asks the platform."""
    env = os.environ if environ is None else environ
    own = clean((env.get(LINT_ENV) or "").strip())
    if own:
        return own if own.endswith("/") else own + "/"
    for layer in (from_env(environ), from_context(context)):
        docs = clean(layer["docs_base"][0]) if "docs_base" in layer else None
        if docs:
            return (docs if docs.endswith("/") else docs + "/") + "lint/"
    return None
