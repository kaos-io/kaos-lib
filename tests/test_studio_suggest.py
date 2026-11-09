"""AC-44: with no usable engine the message names what is missing for the client's OS, recommends a free engine, gives the
official link and the exact command to run, notes the Docker Desktop licence and ends with "run kaosctl build again".
The golden files are the exact text; a change to a link or a command is a reviewed change to a file here (T-23)."""
import os
import pathlib

import pytest

from kaos_lib.studio.suggest import Platform, no_engine_message

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"
CASES = {
    "no_engine_ubuntu": Platform("linux", "ubuntu", "amd64"),
    "no_engine_fedora": Platform("linux", "fedora", "amd64"),
    "no_engine_linux_other": Platform("linux", "gentoo", "amd64"),
    "no_engine_wsl": Platform("linux", "ubuntu", "amd64", wsl=True),
    "no_engine_macos_arm64": Platform("macos", arch="arm64"),
    "no_engine_macos_amd64": Platform("macos", arch="amd64"),
    "no_engine_windows": Platform("windows", arch="amd64"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_should_print_the_golden_message_for_the_os(name):
    path = GOLDEN / f"{name}.txt"
    text = no_engine_message(CASES[name])
    if os.environ.get("KAOS_UPDATE_GOLDEN"):
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(CASES))
def test_should_carry_the_five_things_ac_44_asks_for(name):
    text = no_engine_message(CASES[name])
    assert "free" in text and "https://" in text and "Official instructions" in text
    assert "250 employees" in text and "10 million" in text
    assert text.rstrip().endswith("run `kaosctl build` again.")
    assert "did not run any of these commands" in text


@pytest.mark.parametrize("system,free_engine", [("linux", "Docker Engine"), ("macos", "Colima"),
                                                 ("windows", "Docker Engine inside WSL2")])
def test_should_recommend_the_free_engine_of_the_prd_for_each_os(system, free_engine):
    assert f"What to install (free): {free_engine}" in no_engine_message(Platform(system, arch="amd64"))


def test_should_mention_rosetta_only_for_apple_chips():
    assert "--vz-rosetta" in no_engine_message(Platform("macos", arch="arm64"))
    assert "--vz-rosetta" not in no_engine_message(Platform("macos", arch="amd64"))
