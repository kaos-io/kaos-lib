"""Plain-language translations of the errors a container engine prints (PRD-CONSOLE-1682 F-34, section 7.3).

Why: "failed to compute cache key" tells a data scientist nothing. Each known failure of Docker, Podman, Colima or
Rancher Desktop maps to one message and one fix. The patterns are matched against the engine's own output, in order:
the first match wins, so the more specific causes come first. `tests/engine_fixtures/` holds one recorded output per
engine and cause, and the table is tested against them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Translation:
    """What went wrong in plain words and what to do about it."""
    key: str
    message: str
    fix: str


_TABLE = (
    ("permission_denied_socket",
     r"permission denied while trying to connect to the (docker|podman)|connect: permission denied|"
     r"permission denied.*(docker|podman)[./a-z]*sock|got permission denied while trying",
     Translation("permission_denied_socket", "Your user is not allowed to use the container engine.",
                 "Add your user to the engine's group (on Linux: `sudo usermod -aG docker $USER`, then log out and in) "
                 "or use a rootless engine such as Podman.")),
    ("daemon_not_running",
     r"cannot connect to the docker daemon|is the docker daemon running|docker daemon is not running|"
     r"error during connect:.*(docker_engine|pipe)|cannot connect to podman|unable to connect to podman|"
     r"podman machine .*not running|failed to connect to the docker api|error during connect|"
     r"colima is not running|dial unix .*(no such file or directory|connection refused)",
     Translation("daemon_not_running", "The container engine is installed but not running.",
                 "Start it (Docker Desktop: open the app; Colima: `colima start`; Podman on macOS or Windows: "
                 "`podman machine start`; Linux: `sudo systemctl start docker`), then run `kaosctl build` again.")),
    ("no_space",
     r"no space left on device|not enough space|disk quota exceeded|write /.*: no space",
     Translation("no_space", "The disk is full.",
                 "Free some space or remove old images (`docker system prune` or `podman system prune`), then run "
                 "`kaosctl build` again. kaosctl shows the free space it found.")),
    ("exec_format",
     r"exec format error|no matching manifest for linux/|does not match the specified platform|"
     r"image's platform \(linux/\w+\) does not match|platform .* does not match",
     Translation("exec_format", "The image's CPU architecture does not match this machine.",
                 "Enable emulation (Docker Desktop and Colima include it; on Linux install `qemu-user-static` and "
                 "`binfmt-support`), or build for this machine's architecture with `kaosctl build --arch`.")),
    ("registry_auth",
     r"pull access denied|requested access to the resource is denied|unauthorized: authentication required|"
     r"denied: requested access|insufficient_scope|unable to retrieve auth token|authentication required|"
     r"\b401 unauthorized|error: unauthorized|failed to fetch (anonymous|oauth) token|\b403 forbidden",
     Translation("registry_auth", "The engine cannot pull a base image: the registry asks you to sign in, or the image "
                 "does not exist.",
                 "Sign in to that registry (`docker login <registry>` or `podman login <registry>`), or change `FROM` "
                 "to a base image you can pull.")),
    ("network",
     r"temporary failure in name resolution|could not resolve host|name or service not known|no such host|"
     r"network is unreachable|proxyconnect|tls handshake timeout|i/o timeout|max retries exceeded|"
     r"failed to establish a new connection|connection timed out|read timed out|"
     r"certificate verify failed|x509: certificate signed by unknown authority|\b407 proxy|"
     r"could not find a version that satisfies|no matching distribution found",
     Translation("network", "The build cannot reach the package index or a registry.",
                 "Check your network and, behind a company proxy, the proxy settings of the engine and of the build "
                 "(HTTP_PROXY, HTTPS_PROXY, NO_PROXY; a company certificate may need adding to the engine).")),
    ("cache_corrupt",
     r"failed to compute cache key|failed to get digest sha256|content digest .* not found|blob sha256:.* not found|"
     r"layer does not exist|failed to prepare extraction snapshot|parent snapshot .* does not exist|"
     r"failed to register layer|digest mismatch|invalid cache|rpc error: .*snapshot",
     Translation("cache_corrupt", "The engine's layer cache is broken.",
                 "Clear the build cache (`docker builder prune` or `podman system prune --all`) and run `kaosctl build` "
                 "again.")),
)
_COMPILED = [(key, re.compile(pattern, re.I), t) for key, pattern, t in _TABLE]

NO_ENGINE_KEY = "no_usable_engine"
KEYS = tuple(k for k, _, _ in _COMPILED) + (NO_ENGINE_KEY,)


def translate(output: str) -> Optional[Translation]:
    """The translation of an engine's output, or None when no known cause matches."""
    for _, pattern, translation in _COMPILED:
        if pattern.search(output or ""):
            return translation
    return None
