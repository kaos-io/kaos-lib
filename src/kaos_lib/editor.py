"""The KAOS extension for VS Code, as published with this kaos-lib (``kaosctl vscode install``).

Every kaos-lib release publishes the extension built from the same commit, at the same version, next to the
release in the public bucket (``channel.public_vscode``). Installing the one of YOUR kaos-lib keeps the editor and
the ``kaosctl`` it runs in step. The file is checked by its SHA-256 before it is handed to the editor.
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
from typing import Optional

import requests

from .errors import KaosLibError

EDITORS = ("code", "cursor", "codium", "code-insiders")     # looked up in this order when --editor is not given
MAX_BYTES = 20 * 1024 * 1024
TIMEOUT = 60


def find_editor(name: Optional[str] = None) -> Optional[str]:
    """The editor's command line program: ``name`` (a command or a path) when given, else the first one on PATH."""
    for candidate in ((name,) if name else EDITORS):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def download(record: dict, dest: pathlib.Path) -> pathlib.Path:
    """Download the extension a record names into ``dest`` and return the file. Refuses a file that is not the
    one the record's SHA-256 names, or that is larger than an extension can be; nothing is left behind then."""
    name = f"{record['name']}-{record['version']}.vsix"
    try:
        resp = requests.get(record["url"], timeout=TIMEOUT, stream=True)
        if resp.status_code != 200:
            raise KaosLibError(f"could not download {name}: the server answered {resp.status_code}")
        digest, size, chunks = hashlib.sha256(), 0, []
        for chunk in resp.iter_content(chunk_size=1 << 16):
            size += len(chunk)
            if size > MAX_BYTES:
                raise KaosLibError(f"could not download {name}: it is larger than {MAX_BYTES} bytes")
            digest.update(chunk)
            chunks.append(chunk)
    except requests.RequestException as exc:
        raise KaosLibError(f"could not download {name}: {exc}") from None
    if digest.hexdigest() != record["sha256"]:
        raise KaosLibError(f"{name} does not match its published SHA-256; nothing was installed")
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / name
    path.write_bytes(b"".join(chunks))
    return path
