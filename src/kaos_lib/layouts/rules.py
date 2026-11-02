"""The declarative rules of a layout, checked over a dataset tree; and the path patterns they use.

Shared with kaos-lake (``pkg/kaos/templates/rules.go``): both give the same problems, in the same order and
words, on the fixtures. Patterns are POSIX paths: ``*`` and ``?`` within one folder level, ``**`` (a whole
level) any number of levels. Files with a part starting with ``.`` (``.keep``, markers) are not looked at.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable

from . import spec as _spec

MAX_LINE_SHOWN = 80


def glob_regex(pattern: str) -> "re.Pattern":
    parts, out = pattern.split("/"), []
    for i, seg in enumerate(parts):
        last = i == len(parts) - 1
        if seg == "**":
            out.append(".*" if last else "(?:[^/]*/)*")
            continue
        out.append("".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in seg))
        if not last:
            out.append("/")
    return re.compile("".join(out), re.ASCII | re.DOTALL)


def matches(pattern: str, path: str) -> bool:
    return glob_regex(pattern).fullmatch(path) is not None


def fixed_prefix(pattern: str) -> str:
    """The literal folders a pattern starts with (``images/`` of ``images/**``), ending in ``/`` or empty."""
    literal = []
    for seg in pattern.split("/")[:-1]:
        if "*" in seg or "?" in seg:
            break
        literal.append(seg)
    return "".join(s + "/" for s in literal)


def list_prefix(pattern: str) -> str:
    """The lakeFS listing prefix covering ``pattern``: the path itself without wildcards, else its literal folders."""
    return fixed_prefix(pattern) if "*" in pattern or "?" in pattern else pattern


def extension(path: str) -> str:
    """``.jpg`` of ``a/b.JPG`` (lower case), or ``""``."""
    seg = path.rsplit("/", 1)[-1]
    i = seg.rfind(".")
    return seg[i:].lower() if i > 0 else ""


def stem(path: str, prefix: str) -> str:
    """``train/a`` of ``images/train/a.jpg`` below ``images/``."""
    rel = path[len(prefix):]
    ext = extension(rel)
    return rel[: len(rel) - len(ext)] if ext else rel


def visible(path: str) -> bool:
    return not any(s.startswith(".") for s in path.split("/"))


def check(spec: dict, paths: Iterable[str], read: Callable[[str], bytes]) -> list:
    """Every problem ``spec``'s rules find in the tree ``paths`` (``read(path)`` gives a file's bytes)."""
    files = sorted(p for p in set(paths) if visible(p))
    present = set(files)
    rules, errors = spec.get("rules", {}), []
    for g in rules.get("required", []):
        rx = glob_regex(g)
        if not any(rx.fullmatch(p) for p in files):
            errors.append(f"{g}: no file matches (required)")
    if rules.get("allowed"):
        allowed = [glob_regex(g) for g in rules["allowed"]]
        errors += [f"{p}: not part of this layout" for p in files if not any(rx.fullmatch(p) for rx in allowed)]
    for rule in rules.get("extensions", []):
        rx, ok = glob_regex(rule["files"]), [e.lower() for e in rule["allowed"]]
        for p in files:
            if rx.fullmatch(p) and extension(p) not in ok:
                errors.append(f"{p}: extension {extension(p) or '(none)'} is not allowed here ({', '.join(ok)})")
    for rule in rules.get("pairs", []):
        rx, prefix = glob_regex(rule["files"]), fixed_prefix(rule["files"])
        exts = [e.lower() for e in rule.get("extensions", [])]
        for p in files:
            if rx.fullmatch(p) and (not exts or extension(p) in exts):
                needed = rule["needs"].replace("{stem}", stem(p, prefix))
                if needed not in present:
                    errors.append(f"{p} has no {needed}")
    for rule in rules.get("lines", []):
        rx, line_rx = glob_regex(rule["files"]), re.compile(rule["pattern"], re.ASCII)
        message = rule.get("message") or f"does not match {rule['pattern']}"
        for p in files:
            if rx.fullmatch(p):
                errors += _lines(p, read(p), line_rx, message)
    for rule in rules.get("manifests", []):
        if rule["file"] in present:
            errors += _manifest(rule["file"], read(rule["file"]), rule["schema"])
    return errors


def _lines(path: str, data: bytes, rx: "re.Pattern", message: str) -> list:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{path}: not UTF-8 text"]
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        line = line.strip(" \t\r")
        if line and not rx.fullmatch(line):
            out.append(f"{path}:{n}: {message}: {line[:MAX_LINE_SHOWN]}")
    return out


def _manifest(path: str, data: bytes, schema: dict) -> list:
    try:
        value = _spec.load_yaml(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return [f"{path}: not valid YAML"]
    return [f"{path}: {e}" for e in _spec.validate(value, schema)]
