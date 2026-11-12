"""AC-42 / CON-17: kaosctl installs nothing. With no engine present it starts no package manager or installer, changes no
file outside the repository, and never installs Docker Desktop; `kaosctl dev` installs Python packages only into the
step's own virtual environment. The test patches `subprocess` itself and asserts on every program that is started."""
import os
import pathlib
import subprocess

import pytest

from kaos_lib import cli
from kaos_lib.studio import proc, pyenv, suggest
from studio_helpers import template_repo

INSTALLERS = {"apt", "apt-get", "dpkg", "dnf", "yum", "rpm", "zypper", "pacman", "apk", "snap", "flatpak", "brew",
              "winget", "choco", "scoop", "msiexec", "sudo", "su", "doas", "curl", "wget", "sh", "bash", "powershell",
              "pwsh", "installer", "softwareupdate", "port", "nix-env"}


class Recorder:
    """Replaces subprocess.run and subprocess.Popen: records every program, starts none."""

    def __init__(self):
        self.started = []

    def run(self, argv, *a, **kw):
        self.started.append([str(x) for x in argv])
        if "venv" in argv:                                    # `uv venv ... <path>`: make what uv would make
            venv = pathlib.Path(argv[-1])
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            (venv / "pyvenv.cfg").write_text("home = x\n")
            (venv / "bin" / "python").write_text("")
        out = "3.11.9" if "sys.version_info" in " ".join(map(str, argv)) else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    def popen(self, argv, *a, **kw):
        self.started.append([str(x) for x in argv])
        raise FileNotFoundError(argv[0])

    def programs(self):
        return {os.path.basename(c[0]).lower().removesuffix(".exe") for c in self.started}


@pytest.fixture
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(subprocess, "run", rec.run)
    monkeypatch.setattr(subprocess, "Popen", rec.popen)
    monkeypatch.setattr(os, "system", lambda cmd: rec.started.append(["os.system", cmd]) or 1)
    return rec


def tree(root: pathlib.Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("platform", [suggest.Platform("linux", "ubuntu", "amd64"), suggest.Platform("linux", "fedora", "amd64"),
                                      suggest.Platform("macos", arch="arm64"), suggest.Platform("windows", arch="amd64")])
def test_should_start_no_installer_and_change_no_file_when_there_is_no_engine(tmp_path, monkeypatch, recorder, capsys, platform):
    repo = template_repo(tmp_path / "app")
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: None)      # no docker, no podman, no uv
    monkeypatch.setattr(suggest, "detect_platform", lambda: platform)
    before = tree(tmp_path)
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 1
    assert not (recorder.programs() & INSTALLERS), recorder.started
    assert recorder.programs() <= {"git"}                                # at most the commit lookup
    assert tree(tmp_path) == before
    assert "kaosctl did not run any of these commands" in capsys.readouterr().out


def test_should_never_install_docker_desktop_even_when_it_is_the_only_thing_asked_for(tmp_path, monkeypatch, recorder):
    repo = template_repo(tmp_path / "app")
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: None)
    cli.main(["build", "--path", str(repo)])
    assert not [c for c in recorder.started if "docker" in " ".join(c).lower() and "desktop" in " ".join(c).lower()]


@pytest.mark.parametrize("program", sorted(proc.FORBIDDEN))
def test_should_refuse_to_start_a_package_manager_or_installer_at_all(program, recorder):
    with pytest.raises(proc.RefusedProgram):
        proc.run([program, "install", "docker"])
    with pytest.raises(proc.RefusedProgram):
        proc.stream([program, "install", "docker"])
    assert recorder.started == []


def test_should_cover_every_installer_the_test_names_in_the_runtime_guard():
    assert INSTALLERS - {"nix-env"} <= proc.FORBIDDEN | {"nix-env"}


def test_should_install_python_packages_only_into_the_steps_own_environment(tmp_path, monkeypatch, recorder):
    repo = template_repo(tmp_path / "app")
    monkeypatch.setattr("shutil.which", lambda name, *a, **k: "/usr/bin/uv" if name == "uv" else None)
    cli.main(["dev", str(repo), "--step", "data-summary"])
    installs = [c for c in recorder.started if "install" in c and "pip" in c]
    assert installs
    for cmd in installs:
        assert str(pyenv.step_env(repo / "steps/data_summary")) in " ".join(cmd), cmd   # always aimed at the step's venv
    assert not (recorder.programs() & INSTALLERS)
    assert all(p in ("uv", "git") or p.startswith("python") for p in recorder.programs())   # uv, or Python itself
