"""The tracker's bearer comes from a file the platform replaces (MLFLOW_TRACKING_TOKEN_FILE): the library reads it at
every call of its own and keeps MLFLOW_TRACKING_TOKEN in step for code that uses the mlflow client directly."""
import http.server
import json
import logging
import os
import threading
import time

import pytest

from kaos_lib import mlflow as kmlflow
from kaos_lib import trackertoken

FIRST, SECOND = "made-up-token-one", "made-up-token-two"


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "tracker-token"
    path.write_text(FIRST + "\n")
    monkeypatch.setenv(trackertoken.FILE_ENV, str(path))
    yield path
    trackertoken.unwatch()


def replace(path, text):
    """As the platform does: write beside it, then rename over it."""
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(text)
    os.replace(tmp, path)


def test_a_library_call_reads_the_file_and_sets_the_environment(token_file):
    assert kmlflow.token() == FIRST
    assert os.environ["MLFLOW_TRACKING_TOKEN"] == FIRST


def test_a_file_replaced_mid_run_is_picked_up_by_the_next_call_and_by_the_environment(token_file):
    assert kmlflow.token() == FIRST
    replace(token_file, SECOND + "\n")
    assert kmlflow.token() == SECOND
    assert os.environ["MLFLOW_TRACKING_TOKEN"] == SECOND


def test_the_bearer_of_every_request_is_the_current_file(token_file):
    auth = kmlflow.ZitadelRequestAuthProvider().get_auth()
    from test_mlflow import bearer
    assert bearer(auth) == f"Bearer {FIRST}"
    replace(token_file, SECOND)
    assert bearer(auth) == f"Bearer {SECOND}"


@pytest.mark.parametrize("bad", ["", "  \n", None])
def test_a_missing_or_empty_file_keeps_the_last_good_value(token_file, bad):
    assert kmlflow.token() == FIRST
    if bad is None:
        token_file.unlink()
    else:
        token_file.write_text(bad)
    assert kmlflow.token() == FIRST
    assert os.environ["MLFLOW_TRACKING_TOKEN"] == FIRST


def test_a_file_that_is_a_folder_or_not_text_does_not_crash(token_file, tmp_path, monkeypatch):
    assert kmlflow.token() == FIRST
    token_file.write_bytes(b"\xff\xfe\x00")
    assert kmlflow.token() == FIRST
    monkeypatch.setenv(trackertoken.FILE_ENV, str(tmp_path))
    assert kmlflow.token() == FIRST


def test_without_the_file_variable_the_environment_alone_decides(monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "from-env")
    assert kmlflow.token() == "from-env"
    trackertoken.refresh()
    assert os.environ["MLFLOW_TRACKING_TOKEN"] == "from-env"
    assert trackertoken.watch() is False


def test_the_token_never_appears_in_a_log_line_or_an_error(token_file, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    kmlflow.token()
    token_file.write_bytes(b"\xff\xfe")
    trackertoken.refresh()
    token_file.unlink()
    trackertoken.refresh()
    out = capsys.readouterr()
    assert FIRST not in caplog.text and FIRST not in out.out + out.err


def test_a_thread_keeps_the_environment_in_step_while_the_step_runs(token_file, monkeypatch):
    monkeypatch.setattr(trackertoken, "EVERY_SECONDS", 0.05)
    assert trackertoken.watch() is True
    assert trackertoken.watch() is False            # once
    replace(token_file, SECOND)
    deadline = time.time() + 5
    while os.environ.get("MLFLOW_TRACKING_TOKEN") != SECOND and time.time() < deadline:
        time.sleep(0.02)
    assert os.environ["MLFLOW_TRACKING_TOKEN"] == SECOND
    trackertoken.unwatch()
    assert not any(t.name == trackertoken.THREAD_NAME for t in threading.enumerate())


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def _answer(self):
        type(self).seen.append(self.headers.get("Authorization"))
        body = json.dumps({"error_code": "RESOURCE_DOES_NOT_EXIST", "message": "none"}).encode()
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *args):
        pass


def test_the_mlflow_client_used_directly_sends_the_replaced_token(token_file, monkeypatch):
    """No kaos_lib auth plugin here: the client reads MLFLOW_TRACKING_TOKEN itself, at every request."""
    pytest.importorskip("mlflow")
    from mlflow.tracking import MlflowClient
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Recorder.seen = []
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    monkeypatch.setattr(trackertoken, "EVERY_SECONDS", 0.05)
    try:
        client = MlflowClient(tracking_uri=f"http://127.0.0.1:{server.server_address[1]}")
        trackertoken.refresh()
        trackertoken.watch()
        assert client.get_experiment_by_name("nothing-here") is None
        replace(token_file, SECOND)
        deadline = time.time() + 5
        while os.environ.get("MLFLOW_TRACKING_TOKEN") != SECOND and time.time() < deadline:
            time.sleep(0.02)
        assert client.get_experiment_by_name("nothing-here") is None
    finally:
        server.shutdown()
        server.server_close()
    assert _Recorder.seen[0] == f"Bearer {FIRST}" and _Recorder.seen[-1] == f"Bearer {SECOND}"
