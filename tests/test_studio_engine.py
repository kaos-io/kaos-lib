"""F-32: detect and verify an engine with a stub behind `proc.run` and the recorded outputs of Docker and Podman."""
import pathlib

import pytest

from kaos_lib.studio import engine as eng
from studio_helpers import DOCKER_INFO, PODMAN_INFO, StubEngine

FX = pathlib.Path(__file__).resolve().parent / "engine_fixtures"


def rec(engine, key):
    return (1, (FX / engine / f"{key}.txt").read_text(encoding="utf-8"))


def verify(stub, kind="docker", arch="amd64", free_gb=100, binfmt=True):
    return eng.verify(kind, f"/usr/bin/{kind}", arch, run=stub.run, environ={}, disk_free=lambda p: int(free_gb * 1024 ** 3),
                      binfmt_exists=lambda n: binfmt)


def healthy_docker(extra=None):
    answers = {("info",): (0, DOCKER_INFO), ("context", "show"): (0, "default\n"), ("build",): (0, "sha256:abc"),
               ("rmi",): (0, "")}
    answers.update(extra or {})
    return StubEngine(answers)


def test_should_find_the_engines_on_path_docker_first():
    found = eng.detect(which=lambda n: f"/usr/bin/{n}" if n in ("podman", "docker") else None)
    assert [k for k, _ in found] == ["docker", "podman"]
    assert eng.detect(which=lambda n: None) == []


def test_should_accept_a_healthy_docker_engine_and_clean_up_its_test_image():
    stub = healthy_docker()
    v = verify(stub)
    assert v.ok and v.engine.flavour == "Docker Engine" and v.engine.arch == "amd64" and round(v.free_gb) == 100
    assert [c[1] for c in stub.calls if c[1] in ("build", "rmi")] == ["build", "rmi"]


def test_should_accept_a_healthy_podman_engine():
    stub = StubEngine({("info",): (0, PODMAN_INFO), ("build",): (0, ""), ("rmi",): (0, "")})
    v = verify(stub, kind="podman")
    assert v.ok and v.engine.flavour == "Podman" and v.engine.version == "5.8.4"


@pytest.mark.parametrize("engine,key", [("docker", "daemon_not_running"), ("podman", "daemon_not_running"),
                                         ("docker", "permission_denied_socket"), ("colima", "daemon_not_running")])
def test_should_report_why_the_daemon_cannot_be_used_in_plain_words(engine, key):
    stub = StubEngine({("info",): rec(engine, key)})
    v = verify(stub, kind="podman" if engine == "podman" else "docker")
    assert not v.ok and v.problems[0].key == key and v.problems[0].fix
    assert not [c for c in stub.calls if c[1] == "build"]    # nothing is built on a dead engine


def test_should_refuse_an_engine_with_too_little_disk_space():
    v = verify(healthy_docker(), free_gb=1.5)
    assert [p.key for p in v.problems] == ["no_space"] and "1.5 GB" in v.problems[0].message


@pytest.mark.parametrize("engine,key", [("docker", "no_space"), ("docker", "network"), ("podman", "network"),
                                         ("docker", "registry_auth")])
def test_should_translate_a_failing_test_build(engine, key):
    v = verify(healthy_docker({("build",): rec(engine, key)}))
    assert [p.key for p in v.problems] == [key]


def test_should_flag_missing_emulation_when_an_arm64_engine_must_build_amd64():
    arm = DOCKER_INFO.replace("x86_64", "aarch64")
    stub = healthy_docker({("info",): (0, arm), ("buildx", "ls"): (0, "default docker  linux/arm64*, linux/arm/v7")})
    v = verify(stub, arch="amd64")
    assert [p.key for p in v.problems] == ["exec_format"] and "emulation" in v.problems[0].message.lower()


def test_should_only_note_slower_builds_when_emulation_is_there():
    arm = DOCKER_INFO.replace("x86_64", "aarch64")
    stub = healthy_docker({("info",): (0, arm), ("buildx", "ls"): (0, "default docker  linux/arm64*, linux/amd64")})
    v = verify(stub, arch="amd64")
    assert v.ok and any("slower" in n for n in v.notes)


@pytest.mark.parametrize("context,expected", [("colima", "Colima"), ("desktop-linux", "Docker Desktop"),
                                               ("rancher-desktop", "Rancher Desktop"), ("default", "Docker Engine")])
def test_should_name_the_flavour_of_a_docker_compatible_engine(context, expected):
    v = verify(healthy_docker({("context", "show"): (0, context + "\n")}))
    assert v.engine.flavour == expected


def test_should_stop_at_the_first_engine_that_works_and_keep_every_verification():
    stub = StubEngine({("info",): rec("docker", "daemon_not_running")})
    stub.answers[("info",)] = rec("docker", "daemon_not_running")
    usable, seen = eng.first_usable([("docker", "/usr/bin/docker")], "amd64", run=stub.run, environ={},
                                    disk_free=lambda p: 10 ** 12)
    assert usable is None and len(seen) == 1 and not seen[0].ok
