"""AC-41: every translated engine error matches a recorded error: the recorded output of Docker, Podman and Colima
gives the message and fix of section 7.3."""
import pathlib

import pytest

from kaos_lib.studio import engine_errors

FIXTURES = pathlib.Path(__file__).resolve().parent / "engine_fixtures"
RECORDED = sorted(FIXTURES.glob("*/*.txt"))


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_should_translate_the_recorded_output_to_the_cause_in_its_name(path):
    t = engine_errors.translate(path.read_text(encoding="utf-8"))
    assert t is not None, path
    assert t.key == path.stem.split("__")[0]
    assert t.message and t.fix and "\n" not in t.message


def test_should_cover_every_cause_of_section_7_3_with_a_recording_from_at_least_one_engine():
    recorded = {p.stem.split("__")[0] for p in RECORDED}
    assert recorded >= set(engine_errors.KEYS) - {engine_errors.NO_ENGINE_KEY}


def test_should_have_recordings_from_docker_podman_and_colima():
    assert {p.parent.name for p in RECORDED} == {"docker", "podman", "colima"}


def test_should_return_none_for_an_output_it_does_not_know():
    assert engine_errors.translate("#5 DONE 0.2s\n") is None


def test_should_prefer_the_socket_permission_over_the_daemon_message():
    text = "permission denied while trying to connect to the Docker daemon socket"
    assert engine_errors.translate(text).key == "permission_denied_socket"
