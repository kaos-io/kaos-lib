"""Reading a repository's files for the linter, safely.

Why: the linter runs on untrusted repositories. It only reads (never imports or runs) files, refuses symbolic
links and anything outside the repository root, and caps what it reads, so a hostile tree fails with an error
finding and never exhausts the run (T-15).
"""
from __future__ import annotations

import ast
import pathlib
from typing import Optional

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
