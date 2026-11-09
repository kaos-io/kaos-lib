"""F-32/F-33 through `kaosctl build`: the same inputs as CI's build-push, the doctor first, a stub engine, no push."""
import argparse
import pathlib

import pytest

from kaos_lib import cli
from kaos_lib.studio import build, proc, steps
from studio_helpers import DOCKER_INFO, StubEngine, template_repo

FX = pathlib.Path(__file__).resolve().parent / "engine_fixtures"


@pytest.fixture
def repo(tmp_path):
    return template_repo(tmp_path / "my-app")


def install_engine(monkeypatch, stub, found=(("docker", "/usr/bin/docker"),)):
    monkeypatch.setattr(proc, "run", stub.run)
    monkeypatch.setattr(proc, "stream", stub.stream)
    monkeypatch.setattr("kaos_lib.studio.engine.detect", lambda which=None: list(found))


def healthy(extra=None):
    answers = {("info",): (0, DOCKER_INFO), ("context", "show"): (0, "default"), ("build", "-q"): (0, "x"),
               ("rmi",): (0, ""), ("build",): (0, "#1 DONE 0.1s")}
    answers.update(extra or {})
    return StubEngine(answers)


def build_calls(stub):
    return [c for c in stub.calls if c[1] == "build" and "-q" not in c]


def flag_values(cmd, flag):
    return [cmd[i + 1] for i, w in enumerate(cmd) if w == flag]


def test_should_pass_ci_s_inputs_to_the_engine_for_a_kaos_lib_step(repo, monkeypatch, capsys):
    stub = healthy()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "dataset-loading", "--path", str(repo), "--kaos-lib", "kaos-lib==0.4.0rc20",
                     "--registry-url", "zot.example/proj/app"]) == 0
    (cmd,) = build_calls(stub)
    step = steps.find(repo, "dataset-loading")
    assert cmd[2:4] == ["--platform", "linux/amd64"]                       # the platform's architecture
    assert flag_values(cmd, "-f") == [str(step.dockerfile)] and cmd[-1] == str(step.path)    # the step folder is the context
    args = flag_values(cmd, "--build-arg")
    assert args[:2] == ["REGISTRY_URL=zot.example/proj/app", "VERSION=local-nogit"]
    assert any(a.startswith("KAOS_LIB_PACKAGE=kaos-lib") and "0.4.0rc20" in a for a in args)
    assert flag_values(cmd, "--label") == [[a for a in args if a.startswith("KAOS_LIB_PACKAGE=")][0].split("=", 1)[1]
                                           ] or flag_values(cmd, "--label")[0].startswith("io.kaos.lib=kaos-lib")
    assert "push" not in " ".join(cmd) and not [c for c in stub.calls if c[1] == "push"]


def test_should_label_with_the_dockerfile_default_when_no_spec_is_chosen(repo, monkeypatch):
    stub = healthy()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "dataset-loading", "--path", str(repo)]) == 0
    cmd = build_calls(stub)[0]
    assert not [a for a in flag_values(cmd, "--build-arg") if a.startswith("KAOS_LIB_PACKAGE")]
    assert flag_values(cmd, "--label") == ['io.kaos.lib=kaos-lib[zitadel]==0.4.0rc20']


def test_should_not_pass_the_kaos_lib_argument_to_a_dockerfile_that_does_not_declare_it(repo, monkeypatch):
    stub = healthy()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo), "--kaos-lib", "kaos-lib==0.4.0rc20"]) == 0
    cmd = build_calls(stub)[0]
    assert not [a for a in flag_values(cmd, "--build-arg") if a.startswith("KAOS_LIB")] and "--label" not in cmd


def test_should_build_compose_and_validate_with_the_repository_root_as_context(repo, monkeypatch):
    stub = healthy()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "compose-and-validate", "--path", str(repo)]) == 0
    assert build_calls(stub)[0][-1] == str(repo)


def test_should_tag_the_image_locally_and_say_nothing_was_pushed(repo, monkeypatch, capsys):
    stub = healthy()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 0
    assert flag_values(build_calls(stub)[0], "-t") == ["kaos-local/my-app:data-summary-local-nogit"]
    assert "nothing was pushed" in capsys.readouterr().out


def test_should_use_the_arch_flag_and_the_environment_variable(repo, monkeypatch):
    stub = healthy({("buildx", "ls"): (0, "default docker  linux/amd64*, linux/arm64")})
    install_engine(monkeypatch, stub)
    monkeypatch.setenv("KAOS_BUILD_ARCH", "arm64")
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 0
    assert build_calls(stub)[0][2:4] == ["--platform", "linux/arm64"]


def test_should_print_the_command_and_build_nothing_on_a_dry_run(repo, monkeypatch, capsys):
    stub = StubEngine()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo), "--dry-run"]) == 0
    assert stub.calls == [] or all(c[0] == "git" for c in stub.calls)
    assert "would run: docker build --platform linux/amd64" in capsys.readouterr().out


def test_should_stop_before_the_build_when_the_doctor_finds_an_error(repo, monkeypatch, capsys):
    (repo / "steps/data_summary/app/entry.py").unlink()
    stub = healthy()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 2
    out = capsys.readouterr()
    assert "L-D05" in out.out and "Dockerfile doctor found 1 error" in out.err
    assert not build_calls(stub) and not [c for c in stub.calls if c[1] == "info"]


def test_should_only_report_the_doctor_findings_of_the_steps_being_built(repo, monkeypatch, capsys):
    (repo / "steps/dataset_loading/app/entry.py").unlink()    # an error in ANOTHER step
    stub = healthy()
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 0
    assert "dataset_loading" not in capsys.readouterr().out


def test_should_print_the_suggestion_and_exit_1_when_there_is_no_engine(repo, monkeypatch, capsys):
    install_engine(monkeypatch, StubEngine(), found=())
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "No usable container engine" in out and out.rstrip().endswith("run `kaosctl build` again.")


def test_should_explain_an_engine_that_is_installed_but_stopped(repo, monkeypatch, capsys):
    stub = StubEngine({("info",): (1, (FX / "docker/daemon_not_running.txt").read_text())})
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "installed but not running" in err and "Fix:" in err


@pytest.mark.parametrize("engine,key", [("docker", "network"), ("docker", "registry_auth"), ("podman", "exec_format"),
                                         ("docker", "no_space")])
def test_should_translate_a_failed_build_into_a_message_and_a_fix(repo, monkeypatch, capsys, engine, key):
    stub = healthy({("build", "--platform"): (1, (FX / engine / f"{key}.txt").read_text())})
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "failed" in err and "Fix:" in err


def test_should_say_so_when_a_build_fails_for_an_unknown_reason(repo, monkeypatch, capsys):
    stub = healthy({("build", "--platform"): (1, "something odd")})
    install_engine(monkeypatch, stub)
    assert cli.main(["build", "data-summary", "--path", str(repo)]) == 1
    assert "last lines are above" in capsys.readouterr().err


def test_should_refuse_an_unknown_step_and_list_the_known_ones(repo, capsys):
    assert cli.main(["build", "nope", "--path", str(repo)]) == 1
    assert "Steps: dataset-loading" in capsys.readouterr().err


def test_should_refuse_an_unknown_architecture():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["build", "--arch", "riscv"])
