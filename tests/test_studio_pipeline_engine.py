"""The platform's pipeline engine on a laptop (PRD-HPC-1461 D-79 step 7): which release, a checked download, an
environment inside the repository, and `kaosctl render` / `kaosctl step run` going through it for an app that holds
no copy of the engine."""
import hashlib
import io
import pathlib
import zipfile

import pytest
import requests

from kaos_lib import cli
from kaos_lib.errors import KaosLibError
from kaos_lib.studio import pipeline_engine as pe

import studio_helpers as h

WHEEL = "kaos_pipeline_engine-0.1.0-py3-none-any.whl"
URL = "https://packages.example/kaos-pipeline-engine/" + WHEEL

RENDER = '''import argparse, os, pathlib, sys
p = argparse.ArgumentParser(); p.add_argument("pipeline"); p.add_argument("--repo"); p.add_argument("--profile")
a = p.parse_args()
assert sys.flags.isolated, "the engine runs isolated from the app's folders"
out = pathlib.Path(a.repo) / "out"; out.mkdir(exist_ok=True)
(out / "raw-workflow-template.yaml").write_text("profile: %s\\nconfig: %s\\n" % (a.profile, os.environ["KUBECORE_CONFIG_DIR"]))
print("rendered by the fake engine")
'''
COMPOSE = '''import argparse, os
def main(argv):
    p = argparse.ArgumentParser(); p.add_argument("--output", required=True); p.add_argument("overrides", nargs="*")
    a = p.parse_args(argv)
    text = "summary:\\n  label: Data summary\\ndata:\\n  seed: 42\\nprofile: %s\\n" % os.environ["KUBECORE_SCHEMA_PROFILE"]
    for token in a.overrides:
        text += token.replace("=", ": ", 1) + "\\n"
    open(a.output, "w").write(text)
'''


def wheel_bytes() -> bytes:
    """A tiny wheel with the engine's layout and no dependencies, so it installs offline."""
    files = {
        "kaos_engine/__init__.py": "", "kaos_engine/render.py": RENDER,
        "kaos_pipeline_engine/__init__.py": "", "kaos_pipeline_engine/kubecore/__init__.py": "",
        "kaos_pipeline_engine/kubecore/compose.py": COMPOSE,
        "kaos_pipeline_engine-0.1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: kaos-pipeline-engine\nVersion: 0.1.0\n",
        "kaos_pipeline_engine-0.1.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = "".join(f"{name},,\n" for name in files) + "kaos_pipeline_engine-0.1.0.dist-info/RECORD,,\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
        z.writestr("kaos_pipeline_engine-0.1.0.dist-info/RECORD", record)
    return buf.getvalue()


BODY = wheel_bytes()
SHA = hashlib.sha256(BODY).hexdigest()
PINNED = f"{URL}#sha256={SHA}"


class Server:
    """A stand-in for `requests.get`: serves the wheel and counts the downloads."""
    def __init__(self, body=BODY, status=200, error=None):
        self.body, self.status, self.error, self.calls = body, status, error, []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        resp = requests.Response()
        resp.status_code, resp.raw = self.status, io.BytesIO(self.body)
        return resp


# ------------------------------------------------------------------------------------------------ which release

def test_the_flag_wins_then_the_environment_then_the_context_file(tmp_path):
    ctx = tmp_path / "pipeline-context.yaml"
    ctx.write_text(f"engine:\n  version: 0.1.0-dev.abc\n  wheel: {URL}\n  wheelSha256: {SHA}\n")
    assert pe.resolve_pin(PINNED, str(ctx), {}).source == "--engine-wheel"
    assert pe.resolve_pin(None, str(ctx), {pe.WHEEL_ENV: PINNED}).source == "$KAOS_ENGINE_WHEEL"
    pin = pe.resolve_pin(None, str(ctx), {})
    assert (pin.url, pin.sha256, pin.version, pin.wheel_name) == (URL, SHA, "0.1.0-dev.abc", WHEEL)


def test_a_context_wheel_may_carry_its_checksum_in_the_url(tmp_path):
    ctx = tmp_path / "c.yaml"
    ctx.write_text(f"engine:\n  wheel: '{PINNED}'\n")
    assert pe.resolve_pin(None, str(ctx), {}).sha256 == SHA


@pytest.mark.parametrize("text,said", [
    (URL, "needs its SHA-256"), (URL + "#sha256=abc", "needs its SHA-256"),
    ("http://packages.example/" + WHEEL + "#sha256=" + "0" * 64, "must be an https URL"),
    ("https://packages.example/engine.tar.gz#sha256=" + "0" * 64, "does not name a wheel"),
    ("/tmp/" + WHEEL + "#sha256=" + "0" * 64, "must be an https URL"),
])
def test_a_wheel_that_cannot_be_checked_is_refused(text, said):
    with pytest.raises(KaosLibError, match=said):
        pe.resolve_pin(text, None, {})


def test_no_engine_says_how_to_give_one(tmp_path):
    with pytest.raises(KaosLibError, match="no pipeline engine was given.*--context"):
        pe.resolve_pin(None, None, {})
    ctx = tmp_path / "c.yaml"
    ctx.write_text("kaosLib:\n  spec: kaos-lib==0.4.0\n")
    with pytest.raises(KaosLibError, match="has not pinned an engine"):
        pe.resolve_pin(None, str(ctx), {})


# ------------------------------------------------------------------------------------------------ the download

def test_the_wheel_is_downloaded_once_checked_and_kept_inside_the_repository(tmp_path):
    home, server = pe.engine_home(tmp_path), Server()
    pin = pe.resolve_pin(PINNED, None, {})
    wheel = pe.fetch(pin, home, server)
    assert wheel == tmp_path / ".kaos/engine/wheels" / SHA / WHEEL and wheel.read_bytes() == BODY
    assert (home / ".gitignore").read_text() == "*\n"
    assert pe.fetch(pin, home, server) == wheel and len(server.calls) == 1, "the second time nothing is downloaded"


def test_a_wrong_checksum_installs_nothing_and_keeps_nothing(tmp_path):
    home = pe.engine_home(tmp_path)
    pin = pe.resolve_pin(PINNED, None, {})
    with pytest.raises(KaosLibError, match="has SHA-256 .* Nothing was installed"):
        pe.fetch(pin, home, Server(body=BODY + b"tampered"))
    assert not list((home / "wheels").rglob("*.whl")) and not list((home / "wheels").rglob("*.part"))


def test_a_kept_wheel_that_was_altered_is_downloaded_again(tmp_path):
    home, server = pe.engine_home(tmp_path), Server()
    pin = pe.resolve_pin(PINNED, None, {})
    wheel = pe.fetch(pin, home, server)
    wheel.write_bytes(b"altered")
    assert pe.fetch(pin, home, server).read_bytes() == BODY and len(server.calls) == 2


def test_a_failed_download_says_so_plainly(tmp_path):
    home, pin = pe.engine_home(tmp_path), pe.resolve_pin(PINNED, None, {})
    with pytest.raises(KaosLibError, match="HTTP 404"):
        pe.fetch(pin, home, Server(status=404))
    with pytest.raises(KaosLibError, match="cannot download.*ConnectionError"):
        pe.fetch(pin, home, Server(error=requests.ConnectionError("no route")))


def test_a_download_that_is_too_large_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "MAX_WHEEL_BYTES", 10)
    with pytest.raises(KaosLibError, match="larger than"):
        pe.fetch(pe.resolve_pin(PINNED, None, {}), pe.engine_home(tmp_path), Server())


# ------------------------------------------------------------------------------------------------ profile, commands

def test_the_profile_is_the_flag_the_environment_or_read_from_the_config(tmp_path):
    assert pe.profile_of(tmp_path, None, {}) == "hera"
    (tmp_path / "config").mkdir()
    (tmp_path / "config/quantization.yaml").write_text("quantization: {}\n")
    assert pe.profile_of(tmp_path, None, {}) == "yolo"
    assert pe.profile_of(tmp_path, "hera", {}) == "hera"
    assert pe.profile_of(tmp_path, None, {pe.PROFILE_ENV: "hera"}) == "hera"
    with pytest.raises(KaosLibError, match="unknown profile"):
        pe.profile_of(tmp_path, "nope", {})


def test_the_engine_always_runs_isolated_from_the_apps_folders(tmp_path):
    py = tmp_path / "python"
    assert pe.render_command(py, "hera")[1:4] == ["-I", "-m", "kaos_engine.render"]
    cmd = pe.compose_command(py, ["train.epochs=5"], tmp_path / "params.yaml")
    assert cmd[1:3] == ["-I", "-c"] and cmd[-3:] == ["train.epochs=5", "--output", str(tmp_path / "params.yaml")]


# ------------------------------------------------------------------------------------------------ end to end

@pytest.fixture
def app(tmp_path, monkeypatch):
    """An app as the new templates ship it: pipeline.py, config/ and steps/, and no kubecore/ folder."""
    root = h.template_repo(tmp_path / "app")
    for rel in ("kubecore/compose.py", "kubecore/__init__.py", "steps/compose_and_validate/Dockerfile"):
        (root / rel).unlink()
    (root / "kubecore").rmdir()
    (root / "steps/compose_and_validate").rmdir()
    (root / "config").mkdir()
    h.fake_venv(root / "steps/data_summary")
    server = Server()
    monkeypatch.setattr(pe.requests, "get", server)
    monkeypatch.setenv(pe.WHEEL_ENV, PINNED)
    monkeypatch.delenv(pe.PROFILE_ENV, raising=False)
    return root


def test_kaosctl_render_fetches_the_pinned_engine_and_renders_with_it(app, capsys):
    assert cli.main(["render", str(app)]) == 0
    out = capsys.readouterr().out
    assert "rendered by the fake engine" in out and "Rendered: out/raw-workflow-template.yaml" in out
    raw = (app / "out/raw-workflow-template.yaml").read_text()
    assert "profile: hera" in raw and f"config: {app / 'config'}" in raw
    assert (app / ".kaos/engine/.venv/pyvenv.cfg").is_file(), "the engine lives inside the repository"
    assert cli.main(["render", str(app), "--profile", "yolo"]) == 0
    assert "profile: yolo" in (app / "out/raw-workflow-template.yaml").read_text()
    assert "ready in .kaos/engine" not in capsys.readouterr().out, "the second run sets nothing up"


def test_kaosctl_step_run_composes_with_the_engine_when_the_app_has_no_copy(app, capsys):
    assert cli.main(["step", "run", "data-summary", str(app), "--set", "data.seed=7"]) == 0
    assert "Data summary: seed=42" in capsys.readouterr().out, "the step ran on the engine's composed params"
    params = (app / ".kaos/local/params.yaml").read_text()
    assert "profile: hera" in params and "data.seed: 7" in params, "composed by the engine, with the override"


def test_kaosctl_render_needs_a_pipeline(tmp_path, capsys):
    assert cli.main(["render", str(tmp_path)]) == 1
    assert "has no pipeline.py" in capsys.readouterr().err
