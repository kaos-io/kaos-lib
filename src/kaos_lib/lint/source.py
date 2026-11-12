"""Reading a repository's files for the linter, safely.

Why: the linter runs on untrusted repositories. It only reads (never imports or runs) files, refuses symbolic
links and anything outside the repository root, and caps what it reads, so a hostile tree fails with an error
finding and never exhausts the run (T-15).
"""
from __future__ import annotations

import ast
import fnmatch
import os
import pathlib
from typing import Iterator, Optional

from .constants import MAX_FILE_BYTES
from .model import Span


class TooLarge(Exception):
    """A file is above the size the linter reads."""


class SourceFile:
    """One text file of the repository, with helpers to turn syntax-tree positions into report ranges."""

    def __init__(self, rel: str, text: str):
        self.rel = rel
        self.text = text
        self.lines = text.splitlines()
        self.tree: Optional[ast.AST] = None

    def column(self, line: int, byte_offset: int) -> int:
        """1-based character column of a UTF-8 byte offset on a 1-based line (the syntax tree counts bytes)."""
        if not 1 <= line <= len(self.lines):
            return byte_offset + 1
        prefix = self.lines[line - 1].encode("utf-8")[:byte_offset]
        return len(prefix.decode("utf-8", errors="ignore")) + 1

    def span(self, node: ast.AST) -> Span:
        """The range of a syntax-tree node."""
        line, end_line = node.lineno, getattr(node, "end_lineno", None) or node.lineno
        end_col = getattr(node, "end_col_offset", None)
        end_col = self.column(end_line, end_col) if end_col is not None else self.column(line, node.col_offset)
        return Span(line, self.column(line, node.col_offset), end_line, end_col)


SKIP_DIRS = {".git", ".venv", "venv", ".kaos", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache",
             "site-packages"}


def _ignored_names(folder: pathlib.Path) -> list:
    """The plain names (no slash inside) that the folder's ``.gitignore`` lists: what it is enough to skip here."""
    try:
        lines = (folder / ".gitignore").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    names = [line.strip().strip("/") for line in lines if line.strip() and line.strip()[0] not in "#!"]
    return [n for n in names if n and "/" not in n]


def walk(folder: pathlib.Path) -> Iterator[pathlib.Path]:
    """Every file below ``folder``, in order, that is the repository's own: never a virtualenv (any folder with a
    ``pyvenv.cfg``, and ``.venv``), ``.kaos/``, a cache, ``node_modules``, or a name the folder's ``.gitignore``
    lists. Links are not followed."""
    ignored = _ignored_names(folder)

    def skip(name: str, parent: str) -> bool:
        return name in SKIP_DIRS or any(fnmatch.fnmatch(name, pattern) for pattern in ignored) \
            or os.path.isfile(os.path.join(parent, name, "pyvenv.cfg"))

    for parent, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not skip(d, parent))
        for name in sorted(files):
            if not any(fnmatch.fnmatch(name, pattern) for pattern in ignored):
                yield pathlib.Path(parent, name)


def inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    """True when path is a regular (non-link) file whose real location is under root."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def read_text(root: pathlib.Path, path: pathlib.Path, rel: Optional[str] = None) -> Optional[SourceFile]:
    """The file as text, or None when it is missing, a link, outside the root or not valid UTF-8.

    Raises TooLarge when it is above MAX_FILE_BYTES.
    """
    if not inside(root, path):
        return None
    if path.stat().st_size > MAX_FILE_BYTES:
        raise TooLarge(rel or str(path))
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return SourceFile(rel or path.relative_to(root).as_posix(), text)


def parse_python(src: SourceFile) -> Optional[ast.AST]:
    """Parse the file's text into a syntax tree. Parsing never runs the code. None when it does not parse."""
    try:
        src.tree = ast.parse(src.text, filename=src.rel)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        src.tree = None
    return src.tree


def buffer_source(text: str, rel: str) -> SourceFile:
    """A SourceFile for text that is not on disk yet (an editor's unsaved buffer), under the same size limit."""
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise TooLarge(rel)
    return SourceFile(rel, text)
