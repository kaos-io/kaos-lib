"""Thin lakeFS REST client (API v1) for kaos-lake. One class, no business logic.

Authentication comes from ``credentials.resolve``: a bearer token, or an
access-key pair sent as Basic auth. ``for_owner`` returns a client for another
project's lakeFS that never carries this project's access key: an app's own key there
(``credentials.peer_key``), or a person's or job's bearer token (``credentials.resolve_peer``).
HTTP failures become ``LakeFSError`` subclasses whose messages tell the user what to do next.
"""
from __future__ import annotations

import os
import pathlib
import threading
import time
from typing import Iterator, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import credentials
from .config import resolve_endpoint
from .errors import AuthError, KaosLibError, LakeFSError, NotFoundError, PermissionDenied

USER_AGENT = "kaos-lib/0.5"


RENEW_BEFORE = 120   # seconds: a key of another project's lakeFS is replaced this long before it ends
RENEW_GAP = 10       # seconds: after one request for a new key, no other, whatever is refused meanwhile
_REFUSED = (301, 302, 303, 307, 308, 401, 403)


def _repo_of(path: str) -> Optional[str]:
    """The repository a ``/repositories/<repo>/...`` path names."""
    parts = path.strip("/").split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "repositories" else None


def _now() -> float:
    return time.time()


def _q(value: str) -> str:
    return quote(value, safe="")


def _strs(metadata: Optional[dict]) -> dict:
    return {k: str(v) for k, v in (metadata or {}).items()}


def _is_no_changes(exc: LakeFSError) -> bool:
    """lakeFS answers an empty commit or merge with 400 'no changes'."""
    return exc.status == 400 and "no changes" in str(exc).lower()


def _session(cred: credentials.Credential, pool: int) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=0.5, status_forcelist=[502, 503, 504],
                  allowed_methods=["HEAD", "GET", "PUT", "DELETE"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = USER_AGENT
    if cred.token:
        s.headers["Authorization"] = f"Bearer {cred.token}"
    else:
        s.auth = (cred.access_key, cred.secret_key)
    return s


class LakeFS:
    """A lakeFS server reachable at ``base_url`` with one credential.

    ``owner`` is None for the own project's lakeFS, else the project whose lakeFS this is.
    """

    def __init__(self, base_url: str, credential: credentials.Credential,
                 session: Optional[requests.Session] = None, timeout: int = 300, concurrency: int = 16,
                 owner: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.concurrency = concurrency
        self.owner = owner
        self.credential = credential
        self.session = session or _session(credential, concurrency * 2)
        self._peer_clients: dict = {}
        # A client for another project's lakeFS as an app holds a key that ends: _refresh asks for a new one.
        self._refresh = None
        self._generation = 0
        self._renewing = threading.Lock()
        self._served: set = set()          # repositories of the owner this client has read successfully
        self._attempted = float("-inf")
        self._templates: Optional[dict] = None
        self._key_mtime = self._mtime_of_key_file()

    @classmethod
    def connect(cls, url: Optional[str] = None, start: Optional[str] = None) -> "LakeFS":
        """Resolve the endpoint and the credential chain and return a ready client."""
        base = resolve_endpoint(url, start)
        return cls(base, credentials.resolve(base))

    def for_owner(self, owner: str) -> "LakeFS":
        """A client for the lakeFS of project ``owner`` (this client when ``owner`` is the own project).

        The address comes from the own lakeFS's peers (``/kaos/v1/peers``): the platform-network endpoint when
        this client's base is such an address (``.svc``), else the public URL. An app (this client's credential is an
        access key) asks its own lakeFS for a key of the same app in the owner's, which reads what the owner shares
        with the project and nothing else (``credentials.peer_key``). Otherwise the credential is a bearer token
        (``credentials.resolve_peer``). This project's access key is never sent to the owner.
        """
        from . import peers
        if self.owner:
            raise LakeFSError(f"this client reads project {self.owner}; ask the own project's client for {owner}.")
        if owner in self._peer_clients:
            return self._peer_clients[owner]
        if owner == peers.load(self).project:
            return self
        base = peers.base_for(self.base_url, peers.peer(self, owner))
        if self.credential.access_key:
            cred = credentials.peer_key(self.session, self.base_url, owner, self.timeout)
        else:
            cred = credentials.resolve_peer(self.base_url)
        client = LakeFS(base, cred, timeout=self.timeout,
                        concurrency=self.concurrency, owner=owner)
        if self.credential.access_key:
            client._refresh = lambda: credentials.peer_key(self.session, self.base_url, owner, self.timeout)
        self._peer_clients[owner] = client
        return client

    # -- plumbing --------------------------------------------------------
    def _call(self, method: str, path: str, ok=(200, 201, 204), what: str = "", **kw):
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("allow_redirects", method == "GET")
        what = what or f"{method} {path}"
        repo = _repo_of(path)
        generation = self._fresh_key()
        resp = self.session.request(method, f"{self.base_url}/api/v1{path}", **kw)
        if self._refresh and resp.status_code in _REFUSED:
            # The key may have ended, or the share may be gone: ask for a new key once and try once more.
            resp.close()
            self._renew(generation, what, repo)
            resp = self.session.request(method, f"{self.base_url}/api/v1{path}", **kw)
            if resp.status_code in _REFUSED and repo in self._served:
                raise self._withdrawn(what)     # read before, refused now with a new key: the share is gone
        if resp.status_code in ok:
            if repo:
                self._served.add(repo)
            return resp
        raise self._error(resp, what)

    # -- the key of an app in another project's lakeFS -------------------
    def _mtime_of_key_file(self) -> Optional[float]:
        try:
            return os.stat(self.credential.key_file).st_mtime if self.credential.key_file else None
        except OSError:
            return None

    def _reread_key_file(self) -> None:
        """A job's key is in a file the platform rewrites: take the key the file holds now, when it is new.

        A file that is missing or unreadable for a moment (being rewritten) leaves the key in use as it is.
        """
        path = self.credential.key_file
        mtime, exp = self._mtime_of_key_file(), self.credential.expires
        if mtime is None or (mtime == self._key_mtime and not (exp is not None and _now() >= exp - RENEW_BEFORE)):
            return
        try:
            cred = credentials.read_key_file(path)
        except AuthError:
            return
        self._key_mtime = mtime
        if (cred.access_key, cred.secret_key) != (self.credential.access_key, self.credential.secret_key):
            self.credential = cred
            self.session.auth = (cred.access_key, cred.secret_key)
            self._generation += 1

    def _fresh_key(self) -> int:
        """Replace a key that is about to end; returns the generation of the key the next request carries."""
        if self.credential.key_file:
            self._reread_key_file()
        generation = self._generation
        exp = self.credential.expires
        if self._refresh and exp is not None and _now() >= exp - RENEW_BEFORE:
            try:
                self._renew(generation, "the next request", None)
            except (KaosLibError, requests.RequestException):
                pass    # the key may still work: this request goes with it; only a refusal makes a renewal required
            generation = self._generation
        return generation

    def _renew(self, seen: int, what: str, repo: Optional[str]) -> None:
        """Get a new key, unless another thread already did since ``seen`` (so N threads cost one request)."""
        with self._renewing:
            if self._generation != seen or _now() - self._attempted < RENEW_GAP:
                return      # another thread just did; or a key that was just asked for is refused too: that is no expiry
            self._attempted = _now()
            try:
                cred = self._refresh()
            except credentials.NotShared:
                if repo in self._served:
                    raise self._withdrawn(what) from None
                raise
            self.credential = cred
            self.session.auth = (cred.access_key, cred.secret_key)
            self._generation += 1

    def _withdrawn(self, what: str) -> AuthError:
        return AuthError(f"the share was withdrawn: project {self.owner} no longer shares this dataset with your project "
                         f"({what}). Ask {self.owner} to share it again; nothing in your step needs to change.")

    def _error(self, resp: requests.Response, what: str) -> LakeFSError:
        status, detail = resp.status_code, (resp.text or "")[:300]
        if self.owner and status in (301, 302, 303, 307, 308, 401, 403):
            return AuthError(f"not shared with your project: project {self.owner}'s lakeFS refused it ({what}). "
                             f"Ask {self.owner} to share the dataset with your project.")
        if status == 403 or (status == 401 and "insufficient permissions" in detail):   # kaos-lake answers 401 here
            return PermissionDenied(f"you are not allowed to do this ({what}): {detail}")
        if status in (301, 302, 303, 307, 308, 401):
            return AuthError(f"lakeFS rejected the credential ({what}). Run `kaosctl login` again.")
        if status == 404:
            return NotFoundError(f"not found ({what}): {detail}", status)
        return LakeFSError(f"{what} failed: HTTP {status} {detail}", status)

    def _pages(self, path: str, params: Optional[dict] = None, after: str = "") -> Iterator[dict]:
        while True:
            body = self._call("GET", path, params={**(params or {}), "after": after, "amount": 1000}).json()
            yield from body.get("results", [])
            page = body.get("pagination", {})
            if not page.get("has_more"):
                return
            after = page.get("next_offset", "")

    # -- repositories ----------------------------------------------------
    def repositories(self) -> list:
        """Every repository the caller may see: dicts with ``id``, ``storage_namespace``, ..."""
        return list(self._pages("/repositories"))

    def repository(self, repo: str) -> Optional[dict]:
        """The repository dict, or None when it does not exist."""
        try:
            return self._call("GET", f"/repositories/{_q(repo)}", what=f"repository {repo}").json()
        except NotFoundError:
            return None

    def create_repository(self, repo: str, storage_namespace: str, default_branch: str = "main") -> None:
        self._call("POST", f"/repositories", json={
            "name": repo, "storage_namespace": storage_namespace, "default_branch": default_branch},
            what=f"create repository {repo}")

    def metadata(self, repo: str) -> dict:
        """The repository's metadata labels (``kaos.*``); lakeFS answers them as a flat object."""
        return self._call("GET", f"/repositories/{_q(repo)}/metadata", what=f"metadata of {repo}").json() or {}

    def set_metadata(self, repo: str, labels: dict) -> None:
        self._call("POST", f"/repositories/{_q(repo)}/metadata", json={"metadata": labels},
                   what=f"set metadata of {repo}")

    # -- refs ------------------------------------------------------------
    def branch_commit(self, repo: str, branch: str) -> str:
        """The commit id at the head of ``branch``."""
        return self._call("GET", f"/repositories/{_q(repo)}/branches/{_q(branch)}",
                          what=f"branch {branch} of {repo}").json()["commit_id"]

    def create_branch(self, repo: str, name: str, source: str) -> None:
        self._call("POST", f"/repositories/{_q(repo)}/branches", json={"name": name, "source": source},
                   what=f"create branch {name}")

    def delete_branch(self, repo: str, name: str) -> None:
        """Delete ``name`` (a missing branch is fine)."""
        self._call("DELETE", f"/repositories/{_q(repo)}/branches/{_q(name)}", ok=(200, 204, 404),
                   what=f"delete branch {name}")

    def merge(self, repo: str, source: str, destination: str, message: str, metadata: Optional[dict] = None,
              tolerate_empty: bool = False, expected_head: Optional[str] = None) -> str:
        """Merge ``source`` into ``destination`` (mergeIntoBranch); returns the merge commit id.

        With ``tolerate_empty`` a merge with nothing to merge is a success returning the destination head.
        With ``expected_head`` (a full commit id) the merge happens only while ``destination`` is still at that
        commit; when it moved, kaos-lake answers 412 and this raises ``LakeFSError`` with ``status == 412``.
        """
        body = {"message": message, "metadata": _strs(metadata)}
        if expected_head:
            body["expected_head"] = expected_head
        try:
            resp = self._call("POST", f"/repositories/{_q(repo)}/refs/{_q(source)}/merge/{_q(destination)}",
                              json=body, what=f"merge {source} into {destination}")
        except LakeFSError as exc:
            if tolerate_empty and _is_no_changes(exc):
                return self.branch_commit(repo, destination)
            raise
        return resp.json()["reference"]

    def branch_exists(self, repo: str, branch: str) -> bool:
        try:
            self.branch_commit(repo, branch)
            return True
        except NotFoundError:
            return False

    def dataset_templates(self) -> Optional[dict]:
        """kaos-lake's ``GET /kaos/v1/dataset-templates`` (layouts and the storage prefix), read once; None if it has none."""
        if self._templates is None:
            try:
                resp = self.session.get(f"{self.base_url}/kaos/v1/dataset-templates", timeout=30,
                                        allow_redirects=False)
                body = resp.json() if resp.status_code == 200 else None
            except (requests.RequestException, ValueError):
                body = None
            self._templates = body if isinstance(body, dict) else {}
        return self._templates or None

    def storage_namespace_prefix(self) -> Optional[str]:
        """Where kaos-lake wants new repositories (``GET /kaos/v1/dataset-templates``), or None if it does not say."""
        return (self.dataset_templates() or {}).get("storage_namespace_prefix") or None

    def tags(self, repo: str, prefix: str = "", after: str = "") -> list:
        """The tags in name order (those whose name starts with ``prefix`` and sorts after ``after``): dicts with
        ``id`` (name) and ``commit_id``."""
        return list(self._pages(f"/repositories/{_q(repo)}/tags", {"prefix": prefix} if prefix else None, after))

    def tag_commit(self, repo: str, tag: str) -> str:
        return self._call("GET", f"/repositories/{_q(repo)}/tags/{_q(tag)}",
                          what=f"tag {tag} of {repo}").json()["commit_id"]

    def commit_info(self, repo: str, commit: str) -> dict:
        """The commit as lakeFS describes it (``id``, ``parents``, ``message``, ``metadata``); NotFoundError if none."""
        return self._call("GET", f"/repositories/{_q(repo)}/commits/{_q(commit)}",
                          what=f"commit {commit} of {repo}").json()

    def commit_id(self, repo: str, commit: str) -> str:
        """``commit`` itself when it exists in ``repo`` (NotFoundError otherwise)."""
        return self.commit_info(repo, commit)["id"]

    def create_tag(self, repo: str, tag: str, ref: str) -> None:
        self._call("POST", f"/repositories/{_q(repo)}/tags", json={"id": tag, "ref": ref},
                   what=f"create tag {tag}")

    # -- objects ---------------------------------------------------------
    def list_objects(self, repo: str, ref: str, prefix: str = "") -> Iterator[dict]:
        """Every object under ``prefix`` on ``ref``: dicts with ``path``, ``checksum``, ``size_bytes``."""
        for obj in self._pages(f"/repositories/{_q(repo)}/refs/{_q(ref)}/objects/ls", {"prefix": prefix}):
            if obj.get("path_type", "object") == "object":
                yield obj

    def download_object(self, repo: str, ref: str, path: str, dest: pathlib.Path) -> None:
        """Stream one object at ``ref`` (a commit id pins it) to ``dest``."""
        resp = self._call("GET", f"/repositories/{_q(repo)}/refs/{_q(ref)}/objects",
                          params={"path": path}, stream=True, what=f"download {path}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)

    def upload_object(self, repo: str, branch: str, path: str, local: pathlib.Path) -> None:
        with local.open("rb") as fh:
            self._call("POST", f"/repositories/{_q(repo)}/branches/{_q(branch)}/objects",
                       params={"path": path}, files={"content": (local.name, fh)}, what=f"upload {path}")

    def copy_object(self, repo: str, branch: str, path: str, src_path: str, src_ref: str) -> None:
        """Put the object ``src_path`` of ``src_ref`` (a commit id pins it) on ``branch`` as ``path``, copied by the
        server inside the repository: the bytes are not sent again."""
        self._call("POST", f"/repositories/{_q(repo)}/branches/{_q(branch)}/objects/copy",
                   params={"dest_path": path}, json={"src_path": src_path, "src_ref": src_ref},
                   what=f"copy {src_path} to {path}")

    def delete_object(self, repo: str, branch: str, path: str) -> None:
        self._call("DELETE", f"/repositories/{_q(repo)}/branches/{_q(branch)}/objects",
                   params={"path": path}, ok=(200, 204, 404), what=f"delete {path}")

    def commit(self, repo: str, branch: str, message: str, metadata: Optional[dict] = None,
               tolerate_empty: bool = False) -> str:
        """Commit the staged changes on ``branch``; returns the new commit id.

        With ``tolerate_empty`` a commit with nothing staged is a success returning the branch head.
        """
        try:
            resp = self._call("POST", f"/repositories/{_q(repo)}/branches/{_q(branch)}/commits",
                              json={"message": message, "metadata": _strs(metadata)}, what=f"commit on {branch}")
        except LakeFSError as exc:
            if tolerate_empty and _is_no_changes(exc):
                return self.branch_commit(repo, branch)
            raise
        return resp.json()["id"]

    # -- pull requests ---------------------------------------------------
    def create_pull(self, repo: str, source: str, destination: str, title: str, description: str = "") -> str:
        """Open a pull request source -> destination; returns its id."""
        resp = self._call("POST", f"/repositories/{_q(repo)}/pulls", json={
            "title": title, "description": description,
            "source_branch": source, "destination_branch": destination}, what="open pull request")
        return str(resp.json()["id"])
