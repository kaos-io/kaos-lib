"""The only place kaosctl starts a program.

Why: one choke point makes "kaosctl installs nothing" (CON-17, AC-42) checkable: a test replaces `subprocess` here
and asserts that no package manager or installer is ever started. It also lets a test give the build a stub engine.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

# Programs kaosctl must never start: system package managers and installers (CON-17). A guard, in addition to the
# rule that no code path asks for one; `run` refuses them so a future change cannot add one silently.
FORBIDDEN = frozenset((
    "apt", "apt-get", "aptitude", "dpkg", "dnf", "yum", "rpm", "zypper", "pacman", "apk", "emerge", "snap", "flatpak",
    "brew", "port", "nix", "nix-env", "winget", "choco", "scoop", "msiexec", "installer", "softwareupdate",
    "sudo", "su", "doas", "pkexec", "runas", "curl", "wget", "sh", "bash", "powershell", "pwsh",
))


class RefusedProgram(Exception):
    """kaosctl tried to start a program it is never allowed to start."""


@dataclass
class Result:
    """What a started program did. `returncode` is 127 when the program does not exist, 124 on a timeout."""
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def text(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


def program_name(argv: list) -> str:
    name = os.path.basename(str(argv[0])).lower()
    return name[:-4] if name.endswith(".exe") else name


def run(argv: list, env: Optional[dict] = None, cwd=None, timeout: Optional[float] = None) -> Result:
    """Run a program and capture its output. Never raises for a failing program: the Result says what happened."""
    if program_name(argv) in FORBIDDEN:
        raise RefusedProgram(f"kaosctl never runs {argv[0]!r}: it installs nothing on your machine.")
    try:
        done = subprocess.run([str(a) for a in argv], env=env, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        return Result(done.returncode, done.stdout or "", done.stderr or "")
    except FileNotFoundError as exc:
        return Result(127, "", str(exc))
    except subprocess.TimeoutExpired:
        return Result(124, "", f"timed out after {timeout} seconds")
    except PermissionError as exc:
        return Result(126, "", str(exc))


def stream(argv: list, env: Optional[dict] = None, cwd=None, echo=print, tail: int = 40) -> Result:
    """Run a program, echo its output line by line as it comes, and keep the last `tail` lines for error messages."""
    if program_name(argv) in FORBIDDEN:
        raise RefusedProgram(f"kaosctl never runs {argv[0]!r}: it installs nothing on your machine.")
    try:
        child = subprocess.Popen([str(a) for a in argv], env=env, cwd=cwd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        return Result(127, "", str(exc))
    except PermissionError as exc:
        return Result(126, "", str(exc))
    lines = []
    for line in child.stdout:
        echo(line.rstrip("\n"))
        lines.append(line.rstrip("\n"))
        del lines[:-tail]
    return Result(child.wait(), "\n".join(lines), "")
