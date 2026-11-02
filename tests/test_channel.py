"""Release channels (PEP 440 version; PEP 610 for local/commit installs), the recommended spec, the public channel
metadata, `kaosctl upgrade` and `--version`."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import kaos_lib
from kaos_lib import channel, cli, support
from kaos_lib.errors import AuthError, ConfigError
from packaging.requirements import Requirement

AR = "https://europe-west1-python.pkg.dev/kaos-dev-511509"
RC_WHEEL = f"{AR}/kaos-lib-rc/kaos-lib/kaos_lib-0.3.0rc2-py3-none-any.whl"
STABLE_WHEEL = f"{AR}/kaos-lib/kaos-lib/kaos_lib-0.3.0-py3-none-any.whl"
SHA256 = "0" * 64


# ------------------------------------------------------------------ channel detection
@pytest.mark.parametrize("version, expected", [
    ("0.3.0", ("stable", "v0.3.0")),
    ("0.3.0rc2", ("prerelease", "v0.3.0-rc.2")),
    ("1.12.0rc17", ("prerelease", "v1.12.0-rc.17")),
    ("0.3.0a1", ("unknown", None)),
    ("0.3.0.dev4", ("unknown", None)),
    ("0.3.0+local", ("unknown", None)),
    ("0.3.0.post1", ("unknown", None)),
    ("not-a-version", ("unknown", None)),
])
def test_the_channel_follows_from_the_version(version, expected):
    got = channel.channel_of(version)
    assert (got["channel"], got["tag"]) == expected


@pytest.mark.parametrize("record, expected", [
    ({"url": f"{RC_WHEEL}", "archive_info": {}}, ("prerelease", "v0.3.0-rc.2")),
    ({"url": "https://github.com/kaos-io/kaos-lib/archive/dc24f292029bb2a49a2cdf5c24eb169d7706d9a5.zip"},
     ("commit", "dc24f292029b")),
    ({"url": "file:///home/me/kaos-lib", "dir_info": {"editable": True}}, ("local", None)),
    ({"url": "file:///tmp/kaos_lib-0.3.0rc2-py3-none-any.whl", "archive_info": {}}, ("local", None)),
    (None, ("prerelease", "v0.3.0-rc.2")),                     # from a package index: the version decides
])
def test_local_and_commit_installs_come_from_pep_610(record, expected):
    got = channel.channel_of("0.3.0rc2", record)
    assert (got["channel"], got["tag"]) == expected


class FakeDist:
    def __init__(self, direct_url):
        self.direct_url = direct_url

    def read_text(self, name):
        assert name == "direct_url.json"
        return self.direct_url


@pytest.mark.parametrize("raw, expected", [
    (json.dumps({"url": RC_WHEEL, "archive_info": {}}), "prerelease"),
    (None, "stable"),
    ("{not json", "stable"),
])
def test_installed_reads_pep_610(monkeypatch, raw, expected):
    monkeypatch.setattr(channel.metadata, "distribution", lambda name: FakeDist(raw))
    assert channel.installed("0.3.0rc2" if expected == "prerelease" else "0.3.0")["channel"] == expected


def test_installed_when_not_installed_is_a_local_source_tree(monkeypatch):
    def missing(name):
        raise channel.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(channel.metadata, "distribution", missing)
    assert channel.installed("0.3.0") == {"channel": "local", "tag": None, "url": None}


@pytest.mark.parametrize("info, text", [
    ({"channel": "prerelease", "tag": "v0.3.0-rc.2"}, "prerelease v0.3.0-rc.2"),
    ({"channel": "stable", "tag": "v0.3.0"}, "stable v0.3.0"),
    ({"channel": "commit", "tag": "dc24f292029b"}, "commit dc24f292029b"),
    ({"channel": "local", "tag": None}, "local install"),
    ({"channel": "unknown", "tag": None}, "unknown"),
])
def test_describe(info, text):
    assert channel.describe(info) == text


# ------------------------------------------------------------------ the public channel metadata
@pytest.fixture
def releases(monkeypatch):
    """A local stand-in for the public bucket: {prefix: (status, body)}."""
    served = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            status, body = served.get(self.path.strip("/").split("/")[0], (404, b""))
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("KAOS_LIB_RELEASES_BASE", f"http://127.0.0.1:{server.server_port}")
    yield served
    server.shutdown()


def test_public_release_reads_the_channel_pointer(releases):
    releases["rc"] = (200, json.dumps({"tag": "v0.3.0-rc.2", "recommended": f"kaos-lib[zitadel] @ {RC_WHEEL}"}).encode())
    releases["stable"] = (200, json.dumps({"tag": "v0.3.0"}).encode())
    assert channel.public_release("prerelease")["tag"] == "v0.3.0-rc.2"
    assert channel.public_release("stable")["tag"] == "v0.3.0"
    assert channel.public_release("nightly") is None


@pytest.mark.parametrize("answer", [(404, b""), (500, b"boom"), (200, b"<html>"), (200, b"[1, 2]")])
def test_public_release_unusable_answers_are_none(releases, answer):
    releases["stable"] = answer
    assert channel.public_release("stable") is None


def test_public_release_offline_is_none(monkeypatch):
    monkeypatch.setenv("KAOS_LIB_RELEASES_BASE", "http://127.0.0.1:9")
    assert channel.public_release("stable") is None


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
    assert channel.is_current(channel.requirement(f"@ {RC_WHEEL}#sha256={SHA256}", False), rc, "0.3.0rc2")
    assert not channel.is_current(channel.requirement(f"@ {STABLE_WHEEL}", False), rc, "0.3.0rc2")
    assert channel.is_current(channel.requirement("==0.3.0rc2", False), rc, "0.3.0rc2")
    assert not channel.is_current(channel.requirement("==0.4.0", False), rc, "0.3.0rc2")
    assert not channel.is_current(channel.requirement(">=0.3", False), rc, "0.3.0rc2")   # a range is never "there"


def test_is_current_for_an_index_install_of_the_same_registry_wheel():
    from_index = {"channel": "stable", "tag": "v0.3.0", "url": None}
    assert channel.is_current(channel.requirement(f"@ {STABLE_WHEEL}#sha256={SHA256}", False), from_index, "0.3.0")
    assert not channel.is_current(channel.requirement(f"@ {STABLE_WHEEL}", False), from_index, "0.2.0")
    local = {"channel": "local", "tag": None, "url": "file:///src"}
    assert not channel.is_current(channel.requirement(f"@ {STABLE_WHEEL}", False), local, "0.3.0")


def test_pip_command_uses_this_interpreter():
    assert channel.pip_command(channel.requirement("==0.3.0", False)) == [
        sys.executable, "-m", "pip", "install", "--upgrade", "kaos-lib==0.3.0"]


# ------------------------------------------------------------------ kaosctl --version / upgrade
@pytest.fixture
def platform(fake, monkeypatch):
    monkeypatch.setattr(cli.LakeFS, "connect", classmethod(lambda cls, url=None, start=None: fake.client()))
    monkeypatch.setattr(channel, "installed", lambda v: {"channel": "prerelease", "tag": "v0.3.0-rc.2", "url": RC_WHEEL})
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
    assert version_lines(capsys) == [f"kaosctl {kaos_lib.__version__} (prerelease v0.3.0-rc.2)",
                                     f"platform http://lakefs.test: recommends kaos-lib @ {STABLE_WHEEL}"]


def test_version_when_the_platform_publishes_nothing_yet(capsys, platform):
    assert version_lines(capsys)[1] == "platform http://lakefs.test: publishes no recommendation yet"


def test_version_without_a_platform(capsys, monkeypatch):
    monkeypatch.setattr(channel, "installed", lambda v: {"channel": "local", "tag": None, "url": None})
    lines = version_lines(capsys)
    assert lines[0] == f"kaosctl {kaos_lib.__version__} (local install)"
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


NEWER_WHEEL = STABLE_WHEEL.replace("0.3.0", "9.9.9") + "#sha256=" + SHA256


def test_upgrade_installs_the_recommended_spec(capsys, platform, pip):
    recommend(platform, f"@ {NEWER_WHEEL}")
    code, out, _ = run(capsys, "upgrade")
    assert code == 0 and pip == [[sys.executable, "-m", "pip", "install", "--upgrade",
                                  str(Requirement(f"kaos-lib[zitadel] @ {NEWER_WHEEL}"))]]
    assert f"http://lakefs.test recommends {Requirement(f'kaos-lib[zitadel] @ {NEWER_WHEEL}')}" in out
    assert "kaosctl --version" in out


def test_upgrade_dry_run_installs_nothing(capsys, platform, pip):
    recommend(platform, "==9.9.9")
    code, out, _ = run(capsys, "upgrade", "--dry-run")
    assert code == 0 and pip == [] and "would run:" in out and "kaos-lib[zitadel]==9.9.9" in out


def test_upgrade_when_already_on_the_recommendation(capsys, platform, pip):
    recommend(platform, f"@ {RC_WHEEL}")
    code, out, _ = run(capsys, "upgrade")
    assert code == 0 and pip == [] and "nothing to do" in out


def test_upgrade_without_any_recommendation_installs_nothing(capsys, platform, pip):
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and pip == []
    assert "publishes no recommended kaos-lib" in err and "release is published yet" in err
    assert "python.pkg.dev/kaos-dev-511509/" in err


def test_upgrade_falls_back_to_the_newest_release_of_the_own_channel(capsys, platform, pip, releases):
    mine = channel.PREFIX[channel.channel_of_version(kaos_lib.__version__)]
    releases[mine] = (200, json.dumps({"tag": "v9.9.9", "channel": "stable",
                                       "recommended": f"kaos-lib[zitadel] @ {STABLE_WHEEL.replace('0.3.0', '9.9.9')}",
                                       "index_url": f"{AR}/kaos-lib/simple/"}).encode())
    code, out, err = run(capsys, "upgrade")
    assert code == 0 and "NOTE:" in err and "using the newest stable release v9.9.9" in err
    assert pip and pip[0][-1].endswith("kaos_lib-9.9.9-py3-none-any.whl")


def test_upgrade_without_a_platform_uses_the_public_channel(capsys, monkeypatch, pip, releases):
    mine = channel.PREFIX[channel.channel_of_version(kaos_lib.__version__)]
    releases[mine] = (200, json.dumps({"tag": "v9.9.9", "recommended": "==9.9.9"}).encode())
    code, _, err = run(capsys, "upgrade", "--dry-run")
    assert code == 0 and "no platform (cannot determine the lakeFS URL" in err and pip == []


def test_upgrade_refuses_a_recommendation_that_is_not_kaos_lib(capsys, platform, pip):
    recommend(platform, "kaos-libx @ https://evil.test/x.whl")
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and pip == [] and "refusing" in err


def test_upgrade_reports_a_failed_pip(capsys, platform, monkeypatch):
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 3)
    recommend(platform, "==9.9.9")
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and "pip install failed (exit 3)" in err


def test_upgrade_offline_platform(capsys, platform, pip):
    platform.kaos[support.UI_PATH] = (502, {"message": "bad gateway"})
    code, _, err = run(capsys, "upgrade")
    assert code == 1 and "publishes no recommended kaos-lib" in err and pip == []
