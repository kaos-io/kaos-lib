"""Find and check the container engine a build would use (PRD-CONSOLE-1682 F-32, D-17).

Why: a build on the client's machine works only if an engine is there and healthy. This module detects Docker (Engine,
Desktop, Colima and Rancher Desktop all answer to the `docker` command) and Podman, then verifies the one it will use:
the daemon answers, a tiny test build succeeds, there is disk space, and the architecture works (an Apple Silicon Mac
building amd64 needs emulation). It only reads and runs the engine's own commands; it never installs or configures an
engine (CON-17). Every program is started through `proc`, which a test replaces with a stub engine.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import engine_errors, proc
from .constants import ENGINE_TIMEOUT_SECONDS, MIN_FREE_GB, TEST_BUILD_TIMEOUT_SECONDS, TEST_IMAGE_TAG

KINDS = ("docker", "podman")
ARCH_NAMES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
QEMU_BINFMT = {"amd64": "qemu-x86_64", "arm64": "qemu-aarch64"}


@dataclass
class Engine:
    """An engine that answered: which command, what it calls itself, its architecture and where it keeps images."""
    kind: str                 # docker | podman
    exe: str
    flavour: str = ""         # Docker Engine | Docker Desktop | Colima | Rancher Desktop | Podman
    version: str = ""
    arch: str = ""            # amd64 | arm64: the engine's own CPU (the VM's, for Desktop and Colima)
    storage: str = ""         # the folder images live in, when this machine can see it

    @property
    def label(self) -> str:
        return f"{self.flavour or self.kind} {self.version}".strip()


@dataclass
class Problem:
    """Why an engine cannot be used, in plain words, with the fix."""
    key: str
    message: str
    fix: str
    detail: str = ""


@dataclass
class Verification:
    """The outcome of checking one candidate engine."""
    engine: Optional[Engine] = None
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    free_gb: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.engine is not None and not self.problems


def detect(which: Optional[Callable] = None) -> list:
    """The engine commands present on PATH, docker first. (Colima and Rancher Desktop are reached through `docker`.)"""
    which = which or shutil.which        # looked up at call time, so a test can replace it
    return [(kind, which(kind)) for kind in KINDS if which(kind)]


def _problem_from(output: str, fallback_key: str, fallback_message: str, fallback_fix: str) -> Problem:
    t = engine_errors.translate(output)
    if t:
        return Problem(t.key, t.message, t.fix, output[-600:])
    return Problem(fallback_key, fallback_message, fallback_fix, output[-600:])


def _flavour(kind: str, info: dict, environ: dict, context: str) -> str:
    if kind == "podman":
        return "Podman"
    host = environ.get("DOCKER_HOST", "")
    blob = " ".join([str(info.get("OperatingSystem", "")), str(info.get("Name", "")), context, host]).lower()
    if "docker desktop" in blob or "desktop-linux" in blob:
        return "Docker Desktop"
    if "colima" in blob:
        return "Colima"
    if "rancher" in blob or "/.rd/" in blob:
        return "Rancher Desktop"
    return "Docker Engine"


def _read_info(kind: str, exe: str, run: Callable) -> tuple:
    """(info dict, raw output, ok) from the engine's `info`."""
    argv = [exe, "info", "--format", "json" if kind == "podman" else "{{json .}}"]
    done = run(argv, timeout=ENGINE_TIMEOUT_SECONDS)
    if not done.ok:
        return {}, done.text, False
    try:
        return json.loads(done.stdout), done.text, True
    except ValueError:
        return {}, done.text or "the engine's info output could not be read", False


def _facts(kind: str, info: dict) -> tuple:
    """(version, arch, storage) from a docker or podman info document."""
    if kind == "podman":
        host, ver, store = info.get("host") or {}, info.get("version") or {}, info.get("store") or {}
        return str(ver.get("Version", "")), ARCH_NAMES.get(str(host.get("arch", "")).lower(), ""), str(store.get("graphRoot", ""))
    return (str(info.get("ServerVersion", "")), ARCH_NAMES.get(str(info.get("Architecture", "")).lower(), ""),
            str(info.get("DockerRootDir", "")))


def _check_disk(v: Verification, storage: str, disk_free: Callable) -> None:
    for candidate in (storage, str(pathlib.Path.home())):
        try:
            if candidate and pathlib.Path(candidate).exists():
                v.free_gb = disk_free(candidate) / 1024 ** 3
                break
        except OSError:
            continue
    if v.free_gb is None:
        v.notes.append("free disk space could not be read: the engine keeps its images inside a virtual machine")
    elif v.free_gb < MIN_FREE_GB:
        t = engine_errors.translate("no space left on device")
        v.problems.append(Problem(t.key, f"{t.message} Only {v.free_gb:.1f} GB are free; a build needs about "
                                         f"{MIN_FREE_GB} GB.", t.fix))


def _test_build(engine: Engine, run: Callable) -> Optional[Problem]:
    """A tiny build (`FROM scratch`: no download) proves the build path works; its image is removed again."""
    with tempfile.TemporaryDirectory() as ctx:
        (pathlib.Path(ctx) / "Dockerfile").write_text("FROM scratch\nLABEL io.kaos.check=1\n", encoding="utf-8")
        done = run([engine.exe, "build", "-q", "-t", TEST_IMAGE_TAG, ctx], timeout=TEST_BUILD_TIMEOUT_SECONDS)
    run([engine.exe, "rmi", "-f", TEST_IMAGE_TAG], timeout=ENGINE_TIMEOUT_SECONDS)
    if done.ok:
        return None
    return _problem_from(done.text, "test_build_failed", "A small test build failed.",
                         "Run `docker build` (or `podman build`) on any small Dockerfile to see the engine's own error.")


def _check_arch(v: Verification, engine: Engine, target: str, run: Callable, binfmt_exists: Callable) -> None:
    if not engine.arch or engine.arch == target:
        return
    slower = f"This machine builds for {engine.arch}; the platform runs {target} images, so the build is emulated and slower."
    if engine.kind == "docker":
        listed = run([engine.exe, "buildx", "ls"], timeout=ENGINE_TIMEOUT_SECONDS)
        ok = listed.ok and f"linux/{target}" in listed.text
    else:
        ok = binfmt_exists(QEMU_BINFMT.get(target, "")) if sys.platform.startswith("linux") else None
    if ok is False:
        t = engine_errors.translate("exec format error")
        v.problems.append(Problem(t.key, f"{t.message} {slower} Emulation for {target} is not set up.", t.fix))
    else:
        v.notes.append(slower + ("" if ok else " Emulation could not be checked here; if the build fails with an "
                                              "`exec format error`, enable it."))


def _binfmt_exists(name: str) -> bool:
    return bool(name) and os.path.exists(f"/proc/sys/fs/binfmt_misc/{name}")


def verify(kind: str, exe: str, target_arch: str, run: Optional[Callable] = None, environ: Optional[dict] = None,
           disk_free: Callable = lambda p: shutil.disk_usage(p).free, binfmt_exists: Callable = _binfmt_exists) -> Verification:
    """Check one engine: daemon, disk, architecture and a test build. Problems carry a plain message and a fix."""
    v, environ = Verification(), environ if environ is not None else dict(os.environ)
    run = run or proc.run       # looked up at call time, so a test can replace proc.run
    info, output, ok = _read_info(kind, exe, run)
    if not ok:
        v.problems.append(_problem_from(output, "daemon_not_running", engine_errors.translate("Cannot connect to the Docker daemon").message,
                                        engine_errors.translate("Cannot connect to the Docker daemon").fix))
        return v
    context = run([exe, "context", "show"], timeout=ENGINE_TIMEOUT_SECONDS).stdout.strip() if kind == "docker" else ""
    version, arch, storage = _facts(kind, info)
    v.engine = Engine(kind, exe, _flavour(kind, info, environ, context), version, arch, storage)
    _check_disk(v, storage, disk_free)
    _check_arch(v, v.engine, target_arch, run, binfmt_exists)
    failed = _test_build(v.engine, run)
    if failed:
        v.problems.append(failed)
    return v


def first_usable(candidates: list, target_arch: str, **kw) -> tuple:
    """(the first verification that is ok or None, every verification made). Stops at the first engine that works."""
    seen = []
    for kind, exe in candidates:
        v = verify(kind, exe, target_arch, **kw)
        seen.append(v)
        if v.ok:
            return v, seen
    return None, seen
