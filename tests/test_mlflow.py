"""kaos_lib.mlflow: the credential chain, the org-project audience, refresh, the ``zitadel`` auth provider."""
import http.server
import importlib.metadata
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import types

import jwt
import pytest
import requests

from kaos_lib import credentials
from kaos_lib import mlflow as kmlflow
from kaos_lib.errors import AuthError, ConfigError, KaosLibError

LAKEFS = "https://lakefs-b.example"
AUD_SCOPE = "urn:zitadel:iam:org:project:id:321:aud"


def session_token(**claims):
    return jwt.encode({"sub": "person", **claims}, "not-checked-here-" * 4, algorithm="HS256")


@pytest.fixture
def laptop(monkeypatch):
    """A laptop inside an app clone: lakeFS URL and login settings known, ``kaosctl login`` done."""
    monkeypatch.setenv("LAKEFS_ENDPOINT", LAKEFS)
    monkeypatch.setenv("KUBECORE_ML_OIDC_PROJECT_ID", "321")

    def login(token):
        credentials.save_session(LAKEFS, token)
        return token
    return login


def bearer(auth):
    req = requests.Request("GET", "https://mlflow.example/api/2.0/mlflow/experiments/search").prepare()
    return auth(req).headers["Authorization"]


# ------------------------------------------------------------------ chain order
def test_explicit_token_wins_over_everything(zitadel_env, laptop, monkeypatch):
    laptop(session_token(aud=["321"]))
    monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "env-token")
    kmlflow._source.explicit = "explicit-token"
    assert kmlflow.token() == "explicit-token"
    assert zitadel_env.requests == []


def test_tracking_token_env_comes_before_the_machine_key(zitadel_env, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "env-token")
    assert kmlflow.token() == "env-token"
    assert zitadel_env.requests == []


def test_machine_key_comes_before_the_laptop_session(zitadel_env, laptop):
    laptop(session_token(aud=["321"]))
    assert kmlflow.token() == "minted-token"
    assert len(zitadel_env.requests) == 1


def test_laptop_session_is_the_last_link(laptop):
    token = laptop(session_token(aud=["321", "other"], exp=int(time.time()) + 3600))
    assert kmlflow.token() == token


def test_empty_chain_says_what_to_do():
    with pytest.raises(AuthError, match="no MLflow credential.*MLFLOW_TRACKING_TOKEN.*kaosctl login"):
        kmlflow.token()


# ------------------------------------------------------------------ audience
def test_machine_token_is_requested_with_the_org_project_audience(zitadel_env):
    kmlflow.token()
    (_, url, form), = zitadel_env.requests
    assert url == "https://zitadel.test/oauth/v2/token"
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert AUD_SCOPE in form["scope"].split()
    assert "urn:zitadel:iam:org:projects:roles" in form["scope"].split()


def test_machine_key_without_the_project_id_is_refused(zitadel_env, monkeypatch):
    monkeypatch.delenv("ZITADEL_MLFLOW_PROJECT_ID")
    with pytest.raises(AuthError, match="ZITADEL_MLFLOW_PROJECT_ID not set"):
        kmlflow.token()
    assert zitadel_env.requests == []


def test_session_without_the_org_project_audience_is_refused(laptop):
    laptop(session_token(aud="console-project"))
    with pytest.raises(AuthError, match=r"lacks the organisation project audience \(321\).*kaosctl login"):
        kmlflow.token()


def test_expired_session_asks_for_a_new_login(laptop):
    laptop(session_token(aud=["321"], exp=int(time.time()) - 5))
    with pytest.raises(AuthError, match="session has expired"):
        kmlflow.token()


def test_opaque_session_token_is_passed_on_unchecked(laptop):
    laptop("opaque-token")
    assert kmlflow.token() == "opaque-token"


def test_session_of_another_lakefs_is_not_used(laptop):
    credentials.save_session("https://lakefs-other.example", session_token(aud=["321"]))
    with pytest.raises(AuthError, match="no MLflow credential"):
        kmlflow.token()


# ------------------------------------------------------------------ refresh
def test_machine_token_is_cached_then_minted_again_before_expiry(zitadel_env, monkeypatch):
    now = [1000.0]
    source = kmlflow.TokenSource(clock=lambda: now[0])
    zitadel_env.body = {"access_token": "first", "expires_in": 600}
    assert source.token() == "first"
    now[0] += 600 - kmlflow.REFRESH_LEEWAY - 1                 # still inside the leeway: cached
    zitadel_env.body = {"access_token": "second", "expires_in": 600}
    assert source.token() == "first"
    assert len(zitadel_env.requests) == 1
    now[0] += 1                                                # leeway reached: minted again
    assert source.token() == "second"
    assert len(zitadel_env.requests) == 2


def test_answer_without_expires_in_is_treated_as_short_lived(zitadel_env):
    now = [0.0]
    source = kmlflow.TokenSource(clock=lambda: now[0])
    zitadel_env.body = {"access_token": "t"}
    source.token()
    now[0] = kmlflow.DEFAULT_LIFETIME - kmlflow.REFRESH_LEEWAY
    source.token()
    assert len(zitadel_env.requests) == 2


def test_refused_mint_is_one_clear_error(zitadel_env):
    zitadel_env.status, zitadel_env.body = 400, {"error": "invalid_grant", "error_description": "key revoked"}
    with pytest.raises(AuthError, match=r"HTTP 400\): invalid_grant: key revoked"):
        kmlflow.token()


# ------------------------------------------------------------------ the auth provider
def test_entry_point_zitadel_is_registered_and_sends_the_bearer(zitadel_env):
    try:
        eps = importlib.metadata.entry_points(group="mlflow.request_auth_provider")
    except TypeError:   # Python 3.9
        eps = importlib.metadata.entry_points().get("mlflow.request_auth_provider", [])
    found = {ep.name: ep for ep in eps}
    if "zitadel" not in found and not any(d.metadata["Name"] == "kaos-lib" for d in importlib.metadata.distributions()):
        pytest.skip("kaos-lib is not installed (pip install -e .), so its entry points are not registered")
    provider_class = found["zitadel"].load()
    assert provider_class is kmlflow.ZitadelRequestAuthProvider
    provider = provider_class()
    assert provider.get_name() == "zitadel"
    assert bearer(provider.get_auth()) == "Bearer minted-token"


def test_every_request_asks_the_chain_again(monkeypatch):
    auth = kmlflow.ZitadelRequestAuthProvider().get_auth()
    monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "one")
    assert bearer(auth) == "Bearer one"
    monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "two")
    assert bearer(auth) == "Bearer two"


# ------------------------------------------------------------------ mlflow()
@pytest.fixture
def fake_mlflow_module(monkeypatch):
    calls = {}

    class Client:
        def __init__(self, tracking_uri=None):
            self.tracking_uri = tracking_uri

    module = types.ModuleType("mlflow")
    module.set_tracking_uri = lambda uri: calls.setdefault("uri", uri)
    tracking = types.ModuleType("mlflow.tracking")
    tracking.MlflowClient = Client
    module.tracking = tracking
    monkeypatch.setitem(sys.modules, "mlflow", module)
    monkeypatch.setitem(sys.modules, "mlflow.tracking", tracking)
    return calls


def test_mlflow_sets_uri_and_auth_and_returns_a_client(fake_mlflow_module, zitadel_env, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.ml-b.svc:5000")
    client = kmlflow.mlflow()
    assert client.tracking_uri == fake_mlflow_module["uri"] == "http://mlflow.ml-b.svc:5000"
    assert os.environ["MLFLOW_TRACKING_AUTH"] == "zitadel"
    assert len(zitadel_env.requests) == 1                      # the chain was asked up front


def test_mlflow_explicit_uri_and_token(fake_mlflow_module):
    client = kmlflow.mlflow("https://mlflow-b.example", token="explicit")
    assert client.tracking_uri == "https://mlflow-b.example"
    assert kmlflow.token() == "explicit"


def test_mlflow_without_a_credential_fails_before_any_work(fake_mlflow_module, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow")
    with pytest.raises(AuthError, match="no MLflow credential"):
        kmlflow.mlflow()
    assert "uri" not in fake_mlflow_module


def test_mlflow_without_a_tracking_uri(fake_mlflow_module, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "t")
    with pytest.raises(ConfigError, match="MLFLOW_TRACKING_URI"):
        kmlflow.mlflow()


def test_missing_mlflow_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "mlflow", None)   # import mlflow -> ImportError
    with pytest.raises(KaosLibError, match=r"pip install 'kaos-lib\[mlflow\]'"):
        kmlflow.mlflow("http://mlflow", token="t")


def test_importing_the_module_does_not_import_mlflow():
    import kaos_lib
    src = str(pathlib.Path(kaos_lib.__file__).parent.parent)
    code = "import sys, kaos_lib.mlflow, kaos_lib.lock, kaos_lib.runtime; print('mlflow' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": src})
    assert out.stdout.strip() == "False"


# ------------------------------------------------------------------ real MLflow (mlflow-skinny installed)
class _Recorder(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def _answer(self):
        type(self).seen.append((self.command, self.path, self.headers.get("Authorization")))
        body = json.dumps({"error_code": "RESOURCE_DOES_NOT_EXIST", "message": "no such experiment"}).encode()
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = _answer

    def log_message(self, *args):
        pass


def test_real_mlflow_sends_the_chain_bearer_through_the_plugin(zitadel_env, monkeypatch):
    pytest.importorskip("mlflow")
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Recorder.seen = []
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    try:
        client = kmlflow.mlflow(f"http://127.0.0.1:{server.server_address[1]}")
        assert client.get_experiment_by_name("nothing-here") is None
    finally:
        server.shutdown()
        server.server_close()
    assert _Recorder.seen
    assert {auth for _, _, auth in _Recorder.seen} == {"Bearer minted-token"}


def test_real_mlflow_registry_finds_the_zitadel_provider(zitadel_env):
    pytest.importorskip("mlflow")
    from mlflow.tracking.request_auth.registry import fetch_auth
    assert bearer(fetch_auth("zitadel")) == "Bearer minted-token"
