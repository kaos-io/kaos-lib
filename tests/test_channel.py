"""Release channel detection (PEP 610 direct_url.json), the platform's recommended spec, `kaos-cli upgrade`, `--version`."""
import json
import sys

import pytest

import kaos_lib
from kaos_lib import channel, cli, support
from kaos_lib.errors import AuthError, ConfigError
from packaging.requirements import Requirement

REL = "https://github.com/kaos-io/kaos-lib/releases/download"
RC_WHEEL = f"{REL}/v0.3.0-rc.2/kaos_lib-0.3.0-py3-none-any.whl"
STABLE_WHEEL = f"{REL}/v0.3.0/kaos_lib-0.3.0-py3-none-any.whl"


# ------------------------------------------------------------------ channel detection
@pytest.mark.parametrize("record, expected", [
    ({"url": RC_WHEEL, "archive_info": {}}, ("prerelease", "v0.3.0-rc.2")),
    ({"url": STABLE_WHEEL, "archive_info": {}}, ("stable", "v0.3.0")),
    ({"url": f"{REL}/v0.4.0-rc.11/kaos_lib-0.4.0.tar.gz"}, ("prerelease", "v0.4.0-rc.11")),
    ({"url": "https://github.com/kaos-io/kaos-lib/archive/refs/tags/v0.3.0.zip"}, ("stable", "v0.3.0")),
    ({"url": "https://github.com/kaos-io/kaos-lib/archive/refs/tags/v0.3.0-rc.1.tar.gz"}, ("prerelease", "v0.3.0-rc.1")),
    ({"url": "https://github.com/kaos-io/kaos-lib/archive/dc24f292029bb2a49a2cdf5c24eb169d7706d9a5.zip"},
     ("commit", "dc24f292029b")),
    ({"url": f"{REL}/v0.3.0-rc/kaos_lib-0.3.0-py3-none-any.whl"}, ("unknown", "v0.3.0-rc")),   # not vX.Y.Z-rc.N
    ({"url": f"{REL}/v0.3/kaos_lib-0.3-py3-none-any.whl"}, ("unknown", "v0.3")),
    ({"url": "https://example.test/kaos_lib-0.3.0-py3-none-any.whl"}, ("unknown", None)),
    ({"url": "file:///home/me/kaos-lib", "dir_info": {"editable": True}}, ("local", None)),
    ({"url": "file:///tmp/kaos_lib-0.3.0-py3-none-any.whl", "archive_info": {}}, ("local", None)),
    (None, ("index", None)),
])
def test_channel_of_the_install_url(record, expected):
    got = channel.channel_of(record)
    assert (got["channel"], got["tag"]) == expected


@pytest.mark.parametrize("tag, expected", [("v1.2.3", "stable"), ("v1.2.3-rc.4", "prerelease"),
                                           ("1.2.3", "unknown"), ("v1.2.3rc4", "unknown"), ("v1.2.3-rc.", "unknown")])
def test_channel_of_tag(tag, expected):
    assert channel.channel_of_tag(tag) == expected


class FakeDist:
    def __init__(self, direct_url):
        self.direct_url = direct_url

    def read_text(self, name):
        assert name == "direct_url.json"
        return self.direct_url


@pytest.mark.parametrize("raw, expected", [
    (json.dumps({"url": RC_WHEEL, "archive_info": {}}), "prerelease"),
    (None, "index"),
    ("{not json", "unknown"),
])
def test_installed_reads_pep_610(monkeypatch, raw, expected):
    monkeypatch.setattr(channel.metadata, "distribution", lambda name: FakeDist(raw))
    assert channel.installed()["channel"] == expected


def test_installed_when_not_installed(monkeypatch):
    def missing(name):
        raise channel.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(channel.metadata, "distribution", missing)
    assert channel.installed() == {"channel": "unknown", "tag": None, "url": None}


@pytest.mark.parametrize("info, text", [
    ({"channel": "prerelease", "tag": "v0.3.0-rc.2"}, "prerelease v0.3.0-rc.2"),
    ({"channel": "stable", "tag": "v0.3.0"}, "stable v0.3.0"),
    ({"channel": "commit", "tag": "dc24f292029b"}, "commit dc24f292029b"),
    ({"channel": "local", "tag": None}, "local install"),
    ({"channel": "index", "tag": None}, "from a package index"),
    ({"channel": "unknown", "tag": None}, "unknown"),
])
def test_describe(info, text):
    assert channel.describe(info) == text


# ------------------------------------------------------------------ recommendation
@pytest.mark.parametrize("value, expected", [
    ({"recommended": "==0.3.0"}, "==0.3.0"),
    (json.dumps({"recommended": f"@ {STABLE_WHEEL}"}), f"@ {STABLE_WHEEL}"),
    ({"recommended": "  ==0.3.0 "}, "==0.3.0"),
    ({"recommended": ""}, None),
    ({"recommended": 3}, None),
    ({"version": "0.3.0"}, None),
    ("{broken", None),
    (None, None),
    ([], None),
])
def test_recommended(value, expected):
    assert channel.recommended(value) == expected


@pytest.mark.parametrize("spec, zitadel, expected", [
    ("==0.3.0", False, "kaos-lib==0.3.0"),
    ("==0.3.0", True, "kaos-lib[zitadel]==0.3.0"),
    (f"@ {STABLE_WHEEL}", True, f"kaos-lib[zitadel]@ {STABLE_WHEEL}"),
    (f"kaos-lib @ {RC_WHEEL}", True, f"kaos-lib[zitadel]@ {RC_WHEEL}"),       # keeps the installed extra
    (f"kaos-lib[zitadel] @ {RC_WHEEL}", False, f"kaos-lib[zitadel]@ {RC_WHEEL}"),
    (f"Kaos_Lib @ {RC_WHEEL}", False, f"Kaos_Lib@ {RC_WHEEL}"),
])
def test_requirement_from_a_recommended_spec(spec, zitadel, expected):
    assert str(channel.requirement(spec, zitadel)) == str(Requirement(expected))


@pytest.mark.parametrize("spec, problem", [
    ("requests==2.0", "not kaos-lib"),
    ("kaos-libx @ https://evil.test/x.whl", "not kaos-lib"),
    ("kaos-lib @ http://insecure.test/kaos_lib-0.3.0-py3-none-any.whl", "not https"),
    ("@ file:///etc/passwd", "not https"),
    ("== = 0.3", "not a pip requirement"),
])
def test_requirement_refuses_anything_but_kaos_lib_over_https(spec, problem):
    with pytest.raises(ConfigError, match=problem):
        channel.requirement(spec, False)


def test_is_current():
    rc = {"channel": "prerelease", "tag": "v0.3.0-rc.2", "url": RC_WHEEL}
    assert channel.is_current(channel.requirement(f"@ {RC_WHEEL}", False), rc, "0.3.0")
    assert not channel.is_current(channel.requirement(f"@ {STABLE_WHEEL}", False), rc, "0.3.0")
    assert channel.is_current(channel.requirement("==0.3.0", False), rc, "0.3.0")
    assert not channel.is_current(channel.requirement("==0.4.0", False), rc, "0.3.0")
    assert not channel.is_current(channel.requirement(">=0.3", False), rc, "0.3.0")   # a range is never "there"


def test_pip_command_uses_this_interpreter():
    assert channel.pip_command(channel.requirement("==0.3.0", False)) == [
        sys.executable, "-m", "pip", "install", "--upgrade", "kaos-lib==0.3.0"]


# ------------------------------------------------------------------ kaos-cli --version / upgrade
@pytest.fixture
def platform(fake, monkeypatch):
    monkeypatch.setattr(cli.LakeFS, "connect", classmethod(lambda cls, url=None, start=None: fake.client()))
    monkeypatch.setattr(channel, "installed", lambda: {"channel": "prerelease", "tag": "v0.3.0-rc.2", "url": RC_WHEEL})
    return fake


def recommend(fake, spec):
    fake.kaos[support.UI_PATH] = (200, {"kaos_lib_support": {"version": "0.3.0", "supported": ">=0.2",
                                                             "recommended": spec}})


def version_lines(capsys):
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--version"])
    assert exit_.value.code == 0
    return capsys.readouterr().out.strip().splitlines()


def test_version_shows_channel_and_the_platform_recommendation(capsys, platform):
    recommend(platform, f"@ {STABLE_WHEEL}")
    assert version_lines(capsys) == [f"kaos-cli {kaos_lib.__version__} (prerelease v0.3.0-rc.2)",
                                     f"platform http://lakefs.test: recommends kaos-lib @ {STABLE_WHEEL}"]


def test_version_when_the_platform_publishes_nothing_yet(capsys, platform):
    assert version_lines(capsys)[1] == "platform http://lakefs.test: publishes no recommendation yet"


def test_version_without_a_platform(capsys, monkeypatch):
    monkeypatch.setattr(channel, "installed", lambda: {"channel": "local", "tag": None, "url": None})
    lines = version_lines(capsys)
    assert lines[0] == f"kaos-cli {kaos_lib.__version__} (local install)"
    assert lines[1].startswith("platform: unknown (cannot determine the lakeFS URL")


def test_version_signed_out_reads_the_recommendation_anonymously(capsys, platform, monkeypatch):
    def signed_out(cls, url=None, start=None):
        raise AuthError("not signed in")
    monkeypatch.setattr(cli.LakeFS, "connect", classmethod(signed_out))
    monkeypatch.setenv("LAKEFS_ENDPOINT", "http://lakefs.test")
    anonymous = platform.client().session
    monkeypatch.setattr(cli.requests, "Session", lambda: anonymous)
    recommend(platform, "==0.3.0")
    assert version_lines(capsys)[1] == "platform http://lakefs.test: recommends kaos-lib ==0.3.0"


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def pip(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: calls.append(cmd) or 0)
    monkeypatch.setattr(channel, "has_zitadel_extra", lambda: True)
    return calls


def test_upgrade_installs_the_recommended_spec(capsys, platform, pip):
    recommend(platform, f"@ {STABLE_WHEEL}")
    code, out, _ = run(capsys, "upgrade")
    assert code == 0 and pip == [[sys.executable, "-m", "pip", "install", "--upgrade",
                                  str(Requirement(f"kaos-lib[zitadel] @ {STABLE_WHEEL}"))]]
    assert f"http://lakefs.test recommends {Requirement(f'kaos-lib[zitadel] @ {STABLE_WHEEL}')}" in out and "kaos-cli --version" in out


def test_upgrade_dry_run_installs_nothing(capsys, platform, pip):
    recommend(platform, "==0.4.0")
    code, out, _ = run(capsys, "upgrade", "--dry-run")
    assert code == 0 and pip == [] and "would run:" in out and "kaos-lib[zitadel]==0.4.0" in out


def test_upgrade_when_already_on_the_recommendation(capsys, platform, pip):
    recommend(platform, f"@ {RC_WHEEL}")
    code, out, _ = run(capsys, "upgrade")
    assert code == 0 and pip == [] and "nothing to do" in out


def test_upgrade_without_a_recommendation_falls_back_with_a_clear_message(capsys, platform, pip):
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and pip == []
    assert "publishes no recommended kaos-lib yet" in err and "github.com/kaos-io/kaos-lib/releases" in err


def test_upgrade_refuses_a_recommendation_that_is_not_kaos_lib(capsys, platform, pip):
    recommend(platform, "kaos-libx @ https://evil.test/x.whl")
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and pip == [] and "refusing" in err


def test_upgrade_reports_a_failed_pip(capsys, platform, monkeypatch):
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 3)
    recommend(platform, "==0.4.0")
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and "pip install failed (exit 3)" in err


def test_upgrade_offline_platform(capsys, platform, pip):
    platform.kaos[support.UI_PATH] = (502, {"message": "bad gateway"})
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and "publishes no recommended kaos-lib yet" in err
