"""MLflow for KAOS: the project's tracking server, authenticated by one credential chain.

``mlflow()`` points the ``mlflow`` module at the tracking URI (``$MLFLOW_TRACKING_URI``), selects the
``zitadel`` request-auth provider (``MLFLOW_TRACKING_AUTH=zitadel``) and returns an ``MlflowClient``. The
provider ships with kaos-lib (entry point ``mlflow.request_auth_provider``: ``zitadel``), so any step with
``MLFLOW_TRACKING_AUTH=zitadel`` in its environment is authenticated without calling anything.

The bearer comes from the first link of the chain that has one:

  1. an explicit token: ``mlflow(token=...)``, else ``$MLFLOW_TRACKING_TOKEN`` (HPC (Slurm) jobs get one);
  2. the step's own machine key: ``ZITADEL_MACHINE_KEY_FILE`` + ``ZITADEL_DOMAIN`` +
     ``ZITADEL_MLFLOW_PROJECT_ID``, minted with the org project's audience scope
     (``urn:zitadel:iam:org:project:id:<id>:aud``) and minted again ``REFRESH_LEEWAY`` seconds before it
     expires, so a long run never sends an expired token;
  3. the laptop session of ``kaosctl login`` (the same browser login as for lakeFS), which carries the org
     project's audience when it was made inside an app clone.

Project MLflow accepts only tokens whose audience is the organisation's Zitadel project (``OIDC_AUDIENCE``).

Needs the optional extra ``kaos-lib[mlflow]`` (mlflow-skinny, PyJWT, cryptography); ``mlflow`` is imported
only when ``mlflow()`` is called.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from typing import Callable, Optional

from requests.auth import AuthBase

from . import credentials, zitadel
from .config import oidc_settings, resolve_endpoint
from .errors import AuthError, ConfigError, KaosLibError

PROVIDER = "zitadel"
TRACKING_URI_ENV, TOKEN_ENV, AUTH_ENV = "MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_TOKEN", "MLFLOW_TRACKING_AUTH"
REFRESH_LEEWAY = 120          # seconds before expiry at which a machine-key token is minted again
DEFAULT_LIFETIME = 300        # assumed lifetime when Zitadel's answer carries no expires_in


def _import_mlflow():
    try:
        import mlflow
    except ImportError:
        raise KaosLibError("kaos_lib.mlflow needs the mlflow extra: pip install 'kaos-lib[mlflow]'.") from None
    return mlflow


def _claims(token: str) -> Optional[dict]:
    """The unverified payload of a JWT, or None for an opaque token (only read to say what is wrong)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _project_id() -> Optional[str]:
    """The org project a token must be audienced to, when known (step env, else the app's login settings)."""
    return os.environ.get(zitadel.PROJECT_ENV) or oidc_settings()[2]


class TokenSource:
    """The credential chain above. Machine-key tokens are cached and minted again before they expire."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self.explicit: Optional[str] = None
        self._minted: Optional[str] = None
        self._expires = 0.0
        self._minted_for: Optional[tuple] = None

    def token(self) -> str:
        """A bearer for project MLflow; AuthError saying what to do when the chain is empty."""
        explicit = self.explicit or os.environ.get(TOKEN_ENV)
        if explicit:
            return explicit
        if os.environ.get(zitadel.KEY_FILE_ENV):
            return self._machine()
        session = self._session()
        if session:
            return session
        raise AuthError(
            "no MLflow credential: set MLFLOW_TRACKING_TOKEN, or (pipeline steps) "
            f"{zitadel.KEY_FILE_ENV} with {zitadel.DOMAIN_ENV} and {zitadel.PROJECT_ENV}, "
            "or run `kaosctl login` inside your app clone.")

    def _machine(self) -> str:
        settings = zitadel.env_settings()
        with self._lock:
            now = self._clock()
            if self._minted is None or settings != self._minted_for or now >= self._expires - REFRESH_LEEWAY:
                body = zitadel.grant(*settings)
                try:
                    lifetime = int(body.get("expires_in") or DEFAULT_LIFETIME)
                except (TypeError, ValueError):
                    lifetime = DEFAULT_LIFETIME
                self._minted, self._expires, self._minted_for = body["access_token"], now + lifetime, settings
            return self._minted

    def _session(self) -> Optional[str]:
        try:
            cred = credentials.load_session(resolve_endpoint())
        except ConfigError:
            return None
        if cred is None:
            return None
        claims = _claims(cred.token) or {}
        exp = claims.get("exp")
        if isinstance(exp, (int, float)) and exp <= self._clock():
            raise AuthError("your `kaosctl login` session has expired: run `kaosctl login` again.")
        project = _project_id()
        aud = claims.get("aud")
        auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else None
        if project and auds is not None and project not in auds:
            raise AuthError(
                f"your `kaosctl login` session is not valid for MLflow: it lacks the organisation project "
                f"audience ({project}). Run `kaosctl login` again inside your app clone.")
        return cred.token


_source = TokenSource()


def token() -> str:
    """The bearer the chain gives now (machine-key tokens are refreshed before they expire)."""
    return _source.token()


class BearerAuth(AuthBase):
    """Puts a fresh bearer from the chain on every request."""

    def __call__(self, request):
        request.headers["Authorization"] = f"Bearer {token()}"
        return request


class ZitadelRequestAuthProvider:
    """MLflow request-auth provider ``zitadel`` (``MLFLOW_TRACKING_AUTH=zitadel``), registered by kaos-lib.

    MLflow calls ``get_auth`` for every request; the returned auth asks the chain each time.
    """

    def get_name(self) -> str:
        return PROVIDER

    def get_auth(self) -> BearerAuth:
        return BearerAuth()


def mlflow(tracking_uri: Optional[str] = None, token: Optional[str] = None):
    """Point the ``mlflow`` module at project MLflow with the chain's auth; return an ``MlflowClient``.

    ``tracking_uri`` defaults to ``$MLFLOW_TRACKING_URI``; ``token`` is chain link 1. The chain is asked once
    here, so a missing credential fails before any work starts. Sets ``MLFLOW_TRACKING_AUTH=zitadel`` in the
    environment, which child processes inherit.
    """
    module = _import_mlflow()
    uri = tracking_uri or os.environ.get(TRACKING_URI_ENV)
    if not uri:
        raise ConfigError("cannot determine the MLflow tracking URI: pass tracking_uri= or set MLFLOW_TRACKING_URI.")
    if token:
        _source.explicit = token
    _source.token()
    os.environ[AUTH_ENV] = PROVIDER
    module.set_tracking_uri(uri)
    from mlflow.tracking import MlflowClient
    return MlflowClient(tracking_uri=uri)
