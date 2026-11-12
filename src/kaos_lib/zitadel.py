"""A short-lived Zitadel access token from a machine key (JWT-profile grant): another project's lakeFS, MLflow.

Pipeline steps get ``ZITADEL_MACHINE_KEY_FILE`` (Zitadel's JSON key: ``type``, ``keyId``, ``key``, ``userId``),
``ZITADEL_DOMAIN`` and ``ZITADEL_MLFLOW_PROJECT_ID``. The token is minted the way the template's
``mint_wallet`` does it: an RS256 assertion ``iss = sub = userId``, ``aud = https://<domain>``, header
``kid = keyId``, POSTed to ``https://<domain>/oauth/v2/token`` with the project-audience scope.

Needs the optional extra ``kaos-lib[zitadel]`` (PyJWT + cryptography), imported only when a token is minted.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Optional

import requests

from .errors import AuthError

KEY_FILE_ENV, DOMAIN_ENV, PROJECT_ENV = "ZITADEL_MACHINE_KEY_FILE", "ZITADEL_DOMAIN", "ZITADEL_MLFLOW_PROJECT_ID"
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
BASE_SCOPE = "openid email profile urn:zitadel:iam:org:projects:roles"
ASSERTION_LIFETIME = 60
TIMEOUT = 30
RETRY_WAITS = (5, 10, 20, 30, 30, 30, 30)      # seconds before each new try: about 2.5 minutes in all
RETRY_STATUSES = (502, 503, 504)               # answers that can pass; a 4xx (a refused key) is never tried again


def _jwt():
    try:
        import jwt
    except ImportError:
        raise AuthError("minting a Zitadel token needs the zitadel extra: "
                        "pip install 'kaos-lib[zitadel]' (PyJWT and cryptography).") from None
    return jwt


def _session() -> requests.Session:
    return requests.Session()


def scope(project_id: str) -> str:
    return f"{BASE_SCOPE} urn:zitadel:iam:org:project:id:{project_id}:aud"


def load_key(key_file) -> dict:
    """The machine key (``keyId``, ``key``, ``userId``) from Zitadel's JSON key file; AuthError saying what is wrong."""
    path = pathlib.Path(key_file)
    try:
        key = json.loads(path.read_text())
    except OSError as exc:
        raise AuthError(f"cannot read the Zitadel machine key {path} ({KEY_FILE_ENV}): {exc.strerror or exc}.") from None
    except ValueError:
        raise AuthError(f"the Zitadel machine key {path} ({KEY_FILE_ENV}) is not JSON.") from None
    if not isinstance(key, dict):
        raise AuthError(f"the Zitadel machine key {path} ({KEY_FILE_ENV}) is not a Zitadel JSON key.")
    if key.get("type") not in (None, "serviceaccount"):
        raise AuthError(f"the Zitadel key {path} is a {key.get('type')!r} key; a service-account (machine) key is needed.")
    missing = [f for f in ("keyId", "key", "userId") if not key.get(f)]
    if missing:
        raise AuthError(f"the Zitadel machine key {path} ({KEY_FILE_ENV}) lacks {', '.join(missing)}.")
    return key


def assertion(key: dict, domain: str, now: Optional[int] = None) -> str:
    """The signed RS256 JWT-profile assertion for ``key`` at ``https://<domain>``."""
    jwt = _jwt()
    now = int(time.time()) if now is None else now
    claims = {"iss": key["userId"], "sub": key["userId"], "aud": f"https://{domain}",
              "iat": now, "exp": now + ASSERTION_LIFETIME}
    try:
        return jwt.encode(claims, key["key"], algorithm="RS256", headers={"kid": key["keyId"]})
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise AuthError(f"the Zitadel machine key {key['keyId']} is not a usable RSA private key "
                        f"({exc.__class__.__name__}).") from None


def grant(key_file, domain: str, project_id: str, session: Optional[requests.Session] = None) -> dict:
    """Zitadel's token response (``access_token``, ``expires_in``, ...) for the machine user of ``key_file``.

    POSTs the JWT-profile grant to ``https://<domain>/oauth/v2/token`` with the project-audience scope. A request
    that fails in a way that can pass (no connection, a timeout, HTTP 502/503/504) is tried again after a growing
    wait, for about 2.5 minutes (``RETRY_WAITS``); a refusal (4xx) is raised at once.
    """
    _jwt()   # the missing extra is reported first, before any key-file problem
    key = load_key(key_file)
    url = f"https://{domain}/oauth/v2/token"
    for wait in (*RETRY_WAITS, None):
        signed = assertion(key, domain)      # signed again each try: an assertion is good for a minute only
        try:
            resp = (session or _session()).post(url, timeout=TIMEOUT, data={
                "grant_type": GRANT_TYPE, "scope": scope(project_id), "assertion": signed})
            what = f"answered HTTP {resp.status_code}" if resp.status_code in RETRY_STATUSES else None
        except requests.RequestException as exc:
            resp, what = None, f"could not be reached ({exc.__class__.__name__})"
            if wait is None:
                raise AuthError(f"cannot reach Zitadel at {url} ({exc.__class__.__name__}).") from None
        if what is None or wait is None:
            break
        print(f"kaos-lib: Zitadel {what}; the sign-in is tried again in {wait} seconds.", file=sys.stderr, flush=True)
        time.sleep(wait)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if resp.status_code != 200:
        reason = ": ".join(str(body[k]) for k in ("error", "error_description") if body.get(k)) \
            or (resp.text or "")[:200]
        raise AuthError(f"Zitadel refused the machine-key token request (HTTP {resp.status_code}): {reason}")
    if not body.get("access_token"):
        raise AuthError(f"Zitadel answered {url} without an access_token.")
    return body


def mint(key_file, domain: str, project_id: str, session: Optional[requests.Session] = None) -> str:
    """An access token for the machine user of ``key_file`` (see ``grant``)."""
    return grant(key_file, domain, project_id, session)["access_token"]


def env_settings() -> tuple:
    """``(key_file, domain, project_id)`` from ZITADEL_MACHINE_KEY_FILE, ZITADEL_DOMAIN and ZITADEL_MLFLOW_PROJECT_ID."""
    missing = [e for e in (KEY_FILE_ENV, DOMAIN_ENV, PROJECT_ENV) if not os.environ.get(e)]
    if missing:
        raise AuthError(f"cannot mint a Zitadel token: {', '.join(missing)} not set "
                        f"(a machine-key token needs {KEY_FILE_ENV}, {DOMAIN_ENV} and {PROJECT_ENV}).")
    return os.environ[KEY_FILE_ENV], os.environ[DOMAIN_ENV], os.environ[PROJECT_ENV]


def mint_from_env() -> str:
    """``mint`` from ZITADEL_MACHINE_KEY_FILE, ZITADEL_DOMAIN and ZITADEL_MLFLOW_PROJECT_ID (all required)."""
    return mint(*env_settings())
