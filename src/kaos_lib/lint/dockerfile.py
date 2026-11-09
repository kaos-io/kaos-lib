"""A small, static Dockerfile reader: instructions, FROM lines, COPY sources and `pip install` commands.

Why: the Dockerfile doctor (rules L-D01 .. L-D08) and `kaosctl dev` must read the same facts from a step's
Dockerfile without building or running anything. Only the parts the platform's step images use are understood;
anything unusual is left alone rather than guessed at.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Optional

PIP_VALUE_OPTIONS = frozenset((
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url", "--extra-index-url",
    "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--platform", "--python-version",
    "--implementation", "--abi", "--only-binary", "--no-binary", "--progress-bar", "--trusted-host",
    "--global-option", "--config-settings", "-C", "--upgrade-strategy", "--src", "--cert", "--proxy",
    "--retries", "--timeout", "--cache-dir", "--report", "--exists-action", "--use-feature", "--python",
))
_PYTHON_IMAGE = re.compile(r"^(?:docker\.io/)?(?:library/)?python:(\d+\.\d+)")
_SHELL_JOINERS = {"&&", "||", ";", "|", "&"}


@dataclass(frozen=True)
class Instruction:
    """One Dockerfile instruction: upper-case keyword, the text after it, and its 1-based line range."""
    keyword: str
    args: str
    line: int
    end_line: int


@dataclass(frozen=True)
class FromLine:
    """A parsed `FROM [--platform=P] image[:tag] [AS stage]`."""
    image: str
    platform: Optional[str]
    stage: Optional[str]
    line: int


@dataclass
class PipInstall:
    """One `pip install ...` command: its requirement strings, `-r` files, index options and cache flag."""
    line: int
    specs: list = field(default_factory=list)
    files: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    editable: list = field(default_factory=list)
    index_options: list = field(default_factory=list)   # [(flag, value)]
    no_cache_dir: bool = False
    via_uv: bool = False
    exe: str = "pip"   # the word that started it; a path (/opt/poetry/bin/pip) means a tool's own environment


@dataclass(frozen=True)
class CopyOp:
    """A COPY or ADD: its sources, destination and whether it copies from another build stage."""
    keyword: str
    sources: tuple
    dest: str
    from_stage: bool
    line: int


def parse(text: str) -> list:
    """The instructions of a Dockerfile, with line continuations joined and comment lines dropped."""
    escape, out, buf, start = "\\", [], [], 0
    lines = text.splitlines()
    for i, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not out and not buf:   # a parser directive may only come before the first instruction
            m = re.match(r"#\s*escape\s*=\s*(\S)", stripped, re.I)
            if m:
                escape = m.group(1)
        if stripped.startswith("#") or (not stripped and not buf):
            continue
        if not buf:
            start = i
        cont = stripped.endswith(escape)
        buf.append(stripped[:-1].rstrip() if cont else stripped)
        if not cont:
            joined = " ".join(p for p in buf if p)
            keyword, _, rest = joined.partition(" ")
            out.append(Instruction(keyword.upper(), rest.strip(), start, i))
            buf = []
    if buf:
        keyword, _, rest = " ".join(buf).partition(" ")
        out.append(Instruction(keyword.upper(), rest.strip(), start, len(lines)))
    return out


def parse_from(instr: Instruction) -> Optional[FromLine]:
    """Parse a FROM instruction; None for any other."""
    if instr.keyword != "FROM":
        return None
    parts, platform, stage = instr.args.split(), None, None
    while parts and parts[0].startswith("--"):
        flag = parts.pop(0)
        if flag.startswith("--platform="):
            platform = flag.split("=", 1)[1]
    if not parts:
        return None
    if len(parts) >= 3 and parts[1].upper() == "AS":
        stage = parts[2]
    return FromLine(parts[0], platform, stage, instr.line)


def froms(instructions: list) -> list:
    return [f for f in (parse_from(i) for i in instructions) if f]


def final_stage(instructions: list) -> list:
    """The instructions from the last FROM on (the image that is shipped)."""
    last = max((n for n, i in enumerate(instructions) if i.keyword == "FROM"), default=0)
    return instructions[last:]


def python_version(image: str) -> Optional[str]:
    """`python:3.11-slim` -> '3.11'; None when the image is not an official python image."""
    m = _PYTHON_IMAGE.match(image or "")
    return m.group(1) if m else None


def arg_default(instructions: list, name: str):
    """(found, default) of `ARG name[=default]`; the default has its surrounding quotes removed."""
    for i in instructions:
        if i.keyword != "ARG":
            continue
        for part in _split(i.args):
            key, eq, value = part.partition("=")
            if key == name:
                return True, (value if eq else None)
    return False, None


def _split(text: str) -> list:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def commands(run_args: str) -> list:
    """The shell commands of a RUN's text, split at `&&`, `||`, `;` and `|`. Each is a list of words."""
    if run_args.startswith("["):
        return [[]]   # exec form: nothing the doctor reads
    try:
        lex = shlex.shlex(run_args, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        words = run_args.split()
    cmds, cur = [], []
    for w in words:
        if w in _SHELL_JOINERS or (w and set(w) <= set("&|;")):
            cmds.append(cur)
            cur = []
        else:
            cur.append(w)
    cmds.append(cur)
    return [c for c in cmds if c]


def _pip_args(cmd: list) -> Optional[tuple]:
    """(args after `install`, via_uv, the word that started pip) when `cmd` is a pip install, else None."""
    names = [w.rsplit("/", 1)[-1] for w in cmd]
    for n, w in enumerate(names):
        if w in ("pip", "pip3") or (w.startswith("pip3.") and w[5:].isdigit()):
            if n + 1 < len(cmd) and cmd[n + 1] == "install":
                return cmd[n + 2:], (n > 0 and names[n - 1] == "uv"), cmd[n]
        if w == "-m" and n + 2 < len(cmd) and cmd[n + 1] == "pip" and cmd[n + 2] == "install":
            return cmd[n + 3:], False, cmd[n - 1] if n else "python"
    return None


def pip_installs(instructions: list) -> list:
    """Every `pip install` (also `python -m pip install`, `uv pip install`) of the RUN instructions."""
    found = []
    for instr in instructions:
        if instr.keyword != "RUN":
            continue
        for cmd in commands(instr.args):
            got = _pip_args(cmd)
            if got is not None:
                found.append(_read_pip(got[0], instr.line, got[1], got[2]))
    return found


def _read_pip(args: list, line: int, via_uv: bool, exe: str) -> PipInstall:
    pip, skip = PipInstall(line, via_uv=via_uv, exe=exe), None
    for n, tok in enumerate(args):
        if skip:
            skip(tok)
            skip = None
            continue
        flag, eq, value = tok.partition("=")
        if flag == "--no-cache-dir":
            pip.no_cache_dir = True
        elif flag in PIP_VALUE_OPTIONS:
            target = _option_target(pip, flag)
            if eq:
                target(value)
            else:
                skip = target
        elif tok.startswith("-"):
            continue
        else:
            pip.specs.append(tok)
    return pip


def _option_target(pip: PipInstall, flag: str):
    if flag in ("-r", "--requirement"):
        return pip.files.append
    if flag in ("-c", "--constraint"):
        return pip.constraints.append
    if flag in ("-e", "--editable"):
        return pip.editable.append
    if flag in ("-i", "--index-url", "--extra-index-url", "-f", "--find-links"):
        return lambda v, f=flag: pip.index_options.append((f, v))
    return lambda v: None


def copy_ops(instructions: list) -> list:
    """Every COPY and ADD, with `--from=` copies marked (their sources are not in the build context)."""
    ops = []
    for i in instructions:
        if i.keyword not in ("COPY", "ADD"):
            continue
        if i.args.startswith("["):
            try:
                import json
                parts, from_stage = [str(p) for p in json.loads(i.args)], False
            except ValueError:
                continue
        else:
            parts, from_stage = _split(i.args), False
            while parts and parts[0].startswith("--"):
                from_stage |= parts.pop(0).startswith("--from=")
        if len(parts) >= 2:
            ops.append(CopyOp(i.keyword, tuple(parts[:-1]), parts[-1], from_stage, i.line))
    return ops


def uses_poetry(instructions: list) -> bool:
    """True when a RUN calls `poetry export` or `poetry install` (the dependencies live in pyproject/poetry.lock)."""
    for i in instructions:
        if i.keyword == "RUN":
            for cmd in commands(i.args):
                names = [w.rsplit("/", 1)[-1] for w in cmd]
                if "poetry" in names and ("install" in names or "export" in names):
                    return True
    return False


def env_names(instructions: list) -> dict:
    """The `ENV name=value` pairs (best effort; used for PIP_NO_CACHE_DIR)."""
    out = {}
    for i in instructions:
        if i.keyword == "ENV":
            for part in _split(i.args):
                key, eq, value = part.partition("=")
                if eq:
                    out[key] = value
    return out


def entrypoint_words(instructions: list) -> Optional[list]:
    """The words of the last ENTRYPOINT (exec or shell form), or None when there is none."""
    last = [i for i in instructions if i.keyword == "ENTRYPOINT"]
    if not last:
        return None
    args = last[-1].args
    if args.startswith("["):
        try:
            import json
            return [str(w) for w in json.loads(args)]
        except ValueError:
            return None
    return _split(args)
