"""The Dockerfile doctor (L-D01 .. L-D08, PRD-CONSOLE-1682 D-19): static checks of each step's Dockerfile.

Why: a Dockerfile problem otherwise shows up minutes into a build on the platform. These rules sit in the same engine as
the pipeline rules, so the pull-request check, `kaosctl lint`, `kaosctl build` and the editor print the same findings.
Static only: a Dockerfile is parsed, never built, and the step's Python files are parsed, never imported. A step
without a Dockerfile is not judged here (the platform reports that itself).
"""
from __future__ import annotations

import ast
import pathlib
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import dockerfile as df
from .constants import (BUILD_ARCH_DEFAULT, COMPOSE_STEP, CUDA_IMAGE_WORDS, CUDA_PACKAGE_PATTERN, DATA_FOLDER_NAMES,
                        ENTRY_MODULE, KAOS_LIB_ARG, LARGE_COPY_BYTES, MAX_FILE_BYTES, MAX_STEP_BYTES, MAX_STEP_FILES)
from .model import ERROR, INFO, WARNING, Span
from .pipeline_reader import UNKNOWN
from .project_reader import step_folder
from .registry import Hit, LintContext, rule
from .source import TooLarge, inside, parse_python, read_text

_CUDA_PACKAGES = re.compile(CUDA_PACKAGE_PATTERN, re.I)
_DEPENDENCY_FILES = ("pyproject.toml", "requirements.txt", "requirements-cuda.txt", "requirements-gpu.txt")


@dataclass
class DockerStep:
    """A step whose Dockerfile the doctor reads: where it is, what context CI builds it with, what it holds."""
    name: str
    folder: str                      # steps/<name>
    dockerfile: str                  # steps/<name>/Dockerfile
    context: str                     # "" = the repository root, else the step folder
    source: object                   # the SourceFile of the Dockerfile
    instructions: list
    gpu: bool = False
    _imports: Optional[bool] = field(default=None, repr=False)

    def span(self, line: int, end_line: Optional[int] = None) -> Span:
        text = self.source.lines[(end_line or line) - 1] if 0 < (end_line or line) <= len(self.source.lines) else ""
        return Span(line, 1, end_line or line, len(text) + 1)

    @property
    def first_line(self) -> int:
        return self.instructions[0].line if self.instructions else 1


def _targets(ctx: LintContext) -> list:
    """The Dockerfiles of the pipeline's steps (and the implicit compose-and-validate step when it has one)."""
    out, seen = [], set()
    pairs = [(s.name, s.is_gpu is True) for s in ctx.pipeline.steps if s.name is not UNKNOWN]
    pairs.append((COMPOSE_STEP, False))
    for name, gpu in pairs:
        if name in seen:
            continue
        seen.add(name)
        folder = step_folder(name)
        rel = f"{folder}/Dockerfile"
        try:
            src = read_text(ctx.root, ctx.root / rel, rel)
        except TooLarge:
            continue
        if src is not None:
            out.append(DockerStep(name, folder, rel, "" if name == COMPOSE_STEP else folder, src,
                                  df.parse(src.text), gpu))
    return out


def _imports_kaos_lib(ctx: LintContext, step: DockerStep) -> bool:
    """True when a Python file of the step folder imports kaos_lib (parsed, never run; bounded like the linter)."""
    if step._imports is None:
        step._imports = False
        budget, count = MAX_STEP_BYTES, 0
        for path in sorted((ctx.root / step.folder).rglob("*.py")):
            count += 1
            if count > MAX_STEP_FILES or not inside(ctx.root, path):
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES or size > budget:
                continue
            budget -= size
            src = read_text(ctx.root, path)
            if src is not None and parse_python(src) is not None and _has_import(src.tree):
                step._imports = True
                break
    return step._imports


def _has_import(tree: ast.AST) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.Import) and any(a.name.split(".")[0] == "kaos_lib" for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "kaos_lib" and not n.level:
            return True
    return False


def _installs_kaos_lib_by_pin(step: DockerStep) -> Optional[int]:
    """The line of a `pip install` that names kaos-lib directly (a pin the platform cannot move), else None."""
    for pip in df.pip_installs(step.instructions):
        if any(re.match(r"kaos[-_]lib\b", s, re.I) for s in pip.specs):
            return pip.line
    return None


@rule("L-D01", "MissingKaosLibArg", ERROR,
      'Add `ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel]==<the version you tested>"` before the install and install '
      'with `RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"`.')
def missing_kaos_lib_arg(ctx: LintContext) -> Iterable[Hit]:
    """A step that uses kaos-lib has no `ARG KAOS_LIB_PACKAGE`, so the platform cannot choose its kaos-lib version."""
    for step in _targets(ctx):
        declared, _ = df.arg_default(step.instructions, KAOS_LIB_ARG)
        pinned = _installs_kaos_lib_by_pin(step)
        if declared or not (_imports_kaos_lib(ctx, step) or pinned):
            continue
        line = pinned or step.first_line
        yield Hit(step.dockerfile, step.span(line),
                  f"The Dockerfile of step '{step.name}' does not declare ARG {KAOS_LIB_ARG}, so the platform's build "
                  f"cannot pass the kaos-lib version it chose or add the io.kaos.lib label to the image.")


@rule("L-D02", "KaosLibNotInstalled", ERROR,
      'Install it from the argument: `RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"`.')
def kaos_lib_not_installed(ctx: LintContext) -> Iterable[Hit]:
    """The step imports kaos_lib and declares the ARG, but no pip install uses it."""
    for step in _targets(ctx):
        declared, _ = df.arg_default(step.instructions, KAOS_LIB_ARG)
        if not declared or not _imports_kaos_lib(ctx, step):
            continue
        used = any(KAOS_LIB_ARG in " ".join(p.specs) for p in df.pip_installs(step.instructions))
        if not used:
            arg = next(i for i in step.instructions if i.keyword == "ARG" and KAOS_LIB_ARG in i.args)
            yield Hit(step.dockerfile, step.span(arg.line, arg.end_line),
                      f"Step '{step.name}' imports kaos_lib, but no `pip install` in its Dockerfile installs "
                      f"${{{KAOS_LIB_ARG}}}, so the image would fail with ModuleNotFoundError when it starts.")


@rule("L-D03", "WrongArchitecture", ERROR,
      "Remove `--platform=` from FROM (the build picks the platform's architecture), or use "
      "`--platform=$BUILDPLATFORM`.")
def wrong_architecture(ctx: LintContext) -> Iterable[Hit]:
    """A FROM names a platform other than the one the project's images are built for (amd64 unless set otherwise)."""
    for step in _targets(ctx):
        for f in df.froms(step.instructions):
            plat = f.platform or ""
            if plat and "$" not in plat and not plat.endswith(f"/{BUILD_ARCH_DEFAULT}") and plat != BUILD_ARCH_DEFAULT:
                yield Hit(step.dockerfile, step.span(f.line),
                          f"FROM --platform={plat} in step '{step.name}': the platform builds step images for "
                          f"linux/{BUILD_ARCH_DEFAULT}, so the nodes could not run this image.")


def _outside(ctx: LintContext, step: DockerStep, source: str) -> Optional[str]:
    """Why a COPY source is not usable in the build context, or None."""
    if re.match(r"^(/|[A-Za-z]:[\\/])", source):
        return "is an absolute path (a build can only read files inside its context)"
    parts = pathlib.PurePosixPath(source.replace("\\", "/")).parts
    depth = 0
    for p in parts:
        depth += -1 if p == ".." else 0 if p == "." else 1
        if depth < 0:
            return "is outside the build context"
    if any(c in source for c in "*?[$") or "://" in source:
        return None
    base = ctx.root / step.context if step.context else ctx.root
    if not (base / source).exists():
        return "does not exist in the build context"
    return None


@rule("L-D04", "CopyOutsideContext", ERROR,
      "Copy only files inside the step's folder (the build context). Files of the repository root are available "
      "to the compose-and-validate step only.")
def copy_outside_context(ctx: LintContext) -> Iterable[Hit]:
    """A COPY or ADD source the platform's build cannot read: absolute, above the context, or missing."""
    for step in _targets(ctx):
        where = "the repository root" if not step.context else f"the step folder {step.folder}/"
        for op in df.copy_ops(step.instructions):
            if op.from_stage:
                continue
            for src in op.sources:
                why = _outside(ctx, step, src)
                if why:
                    yield Hit(step.dockerfile, step.span(op.line), f"{op.keyword} {src}: the source {why}. "
                              f"The platform builds step '{step.name}' with {where} as the context.")


def _is_entrypoint(words: list) -> bool:
    return [w.rsplit("/", 1)[-1] for w in words[:1]] in (["python"], ["python3"]) and words[1:3] == ["-m", ENTRY_MODULE]


@rule("L-D05", "StepContract", ERROR,
      "Put the step's code in steps/<name>/app/entry.py and start it with "
      '`ENTRYPOINT ["python", "-m", "app.entry"]`.')
def step_contract(ctx: LintContext) -> Iterable[Hit]:
    """`app/entry.py` is missing (error) or the Dockerfile does not start `python -m app.entry` (warning)."""
    for step in _targets(ctx):
        if step.name == COMPOSE_STEP:
            continue
        if not (ctx.root / step.folder / "app" / "entry.py").is_file():
            yield Hit(step.dockerfile, step.span(step.first_line),
                      f"Step '{step.name}' has no {step.folder}/app/entry.py: the platform runs "
                      f"`python -m {ENTRY_MODULE}` in the image.")
        words = df.entrypoint_words(step.instructions)
        if words is None or not _is_entrypoint(words):
            last = [i for i in step.instructions if i.keyword == "ENTRYPOINT"]
            line = last[-1].line if last else step.instructions[-1].line
            yield Hit(step.dockerfile, step.span(line),
                      f"The Dockerfile of step '{step.name}' does not end with ENTRYPOINT "
                      f'["python", "-m", "{ENTRY_MODULE}"]. The platform sets the command itself, so this only '
                      f"matters when you run the image by hand.", level=WARNING)


def _dir_bytes(path: pathlib.Path, limit: int) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
        if total > limit:
            break
    return total


@rule("L-D06", "HugeLayers", WARNING,
      "Copy only what the step needs, add --no-cache-dir to pip, and remove /var/lib/apt/lists in the same RUN "
      "as apt-get install.")
def huge_layers(ctx: LintContext) -> Iterable[Hit]:
    """Things that make the image far larger than it needs to be."""
    for step in _targets(ctx):
        env = df.env_names(step.instructions)
        for op in df.copy_ops(step.instructions):
            for src in ([] if op.from_stage else op.sources):
                yield from _copy_size_hit(ctx, step, op, src)
        if env.get("PIP_NO_CACHE_DIR", "").lower() not in ("1", "true", "on", "yes"):
            for pip in df.pip_installs(step.instructions):
                if not pip.no_cache_dir and not pip.via_uv:
                    yield Hit(step.dockerfile, step.span(pip.line), "`pip install` without --no-cache-dir leaves pip's "
                              "download cache in the image layer.")
        for i in step.instructions:
            if i.keyword == "RUN" and re.search(r"apt(-get)?\s+install", i.args) and "/var/lib/apt/lists" not in i.args:
                yield Hit(step.dockerfile, step.span(i.line, i.end_line),
                          "`apt-get install` without `rm -rf /var/lib/apt/lists/*` in the same RUN keeps the package "
                          "lists in the layer.")


def _copy_size_hit(ctx: LintContext, step: DockerStep, op: df.CopyOp, src: str) -> Iterable[Hit]:
    norm = src.rstrip("/")
    if norm in (".", "") and not step.context:
        yield Hit(step.dockerfile, step.span(op.line), "`COPY . .` copies the whole repository root (config, data, "
                  "git history) into the image; copy the folders the step needs.")
        return
    name = pathlib.PurePosixPath(norm).name
    base = (ctx.root / step.context if step.context else ctx.root) / src
    if name in DATA_FOLDER_NAMES:
        yield Hit(step.dockerfile, step.span(op.line), f"`{op.keyword} {src}` copies a folder that usually holds data "
                  f"or results; read data at run time (kaos_lib.datasets) instead of baking it into the image.")
    elif "*" not in src and "$" not in src and base.is_dir() and _dir_bytes(base, LARGE_COPY_BYTES) > LARGE_COPY_BYTES:
        yield Hit(step.dockerfile, step.span(op.line), f"`{op.keyword} {src}` copies more than "
                  f"{LARGE_COPY_BYTES // (1024 * 1024)} MiB into one layer.")


@rule("L-D07", "RootUser", INFO,
      "Add `RUN useradd --create-home app` and `USER app` before the ENTRYPOINT if your step does not need root.")
def root_user(ctx: LintContext) -> Iterable[Hit]:
    """The image's last stage never sets USER, so the step runs as root. Info: the platform's requirement is not verified."""
    for step in _targets(ctx):
        stage = df.final_stage(step.instructions)
        if stage and not any(i.keyword == "USER" for i in stage):
            yield Hit(step.dockerfile, step.span(stage[0].line),
                      f"The image of step '{step.name}' runs as root (no USER). The platform does not require a "
                      f"non-root user today; a restricted cluster may.")


def _dependency_text(ctx: LintContext, step: DockerStep) -> str:
    """The Dockerfile's pip lines plus the step's dependency files, as one lower-case text for a keyword search."""
    chunks = [" ".join(s for p in df.pip_installs(step.instructions) for s in p.specs)]
    for name in _DEPENDENCY_FILES:
        try:
            src = read_text(ctx.root, ctx.root / step.folder / name)
        except TooLarge:
            continue
        chunks.append(src.text if src else "")
    return " ".join(chunks).lower()


@rule("L-D08", "NoCudaForGpuStep", WARNING,
      "Use a CUDA-enabled base image, or depend on a library whose wheel bundles CUDA (for example torch), so "
      "the step can use its GPU. This check is a heuristic: it searches the image and the dependency files.")
def no_cuda_for_gpu_step(ctx: LintContext) -> Iterable[Hit]:
    """A gpu=True step whose image has no sign of CUDA support."""
    for step in _targets(ctx):
        if not step.gpu:
            continue
        images = " ".join(f.image for f in df.froms(step.instructions)).lower()
        if any(w in images for w in CUDA_IMAGE_WORDS) or _CUDA_PACKAGES.search(_dependency_text(ctx, step)):
            continue
        yield Hit(step.dockerfile, step.span(step.first_line),
                  f"Step '{step.name}' asks for a GPU (gpu=True), but its image shows no CUDA support: the base "
                  f"image is not a CUDA image and no GPU library (torch, tensorflow, jax ...) is installed.")
