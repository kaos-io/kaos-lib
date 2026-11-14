"""The one credential chain for lakeFS. No secret is ever stored in the package.

Order (first hit wins):
  1. LAKEFS_ACCESS_KEY + LAKEFS_SECRET_KEY   an app's key pair (pods, CI) -> Basic auth
  2. LAKEFS_KEY_FILE                         a file with an app's key pair that the platform keeps fresh (jobs on
                                             HPC): JSON ``{"access_key_id", "secret_access_key", "expiration"}``
  3. LAKEFS_BEARER_TOKEN                     a bearer token (Slurm jobs)
  4. the cached browser-login session       a person's Zitadel token (laptop)

The session cache is ~/.config/kubecore-ml/lakefs-session.json (0600), the file
the earlier ``kubecore-dataset`` CLI wrote, so an existing login keeps working.

Another project's lakeFS (shared datasets) never gets the own project's access key. An app (the credential
is an access key) asks its own lakeFS for a key of the same app in the owner's lakeFS (``peer_key``), which reads
what is shared with the project and nothing else. A person or a job with a bearer token uses ``resolve_peer``.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Optional

from . import oidc
from .config import oidc_settings
from .errors import AuthError, ConfigError, LakeFSError


@dataclass(frozen=True)
class Credential:
    """How to authenticate to lakeFS: a bearer ``token`` or an access-key pair."""
    token: Optional[str] = field(default=None, repr=False)
    access_key: Optional[str] = None
    secret_key: Optional[str] = field(default=None, repr=False)
    #: When the key stops working (seconds since the epoch), if the server said; None: not known.
    expires: Optional[float] = None
    #: The file the key was read from (``LAKEFS_KEY_FILE``); the client reads it again when it changes.
    key_file: Optional[str] = None

    @property
    def kind(self) -> str:
        return "bearer" if self.token else "access key"


def session_path() -> pathlib.Path:
    """Where the login session is cached (re-evaluated so tests/env can redirect it)."""
    home = os.environ.get("KUBECORE_ML_HOME") or pathlib.Path.home() / ".config" / "kubecore-ml"
    return pathlib.Path(home) / "lakefs-session.json"


KEY_FILE_ENV = "LAKEFS_KEY_FILE"


def read_key_file(path: str) -> Credential:
    """The key pair in the file ``path``; AuthError saying what is wrong when there is none that works.

    Never puts a value of the file into the error.
    """
    try:
        data = json.loads(pathlib.Path(path).read_text())
        key, secret = data["access_key_id"], data["secret_access_key"]
        if not (isinstance(key, str) and isinstance(secret, str) and key and secret):
            raise ValueError
    except FileNotFoundError:
        raise AuthError(f"the key file {path} does not exist yet. The platform writes it when the step starts; "
                        "run `kaosctl login`, or set LAKEFS_BEARER_TOKEN.") from None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise AuthError(f"the key file {path} cannot be read: it holds no access key and secret key. "
                        "Run `kaosctl login`, or set LAKEFS_BEARER_TOKEN.") from None
    expires = _epoch(data.get("expiration")) if data.get("expiration") else None
    if expires is not None and expires <= datetime.datetime.now(datetime.timezone.utc).timestamp():
        raise AuthError(f"the key in the key file {path} has ended and no newer one was written. "
                        "Run `kaosctl login`, or set LAKEFS_BEARER_TOKEN.")
    return Credential(access_key=key, secret_key=secret, expires=expires, key_file=path)


def from_env() -> Optional[Credential]:
    """Credential from the environment (chain steps 1 to 3), or None.

    A key file that holds no working key is skipped when a bearer token is set; without one its error is raised.
    """
    key, secret = os.environ.get("LAKEFS_ACCESS_KEY"), os.environ.get("LAKEFS_SECRET_KEY")
    if key and secret:
        return Credential(access_key=key, secret_key=secret)
    path = os.environ.get(KEY_FILE_ENV)
    if path:
        try:
            return read_key_file(path)
        except AuthError:
            if not os.environ.get("LAKEFS_BEARER_TOKEN"):
                raise
    token = os.environ.get("LAKEFS_BEARER_TOKEN")
    return Credential(token=token) if token else None


def save_session(base_url: str, token: str) -> None:
    """Cache a login token for ``base_url`` (file mode 0600)."""
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"base_url": base_url.rstrip("/"), "token": token}))
    os.chmod(path, 0o600)


def load_session(base_url: str) -> Optional[Credential]:
    """The cached login token for ``base_url`` (chain step 3), or None."""
    try:
        data = json.loads(session_path().read_text())
    except (OSError, ValueError):
        return None
    if data.get("base_url") != base_url.rstrip("/") or not data.get("token"):
        return None
    return Credential(token=data["token"])


def resolve(base_url: str) -> Credential:
    """Walk the chain; raise AuthError telling the user what to do when it is empty."""
    cred = from_env() or load_session(base_url)
    if cred is None:
        raise AuthError(
            "not signed in. Run `kaosctl login`, or set LAKEFS_ACCESS_KEY/LAKEFS_SECRET_KEY "
            "(or LAKEFS_KEY_FILE, or LAKEFS_BEARER_TOKEN) in the environment.")
    return cred


def resolve_peer(own_base_url: str) -> Credential:
    """The credential of a person or a job for ANOTHER project's lakeFS: always a bearer token, never the access key.

    Order (first hit wins):
      1. LAKEFS_BEARER_TOKEN
      2. the cached browser-login session of the own lakeFS at ``own_base_url`` (laptop)

    An app does not come here: ``LakeFS.for_owner`` asks the own lakeFS for the app's key (``peer_key``).
    """
    token = os.environ.get("LAKEFS_BEARER_TOKEN")
    if token:
        return Credential(token=token)
    cred = load_session(own_base_url)
    if cred is None:
        raise AuthError(
            "cannot read another project's datasets: no token. Run `kaosctl login`, or set LAKEFS_BEARER_TOKEN. "
            "LAKEFS_ACCESS_KEY is never sent to another project.")
    return cred


SHARED_CREDENTIALS_PATH = "/kaos/v1/shared-credentials"


class NotShared(AuthError):
    """The owner shares no dataset with this project (any more)."""


def peer_key(session, own_base_url: str, owner: str, timeout: int = 30) -> Credential:
    """The access key of this app in the lakeFS of project ``owner``, from the own lakeFS (``session`` is the app's).

    The own lakeFS knows which app asks, from the key the request is signed with, and asks the owner's lakeFS for a
    key of that app. The key reads exactly the datasets ``owner`` shares with this project, never writes, and
    expires (about an hour). The project's own key never reaches the owner.
    """
    url = own_base_url.rstrip("/") + SHARED_CREDENTIALS_PATH
    resp = session.post(url, json={"owner": owner}, timeout=timeout, allow_redirects=False)
    too_old = ConfigError(f"the lakeFS at {own_base_url} is too old for datasets shared with apps "
                          f"(it does not serve {SHARED_CREDENTIALS_PATH}). Ask the platform team to update kaos-lake.")
    if resp.status_code in (301, 302, 303, 307, 308, 401):
        raise AuthError(f"lakeFS rejected the credential (a key for project {owner}'s datasets). Run `kaosctl login` again.")
    if resp.status_code == 403:
        raise NotShared(f"not shared with your project: {_message(resp)}. Ask project {owner} to share the dataset with your "
                        "project. Only an app of your project reads it this way: a person signs in with `kaosctl login`, "
                        "a job carries LAKEFS_BEARER_TOKEN.")
    if resp.status_code in (404, 405, 501):
        raise too_old
    if resp.status_code != 200:
        raise LakeFSError(f"asking for a key of project {owner} failed: HTTP {resp.status_code} {_message(resp)}",
                          resp.status_code)
    try:
        body = resp.json()
        key, secret = body["access_key_id"], body["secret_access_key"]
    except (ValueError, KeyError, TypeError):
        raise too_old from None   # an old lakeFS answers unknown paths with its web UI
    return Credential(access_key=key, secret_key=secret, expires=_epoch(body.get("expiration")))


def _epoch(text) -> Optional[float]:
    """An RFC 3339 time as seconds since the epoch; None when it is not one."""
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _message(resp) -> str:
    try:
        return str(resp.json().get("message") or "")[:300]
    except (ValueError, AttributeError):
        return (resp.text or "")[:300]


def browser_login(base_url: str, start: Optional[str] = None) -> Credential:
    """Sign in through the browser (Zitadel PKCE), cache the token and return it."""
    issuer, client_id, audience = oidc_settings(start)
    if not issuer or not client_id:
        raise AuthError(
            "browser sign-in is not configured for this app (no oidcIssuer/oidcClientId in "
            ".kubecore/dataset-config.yaml). Run inside your app clone, or use an access key.")
    try:
        tokens = oidc.login(issuer, client_id, audience_project_id=audience)
    except oidc.LoginError as exc:
        raise AuthError(f"browser sign-in failed: {exc}") from exc
    token = tokens["access_token"]
    save_session(base_url, token)
    print("Logged in; session cached.", file=sys.stderr)
    return Credential(token=token)
