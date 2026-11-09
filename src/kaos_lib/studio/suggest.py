"""The message printed when no container engine works on this machine (PRD-CONSOLE-1682 D-17, AC-44).

Why: kaosctl never installs an engine (CON-17). It says what is missing for the client's OS, recommends a free engine, gives
the official link and the exact command for the client to run themselves, notes the Docker Desktop licence, and ends
with "run kaosctl build again". The links and commands come from the reviewed table below (T-23): a wrong or
outdated line here is a bug, and `tests/golden/` holds the exact text printed for each OS.
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass

LICENCE_NOTE = ("Docker Desktop also works if you already have it, but it needs a paid subscription for companies with "
                "more than 250 employees or more than 10 million US dollars of revenue.")
LINUX_PACKAGE_COMMAND = {   # distribution id (from /etc/os-release) -> the distribution's own podman package command
    "ubuntu": "sudo apt-get install -y podman", "debian": "sudo apt-get install -y podman",
    "fedora": "sudo dnf install -y podman", "rhel": "sudo dnf install -y podman", "centos": "sudo dnf install -y podman",
    "rocky": "sudo dnf install -y podman", "almalinux": "sudo dnf install -y podman",
    "arch": "sudo pacman -S podman", "manjaro": "sudo pacman -S podman",
    "opensuse-leap": "sudo zypper install podman", "opensuse-tumbleweed": "sudo zypper install podman",
}
LINUX_GENERIC = "your distribution's package manager (the package is called podman)"


@dataclass(frozen=True)
class Platform:
    """The facts the message depends on: the OS family, the distribution id on Linux, the CPU and whether this is WSL."""
    system: str          # linux | macos | windows
    distro: str = ""
    arch: str = ""       # amd64 | arm64
    wsl: bool = False


def detect_platform() -> Platform:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    if sys.platform == "darwin":
        return Platform("macos", arch=arch)
    if os.name == "nt":
        return Platform("windows", arch=arch)
    distro = ""
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("ID="):
                distro = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return Platform("linux", distro, arch, "microsoft" in platform.release().lower())


def _block(title: str, link: str, commands: list, intro: str = "") -> list:
    lines = [title, f"  Official instructions: {link}"]
    if intro:
        lines.append(f"  {intro}")
    lines += [f"      {c}" for c in commands]
    return lines


def _linux(p: Platform) -> list:
    command = LINUX_PACKAGE_COMMAND.get(p.distro, LINUX_GENERIC)
    lines = ["What to install (free): Docker Engine"]
    lines += _block("", "https://docs.docker.com/engine/install/", [
        "curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh"],
        "Command to run yourself (Docker's own install script; read it first at https://get.docker.com):")[1:]
    lines += ["  Then let your user use it (log out and in afterwards):", "      sudo usermod -aG docker $USER", ""]
    lines += _block("Alternative (free, no background service): Podman", "https://podman.io/docs/installation",
                    [command], "Command to run yourself:")
    if p.wsl:
        lines += ["", "You are in WSL2: install the engine inside this Linux, not in Windows."]
    return lines


def _macos(p: Platform) -> list:
    lines = _block("What to install (free): Colima", "https://github.com/abiosoft/colima#installation",
                   ["brew install colima docker", "colima start"], "Commands to run yourself (Homebrew, https://brew.sh):")
    if p.arch == "arm64":
        lines += ["  Your Mac has an Apple chip and the platform runs amd64 images: building them is emulated and slower. "
                  "To use Rosetta for it, start Colima with:", "      colima start --vm-type vz --vz-rosetta"]
    lines += [""] + _block("Alternative (free): Podman", "https://podman.io/docs/installation",
                           ["brew install podman", "podman machine init", "podman machine start"],
                           "Commands to run yourself:")
    return lines


def _windows(p: Platform) -> list:
    lines = _block("What to install (free): Docker Engine inside WSL2", "https://learn.microsoft.com/windows/wsl/install",
                   ["wsl --install"], "Command to run yourself, in an administrator PowerShell (then restart Windows):")
    lines += ["  Then, in the Linux shell that opens, install Docker Engine with the Linux instructions at "
              "https://docs.docker.com/engine/install/ and run kaosctl there (pip install kaos-lib in that shell).", ""]
    lines += _block("Alternative (free): Podman Desktop", "https://podman-desktop.io/downloads",
                    ["winget install RedHat.Podman-Desktop"], "Command to run yourself:")
    lines += ["", "If you cannot install WSL2 or an engine (no administrator rights, WSL disabled by policy, no "
                  "virtualisation), ask your IT team for one of the two."]
    return lines


def no_engine_message(p: Platform) -> str:
    """The full text for a machine with no usable engine. Ends with the line that tells the client what to do next."""
    head = ["No usable container engine was found on this machine (kaosctl looked for docker and podman).",
            "kaosctl builds your step image with an engine that is already installed. It never installs one for you.", ""]
    body = {"linux": _linux, "macos": _macos, "windows": _windows}[p.system](p)
    tail = ["", LICENCE_NOTE, "", "kaosctl did not run any of these commands. After installing, run `kaosctl build` again."]
    return "\n".join(head + body + tail) + "\n"
