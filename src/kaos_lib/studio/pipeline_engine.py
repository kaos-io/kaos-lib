"""The platform's pipeline engine on this machine: the same release the platform's CI renders and composes with.

Why: an app holds `pipeline.py`, `config/` and `steps/`, and no copy of the engine. To render the pipeline or compose
the parameters locally exactly as CI does, kaosctl fetches the engine release the platform pinned for the app, checks
its SHA-256, and installs it into `.kaos/engine/.venv` inside the repository (git-ignored). Nothing is installed
outside the repository and nothing is run from the app's own folders as engine code.

Which engine, first that exists: `--engine-wheel URL#sha256=<64 hex>`, `$KAOS_ENGINE_WHEEL` (same form), the
`engine:` block of the platform's pipeline-context file (`--context`): `wheel` and `wheelSha256`, then the `engine`
block of this kaos-lib release's own `_release.json` (`wheel`, `sha256`, `version`) when the release names one. A wheel
without a SHA-256 is refused: the checksum is what makes a download the platform's release.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests
import yaml

from ..errors import KaosLibError
from . import envallow, proc, pyenv
from .constants import VENV_DIR

ENGINE_DIR = ".kaos/engine"            # in the repository, git-ignored by itself
WHEEL_ENV = "KAOS_ENGINE_WHEEL"
PROFILE_ENV = "KUBECORE_SCHEMA_PROFILE"
PROFILES = ("hera", "yolo")
MIN_PYTHON = (3, 11)                   # the engine's requires-python
MAX_WHEEL_BYTES = 50 * 1024 * 1024
TIMEOUT = 120
RAW_TEMPLATE = "out/raw-workflow-template.yaml"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_WHEEL_RE = re.compile(r"^[A-Za-z0-9_.+-]+\.whl$")

HOW_TO_PIN = ("This kaos-lib release names no engine of its own. Ask your platform team for the engine release and give it: "
              "--engine-wheel 'URL#sha256=<checksum>' or $%s (or --context <pipeline-context.yaml>, the platform's file "
              "for your app, which has an `engine:` block). Without it, the check of your pull request renders the "
              "pipeline for you." % WHEEL_ENV)


@dataclass(frozen=True)
class EnginePin:
    """One engine release: where its wheel is, the checksum it must have, and who chose it."""
    url: str
    sha256: str
    source: str
    version: str = ""

    @property
    def wheel_name(self) -> str:
        return pathlib.PurePosixPath(urlsplit(self.url).path).name


def _pin_from_text(text: str, source: str) -> EnginePin:
    url, _, fragment = text.strip().partition("#")
    sha = fragment[len("sha256="):] if fragment.startswith("sha256=") else ""
    return _checked(url, sha, source, "")


def _checked(url: str, sha: str, source: str, version: str) -> EnginePin:
    url, sha = (url or "").strip(), (sha or "").strip().lower()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise KaosLibError(f"{source}: the engine wheel must be an https URL, got {url!r}.")
    pin = EnginePin(url, sha, source, str(version or ""))
    if not _WHEEL_RE.match(pin.wheel_name):
        raise KaosLibError(f"{source}: {url!r} does not name a wheel file (.whl).")
    if not _SHA_RE.match(sha):
        raise KaosLibError(f"{source}: the engine wheel needs its SHA-256 (64 hex characters), got {sha!r}. "
                           "Without it the download cannot be checked.")
    return pin


def _context_pin(path: Optional[str]) -> Optional[EnginePin]:
    if not path:
        return None
    try:
        doc = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise KaosLibError(f"cannot read the context file {path}: {exc}") from None
    block = doc.get("engine") if isinstance(doc, dict) else None
    if not isinstance(block, dict) or not block.get("wheel"):
        return None
    wheel = str(block["wheel"])
    if "#" in wheel and not block.get("wheelSha256"):
        return _pin_from_text(wheel, f"the context file {path}")
    return _checked(wheel.partition("#")[0], str(block.get("wheelSha256") or ""), f"the context file {path}",
                    str(block.get("version") or ""))


def _release_pin() -> Optional[EnginePin]:
    """The engine this kaos-lib release names in its own `_release.json` (`engine`: `wheel`, `sha256`, `version`), or
    None when it names none (the case until the release process fills it)."""
    from .. import support
    block = (support.packaged() or {}).get("engine")
    if not isinstance(block, dict) or not block.get("wheel"):
        return None
    return _checked(str(block["wheel"]), str(block.get("sha256") or ""), "this kaos-lib release",
                    str(block.get("version") or ""))


def resolve_pin(flag: Optional[str] = None, context: Optional[str] = None, environ=None) -> EnginePin:
    """Choose the engine release (see the module text for the order); KaosLibError says how to give one."""
    environ = os.environ if environ is None else environ
    if flag:
        return _pin_from_text(flag, "--engine-wheel")
    if environ.get(WHEEL_ENV):
        return _pin_from_text(environ[WHEEL_ENV], f"${WHEEL_ENV}")
    found = _context_pin(context)
    if found:
        return found
    if not context and (named := _release_pin()):
        return named
    if context:
        raise KaosLibError(f"the context file {context} has no `engine:` block with a wheel: the platform has not "
                           "pinned an engine for this app yet. " + HOW_TO_PIN)
    raise KaosLibError("no pipeline engine was given. " + HOW_TO_PIN)


def engine_home(root: pathlib.Path) -> pathlib.Path:
    """`.kaos/engine` of the repository, with a `.gitignore` of `*` so nothing in it is ever committed."""
    home = root / ENGINE_DIR
    home.mkdir(parents=True, exist_ok=True)
    ignore = home / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    return home


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(pin: EnginePin, home: pathlib.Path, get: Optional[Callable] = None) -> pathlib.Path:
    """The pinned wheel on disk, downloaded once and checked every time. A wrong checksum is never kept or used."""
    wheel = home / "wheels" / pin.sha256 / pin.wheel_name
    if wheel.is_file():
        if _sha256(wheel) == pin.sha256:
            return wheel
        wheel.unlink()                              # altered after the download: fetch it again
    wheel.parent.mkdir(parents=True, exist_ok=True)
    part = wheel.with_name(wheel.name + ".part")
    try:
        # Redirects are followed (the package registry redirects to its storage): the SHA-256 below is what makes
        # the bytes the platform's release, wherever they were served from.
        resp = (get or requests.get)(pin.url, timeout=TIMEOUT, stream=True)
        if resp.status_code != 200:
            raise KaosLibError(f"cannot download the pipeline engine from {pin.url}: HTTP {resp.status_code} "
                               f"({pin.source}).")
        size = 0
        with open(part, "wb") as fh:
            for chunk in resp.iter_content(1 << 16):
                size += len(chunk)
                if size > MAX_WHEEL_BYTES:
                    raise KaosLibError(f"the pipeline engine at {pin.url} is larger than "
                                       f"{MAX_WHEEL_BYTES // (1024 * 1024)} MB: not an engine wheel.")
                fh.write(chunk)
        got = _sha256(part)
        if got != pin.sha256:
            raise KaosLibError(f"the pipeline engine downloaded from {pin.url} has SHA-256 {got}, but {pin.source} "
                               f"says {pin.sha256}. Nothing was installed.")
        os.replace(part, wheel)
    except requests.RequestException as exc:
        raise KaosLibError(f"cannot download the pipeline engine from {pin.url}: {type(exc).__name__}. "
                           "Check your connection, then try again.") from None
    finally:
        if part.exists():
            part.unlink()
    return wheel


def find_python(uv: Optional[str]) -> str:
    """A Python the engine runs on (3.11 or newer): this one, else one the machine already has."""
    if sys.version_info[:2] >= MIN_PYTHON:
        return sys.executable
    for minor in ("3.12", "3.13", "3.11"):
        python, note = pyenv.find_python(minor, uv)
        if not note:
            return python
    raise KaosLibError("the pipeline engine needs Python 3.11 or newer and this machine has none. Install one "
                       "yourself (https://www.python.org/downloads/ or `uv python install 3.12`) and run the command again.")


def ensure(root: pathlib.Path, pin: EnginePin, uv: Optional[str] = None, get: Optional[Callable] = None,
           say: Callable = print) -> pathlib.Path:
    """The Python of `.kaos/engine/.venv`, holding exactly the pinned engine (set up or updated when it does not)."""
    home = engine_home(root)
    wheel = fetch(pin, home, get)
    outcome = pyenv.ensure_env(home / VENV_DIR, f"{wheel}\n", find_python(uv), uv)
    if outcome.status == "failed":
        raise KaosLibError(f"cannot set up the pipeline engine in {home / VENV_DIR}: {outcome.detail}\n"
                           + (outcome.output or "")[-1500:])
    if outcome.status != "up-to-date":
        say(f"pipeline engine {pin.version or pin.wheel_name} ready in {ENGINE_DIR}/{VENV_DIR} (from {pin.source})")
    return pyenv.venv_python(home / VENV_DIR)


def profile_of(root: pathlib.Path, flag: Optional[str] = None, environ=None) -> str:
    """The engine's config-schema profile for this app: `--profile`, `$KUBECORE_SCHEMA_PROFILE`, else `yolo` for an
    app whose config has a `quantization` section (the yolo template's), else `hera`."""
    environ = os.environ if environ is None else environ
    chosen = flag or environ.get(PROFILE_ENV)
    if chosen:
        if chosen not in PROFILES:
            raise KaosLibError(f"unknown profile {chosen!r}: use one of {', '.join(PROFILES)}.")
        return chosen
    config = root / "config"
    return "yolo" if (config / "quantization.yaml").is_file() or (config / "quantization").is_dir() else "hera"


def _env(root: pathlib.Path, profile: str) -> dict:
    return {**envallow.allowed(os.environ), PROFILE_ENV: profile, "KUBECORE_CONFIG_DIR": str(root / "config"),
            "PYTHONUNBUFFERED": "1"}


def render_command(py: pathlib.Path, profile: str) -> list:
    return [str(py), "-I", "-m", "kaos_engine.render", "pipeline.py", "--repo", ".", "--profile", profile]


# The engine's compose, started with the engine first on the path and the app's folders never on it (-I).
_COMPOSE = ("import os, sys; import kaos_pipeline_engine as e; sys.path.insert(0, os.path.dirname(e.__file__)); "
            "from kubecore import compose; compose.main(sys.argv[1:])")


def compose_command(py: pathlib.Path, overrides: list, output: pathlib.Path) -> list:
    return [str(py), "-I", "-c", _COMPOSE, *overrides, "--output", str(output)]


def render(root: pathlib.Path, py: pathlib.Path, profile: str, echo: Callable = print) -> proc.Result:
    """Render pipeline.py with the engine; the raw WorkflowTemplate lands in `out/raw-workflow-template.yaml`."""
    return proc.stream(render_command(py, profile), env=_env(root, profile), cwd=root, echo=echo)


def compose(root: pathlib.Path, py: pathlib.Path, profile: str, overrides: list, output: pathlib.Path) -> str:
    """The composed params.yaml text, composed by the engine from the app's `config/`."""
    done = proc.run(compose_command(py, overrides, output), env=_env(root, profile), cwd=root, timeout=300)
    if not done.ok:
        raise KaosLibError("composing the parameters failed:\n" + done.text[-1500:])
    return output.read_text(encoding="utf-8")


def run_render(args) -> int:
    """The `kaosctl render` command: render pipeline.py as the platform's CI does. Returns the engine's exit code."""
    from . import steps
    root = steps.repo_root(args.path)
    if not (root / "pipeline.py").is_file():
        raise KaosLibError(f"{root} has no pipeline.py.")
    pin = resolve_pin(args.engine_wheel, args.context)
    py = ensure(root, pin, pyenv.find_uv())
    profile = profile_of(root, args.profile)
    print(f"Rendering pipeline.py with the platform engine {pin.version or pin.wheel_name} (profile {profile}) ...")
    done = render(root, py, profile)
    if done.returncode:
        print(f"ERROR: the render failed (exit code {done.returncode}).", file=sys.stderr)
        return done.returncode
    print(f"Rendered: {RAW_TEMPLATE}")
    return 0
