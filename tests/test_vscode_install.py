"""`kaosctl vscode install`: the extension published with this kaos-lib release, checked by its SHA-256."""
from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kaos_lib import channel, cli, editor

VSIX = b"PK\x03\x04 the extension"
RECORD_PATH = "rc/v0.4.0-rc.7/vscode.json"


@pytest.fixture
def bucket(monkeypatch):
    """A local stand-in for the public bucket ({path: (status, body)}) holding the extension of 0.4.0rc7."""
    served = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            status, body = served.get(self.path.strip("/"), (404, b""))
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("KAOS_LIB_RELEASES_BASE", base)
    monkeypatch.setattr(cli, "__version__", "0.4.0rc7")
    served["rc/v0.4.0-rc.7/kaos-pipeline-0.4.0-rc.7.vsix"] = (200, VSIX)
    served[RECORD_PATH] = (200, json.dumps(record(base)).encode())
    served["base"] = base
    yield served
    server.shutdown()


def record(base, **changes):
    return dict({"name": "kaos-pipeline", "version": "0.4.0-rc.7", "kaos_lib": "0.4.0rc7",
                 "url": f"{base}/rc/v0.4.0-rc.7/kaos-pipeline-0.4.0-rc.7.vsix",
                 "sha256": hashlib.sha256(VSIX).hexdigest()}, **changes)


@pytest.fixture
def editors(monkeypatch):
    """Stand-ins for PATH and for running the editor: {command: path} found, and the commands that were run."""
    found, ran = {"code": "/usr/bin/code"}, []
    monkeypatch.setattr(editor.shutil, "which", lambda name: found.get(name))

    def call(cmd):
        ran.append((cmd, open(cmd[2], "rb").read()))
        return 0
    monkeypatch.setattr(cli.subprocess, "call", call)
    return found, ran


def test_public_vscode_is_the_record_of_this_release(bucket):
    assert channel.public_vscode("0.4.0rc7")["version"] == "0.4.0-rc.7"
    assert channel.public_vscode("0.4.0rc8") is None, "a release from before the extension was published"
    assert channel.public_vscode("0.4.0.dev1") is None, "not a release"


@pytest.mark.parametrize("changes", [{"name": "other"}, {"sha256": "abc"}, {"url": "http://elsewhere.example/x.vsix"},
                                     {"url": 3}, {"version": None}])
def test_public_vscode_refuses_a_record_it_cannot_trust(bucket, changes):
    bucket[RECORD_PATH] = (200, json.dumps(record(bucket["base"], **changes)).encode())
    assert channel.public_vscode("0.4.0rc7") is None


def test_install_hands_the_checked_file_to_the_editor(bucket, editors, capsys):
    _, ran = editors
    assert cli.main(["vscode", "install"]) == 0
    (cmd, data), = ran
    assert cmd[:2] == ["/usr/bin/code", "--install-extension"] and cmd[3] == "--force"
    assert cmd[2].endswith("kaos-pipeline-0.4.0-rc.7.vsix") and data == VSIX
    assert "Installed the KAOS extension 0.4.0-rc.7" in capsys.readouterr().out


def test_install_uses_the_first_editor_found_or_the_one_named(bucket, editors):
    found, ran = editors
    found.clear()
    found.update({"cursor": "/opt/cursor", "codium": "/usr/bin/codium"})
    assert cli.main(["vscode", "install"]) == 0
    assert cli.main(["vscode", "install", "--editor", "codium"]) == 0
    assert [cmd[0] for cmd, _ in ran] == ["/opt/cursor", "/usr/bin/codium"]


def test_install_without_an_editor_says_how_to_get_the_command(bucket, editors, capsys):
    found, ran = editors
    found.clear()
    assert cli.main(["vscode", "install"]) == 1
    assert "Install 'code' command in PATH" in capsys.readouterr().err and not ran


def test_install_refuses_a_file_that_is_not_the_published_one(bucket, editors, capsys):
    _, ran = editors
    bucket["rc/v0.4.0-rc.7/kaos-pipeline-0.4.0-rc.7.vsix"] = (200, VSIX + b" tampered")
    assert cli.main(["vscode", "install"]) == 1
    assert "does not match its published SHA-256" in capsys.readouterr().err and not ran


def test_install_when_this_kaos_lib_has_no_published_extension(bucket, editors, capsys, monkeypatch):
    _, ran = editors
    monkeypatch.setattr(cli, "__version__", "0.3.0")
    assert cli.main(["vscode", "install"]) == 1
    assert "no VS Code extension is published for kaos-lib 0.3.0" in capsys.readouterr().err and not ran


def test_dry_run_and_download_never_run_the_editor(bucket, editors, capsys, tmp_path):
    _, ran = editors
    assert cli.main(["vscode", "install", "--dry-run"]) == 0
    assert "would run: /usr/bin/code --install-extension kaos-pipeline-0.4.0-rc.7.vsix --force" in capsys.readouterr().out
    assert cli.main(["vscode", "install", "--download", str(tmp_path / "out")]) == 0
    path = capsys.readouterr().out.strip()
    assert path == str(tmp_path / "out/kaos-pipeline-0.4.0-rc.7.vsix") and open(path, "rb").read() == VSIX
    assert not ran


def test_a_failing_editor_is_reported(bucket, editors, capsys, monkeypatch):
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 3)
    assert cli.main(["vscode", "install"]) == 1
    assert "--install-extension failed (exit 3)" in capsys.readouterr().err
