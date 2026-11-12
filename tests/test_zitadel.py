"""Zitadel machine-key tokens (JWT-profile grant) and the peer credential chain (resolve_peer)."""
import json
import sys
import time

import jwt
import pytest
import requests

from conftest import rsa_key, write_machine_key
from fake_zitadel import FakeTokenEndpoint
from kaos_lib import credentials, zitadel
from kaos_lib.errors import AuthError

OWN = "http://b-lakefs.ml-b.svc.cluster.local"
SCOPE = ("openid email profile urn:zitadel:iam:org:projects:roles "
         "urn:zitadel:iam:org:project:id:321:aud")


def session_with(endpoint):
    s = requests.Session()
    s.mount("https://zitadel.test", endpoint)
    return s


# ------------------------------------------------------------------ mint
def test_mint_posts_a_jwt_profile_grant_with_the_right_assertion(zitadel_env):
    before = int(time.time())
    assert zitadel.mint_from_env() == "minted-token"
    (method, url, form), = zitadel_env.requests
    assert (method, url) == ("POST", "https://zitadel.test/oauth/v2/token")
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert form["scope"] == SCOPE
    header = jwt.get_unverified_header(form["assertion"])
    assert header["alg"] == "RS256" and header["kid"] == "kid-123"
    claims = jwt.decode(form["assertion"], rsa_key()[1], algorithms=["RS256"], audience="https://zitadel.test")
    assert claims["iss"] == claims["sub"] == "user-456"
    assert claims["aud"] == "https://zitadel.test"
    assert before <= claims["iat"] <= int(time.time()) and claims["exp"] == claims["iat"] + 60


def test_assertion_is_signed_by_the_machine_key_only(zitadel_env):
    from cryptography.hazmat.primitives.asymmetric import rsa
    zitadel.mint_from_env()
    signed = zitadel_env.requests[0][2]["assertion"]
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(signed, other, algorithms=["RS256"], audience="https://zitadel.test")


def test_key_file_is_read_again_on_every_mint(zitadel_env, tmp_path, monkeypatch):
    zitadel.mint_from_env()
    write_machine_key(tmp_path / "machine-key.json", keyId="kid-rotated")
    zitadel.mint_from_env()
    kids = [jwt.get_unverified_header(r[2]["assertion"])["kid"] for r in zitadel_env.requests]
    assert kids == ["kid-123", "kid-rotated"]


@pytest.mark.parametrize("content,fragment", [
    (None, "cannot read the Zitadel machine key"),
    ("not json", "is not JSON"),
    ("[1, 2]", "is not a Zitadel JSON key"),
    (json.dumps({"type": "application", "keyId": "k", "key": "x", "clientId": "c"}), "'application' key"),
    (json.dumps({"type": "serviceaccount", "key": "x", "userId": "u"}), "lacks keyId"),
    (json.dumps({"type": "serviceaccount", "keyId": "k", "userId": "u"}), "lacks key"),
    (json.dumps({"type": "serviceaccount", "keyId": "k", "key": "x"}), "lacks userId"),
    (json.dumps({}), "lacks keyId, key, userId"),
    (json.dumps({"type": "serviceaccount", "keyId": "k", "key": "not a pem", "userId": "u"}),
     "not a usable RSA private key"),
])
def test_key_file_errors_are_clear_and_never_call_zitadel(tmp_path, content, fragment):
    path = tmp_path / "key.json"
    if content is not None:
        path.write_text(content)
    endpoint = FakeTokenEndpoint()
    with pytest.raises(AuthError) as err:
        zitadel.mint(path, "zitadel.test", "321", session=session_with(endpoint))
    assert fragment in str(err.value) and endpoint.requests == []
    assert "BEGIN" not in str(err.value)            # never the key material in a message


def test_a_key_file_without_type_is_accepted(tmp_path):
    path = write_machine_key(tmp_path / "key.json", type=None)
    assert zitadel.mint(path, "zitadel.test", "321", session=session_with(FakeTokenEndpoint())) == "minted-token"


@pytest.mark.parametrize("status,body,fragment", [
    (400, {"error": "invalid_grant", "error_description": "assertion expired"},
     "(HTTP 400): invalid_grant: assertion expired"),
    (401, {"error": "invalid_client"}, "(HTTP 401): invalid_client"),
    (500, b"upstream connect error", "(HTTP 500): upstream connect error"),
    (403, b"", "(HTTP 403)"),
])
def test_token_error_responses(tmp_path, status, body, fragment):
    endpoint = FakeTokenEndpoint(status, body)
    with pytest.raises(AuthError) as err:
        zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321", session=session_with(endpoint))
    assert "Zitadel refused the machine-key token request" in str(err.value) and fragment in str(err.value)
    assert "eyJ" not in str(err.value)              # never the assertion in a message


@pytest.mark.parametrize("body", [{"token_type": "Bearer"}, {"access_token": ""}, b"<html>ok</html>", b"[]"])
def test_a_200_without_access_token_is_an_error(tmp_path, body):
    with pytest.raises(AuthError, match="without an access_token"):
        zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321",
                     session=session_with(FakeTokenEndpoint(200, body)))


class Flaky(FakeTokenEndpoint):
    """Fails ``times`` token requests with ``error`` (an exception) or ``status``, then answers like the base."""

    def __init__(self, times, error=None, status=None):
        super().__init__()
        self.times, self.error, self.fail_status = times, error, status

    def send(self, request, **kw):
        failing = len(self.requests) < self.times
        self.status = self.fail_status if failing and not self.error else 200
        resp = super().send(request, **kw)       # records the request either way
        if failing and self.error:
            raise self.error
        return resp


@pytest.fixture
def sleeps(monkeypatch):
    """The waits between token requests, recorded; nothing really sleeps."""
    waited = []
    monkeypatch.setattr(zitadel.time, "sleep", waited.append)
    return waited


def test_a_token_request_is_tried_again_after_connection_errors_and_waits_longer_each_time(tmp_path, sleeps, capsys):
    endpoint = Flaky(3, error=requests.ConnectionError("down"))
    token = zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321", session=session_with(endpoint))
    assert token == "minted-token" and len(endpoint.requests) == 4
    assert len(sleeps) == 3 and sleeps == sorted(sleeps) and sleeps[0] < sleeps[-1]
    err = capsys.readouterr().err
    assert err.count("Zitadel") == 3 and "tried again in" in err and "ConnectionError" in err


@pytest.mark.parametrize("error", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_a_timeout_or_dropped_connection_passes(tmp_path, sleeps, error):
    endpoint = Flaky(1, error=error)
    zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321", session=session_with(endpoint))
    assert len(sleeps) == 1


def test_each_try_carries_a_freshly_signed_assertion(tmp_path, sleeps, monkeypatch):
    monkeypatch.setattr(zitadel, "assertion", lambda key, domain, real=zitadel.assertion, clock=iter([1000, 1100, 1200]):
                        real(key, domain, now=next(clock)))
    endpoint = Flaky(2, error=requests.ConnectionError("down"))
    zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321", session=session_with(endpoint))
    iats = [jwt.decode(r[2]["assertion"], rsa_key()[1], algorithms=["RS256"], audience="https://zitadel.test",
                       options={"verify_exp": False})["iat"] for r in endpoint.requests]
    assert iats == [1000, 1100, 1200]


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_bad_gateway_or_busy_answer_is_tried_again(tmp_path, sleeps, status):
    endpoint = Flaky(2, status=status)
    assert zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321",
                        session=session_with(endpoint)) == "minted-token"
    assert len(sleeps) == 2


def test_unreachable_zitadel_is_an_auth_error_after_a_bounded_wait(tmp_path, sleeps):
    endpoint = Flaky(10 ** 6, error=requests.ConnectionError("down"))
    with pytest.raises(AuthError, match=r"^cannot reach Zitadel at https://zitadel.test/oauth/v2/token "
                                        r"\(ConnectionError\)\.$"):
        zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321", session=session_with(endpoint))
    assert 120 <= sum(sleeps) <= 180 and len(endpoint.requests) == len(sleeps) + 1


@pytest.mark.parametrize("status", [400, 401, 403])
def test_a_refused_credential_fails_at_once(tmp_path, sleeps, status):
    endpoint = FakeTokenEndpoint(status, {"error": "invalid_grant"})
    with pytest.raises(AuthError, match=f"HTTP {status}"):
        zitadel.mint(write_machine_key(tmp_path / "k.json"), "zitadel.test", "321", session=session_with(endpoint))
    assert sleeps == [] and len(endpoint.requests) == 1


@pytest.mark.parametrize("unset", ["ZITADEL_DOMAIN", "ZITADEL_MLFLOW_PROJECT_ID"])
def test_mint_from_env_names_what_is_missing(zitadel_env, monkeypatch, unset):
    monkeypatch.delenv(unset)
    with pytest.raises(AuthError, match=f"{unset} not set"):
        zitadel.mint_from_env()
    assert zitadel_env.requests == []


def test_missing_extra_is_a_clear_error(zitadel_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "jwt", None)          # `import jwt` now raises ImportError
    with pytest.raises(AuthError, match=r"pip install 'kaos-lib\[zitadel\]'"):
        zitadel.mint_from_env()
    with pytest.raises(AuthError, match=r"kaos-lib\[zitadel\]"):
        credentials.resolve_peer(OWN)
    assert zitadel_env.requests == []


def test_missing_extra_is_reported_before_a_bad_key_file(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "jwt", None)
    with pytest.raises(AuthError, match=r"kaos-lib\[zitadel\]"):
        zitadel.mint(tmp_path / "absent.json", "zitadel.test", "321")


def test_importing_the_package_does_not_need_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "jwt", None)
    import importlib
    import kaos_lib.zitadel
    importlib.reload(kaos_lib.zitadel)                    # the module imports PyJWT lazily


# ------------------------------------------------------------------ resolve_peer chain
def test_chain_bearer_env_comes_first(zitadel_env, monkeypatch):
    credentials.save_session(OWN, "session-token")
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "env-token")
    assert credentials.resolve_peer(OWN) == credentials.Credential(token="env-token")
    assert zitadel_env.requests == []                   # no mint when a bearer is given


def test_chain_machine_key_mint_before_session(zitadel_env):
    credentials.save_session(OWN, "session-token")
    assert credentials.resolve_peer(OWN) == credentials.Credential(token="minted-token")
    assert len(zitadel_env.requests) == 1


def test_chain_browser_session_last():
    credentials.save_session(OWN, "session-token")
    assert credentials.resolve_peer(OWN) == credentials.Credential(token="session-token")
    assert credentials.resolve_peer(OWN + "/") == credentials.Credential(token="session-token")


def test_chain_session_is_the_own_lakefs_one():
    credentials.save_session("https://somewhere-else.example", "other")
    with pytest.raises(AuthError):
        credentials.resolve_peer(OWN)


def test_chain_never_uses_the_access_key(monkeypatch):
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    with pytest.raises(AuthError) as err:
        credentials.resolve_peer(OWN)
    assert "LAKEFS_ACCESS_KEY is never sent to another project" in str(err.value)
    assert "kaosctl login" in str(err.value)


def test_chain_access_key_does_not_shadow_the_other_steps(zitadel_env, monkeypatch):
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    cred = credentials.resolve_peer(OWN)
    assert (cred.token, cred.access_key, cred.secret_key) == ("minted-token", None, None)
    assert credentials.resolve(OWN).access_key == "AK-B"     # the own lakeFS keeps using the key


def test_chain_a_broken_machine_key_is_an_error_not_a_fallback(zitadel_env, tmp_path, monkeypatch):
    credentials.save_session(OWN, "session-token")
    monkeypatch.setenv("ZITADEL_MACHINE_KEY_FILE", str(tmp_path / "absent.json"))
    with pytest.raises(AuthError, match="cannot read the Zitadel machine key"):
        credentials.resolve_peer(OWN)
