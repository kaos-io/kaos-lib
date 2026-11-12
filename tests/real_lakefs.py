"""A real lakeFS-compatible server in a container, behind the test helpers of ``FakeLakeFS``.

``KAOS_LIB_TEST_LAKEFS=real`` (or ``both``) makes the ``fake`` fixture hand out a ``RealLakeFS``: the same
helper names (``add_repo``, ``tag``, ``head``, ``tree``, ``client``, ``calls``, ``writes``, ``repos``), but every
``/api/v1`` request is answered by the server, so merges conflict, names are validated and commits are real.

What stays scripted, because a test cannot set it on a server: the ``/kaos/v1/*`` answers (``kaos``,
``templates``, ``storage_prefix``) and ``deny``. A test that rewrites the fake's state in place (a commit with
a chosen id) is skipped: a server gives no such handle.

The image is ``$KAOS_LIB_TEST_LAKEFS_IMAGE``, else the local ``kaos-lake:prd1911`` when it exists, else
``treeverse/lakefs:1.86.0``. Both run with local block storage; nothing leaves the workstation.
"""
from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import requests
from requests.adapters import HTTPAdapter

from kaos_lib import credentials, lakefs
from kaos_lib.lakefs import LakeFS

MODE_ENV = "KAOS_LIB_TEST_LAKEFS"          # fake (default) | real | both
IMAGE_ENV = "KAOS_LIB_TEST_LAKEFS_IMAGE"
LOCAL_IMAGE = "kaos-lake:prd1911"
UPSTREAM_IMAGE = "treeverse/lakefs:1.86.0"
ACCESS_KEY, SECRET_KEY = "AKIAIOSFOLKAOSTEST00", "kaos-lib-test-secret-key-0000000000000000"
# The apps of the test project on kaos-lake: each may write its outputs repository and the datasets it declares.
APPS = {
    "writer": {"user": "kaos-app-writer", "access_key_id": "AKIAJWRITER0000001Q", "secret_access_key": "writer-secret",
               "outputs_repository": "outputs-writer", "datasets": [f"dataset-written-{i}" for i in range(1, 9)]},
    "other": {"user": "kaos-app-other", "access_key_id": "AKIAJOTHER00000001Q", "secret_access_key": "other-secret",
              "outputs_repository": "outputs-other", "datasets": ["dataset-others-1"]},
}
SCRIPTED = "this test rewrites the fake's state in place; a real server has no such handle"


def modes() -> list:
    mode = (os.environ.get(MODE_ENV) or "fake").strip().lower()
    if mode not in ("fake", "real", "both"):
        raise pytest.UsageError(f"${MODE_ENV} must be fake, real or both (got {mode!r}).")
    return ["fake", "real"] if mode == "both" else [mode]


def _docker(*args, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def image() -> str:
    if os.environ.get(IMAGE_ENV):
        return os.environ[IMAGE_ENV]
    return LOCAL_IMAGE if _docker("image", "inspect", LOCAL_IMAGE).returncode == 0 else UPSTREAM_IMAGE


class Server:
    """One container for the test session."""

    def __init__(self):
        if not shutil.which("docker") or _docker("info").returncode != 0:
            pytest.skip("docker is not available: the real-lakeFS tests need it")
        self.image = image()
        self.name = f"kaos-lib-test-lakefs-{uuid.uuid4().hex[:8]}"
        self.apps_dir = pathlib.Path(tempfile.mkdtemp(prefix="kaos-lib-test-apps-"))
        for app, entry in APPS.items():      # kaos-lake reads these: the apps of the project and what each produces
            (self.apps_dir / app).write_text(json.dumps(entry))
        self.apps_dir.chmod(0o755)
        for f in self.apps_dir.iterdir():
            f.chmod(0o644)
        self.session = requests.Session()
        self.auth = "Basic " + base64.b64encode(f"{ACCESS_KEY}:{SECRET_KEY}".encode()).decode()
        self.session.headers["Authorization"] = self.auth
        # kaos-lake reads the app users and creates their datasets; upstream lakeFS does not start with those
        # settings, so it is started again without them.
        if not self._start(kaos=True) and not self._start(kaos=False):
            pytest.skip(f"{self.image} did not answer within 60 s: {self.last_log[-300:]}")

    def _start(self, kaos: bool) -> bool:
        _docker("rm", "-f", self.name)
        options = ["-e", "LAKEFS_AUTH_UI_CONFIG_RBAC=internal",
                   "-e", "LAKEFS_KAOS_APP_USERS_PATH=/etc/kaos/apps", "-e", "LAKEFS_KAOS_APP_USERS_INTERVAL=2s",
                   "-e", "LAKEFS_KAOS_REPOSITORIES_STORAGE_NAMESPACE_PREFIX=local://lake",
                   "-e", "LAKEFS_KAOS_REPOSITORIES_INTERVAL=2s",
                   "-v", f"{self.apps_dir}:/etc/kaos/apps:ro,z"] if kaos else []
        run = _docker("run", "-d", "--name", self.name, "-p", "127.0.0.1::8000",
                      "-e", "LAKEFS_DATABASE_TYPE=local", "-e", "LAKEFS_BLOCKSTORE_TYPE=local",
                      "-e", "LAKEFS_AUTH_ENCRYPT_SECRET_KEY=kaos-lib-tests", "-e", "LAKEFS_LOGGING_LEVEL=WARN",
                      "-e", "LAKEFS_INSTALLATION_USER_NAME=admin",
                      "-e", f"LAKEFS_INSTALLATION_ACCESS_KEY_ID={ACCESS_KEY}",
                      "-e", f"LAKEFS_INSTALLATION_SECRET_ACCESS_KEY={SECRET_KEY}", *options, self.image, "run",
                      timeout=600)
        if run.returncode != 0:
            pytest.skip(f"cannot start {self.image}: {run.stderr.strip()[-300:]}")
        port = _docker("port", self.name, "8000/tcp").stdout.splitlines()
        if not port:                       # it exited at once
            self.last_log = _docker("logs", "--tail", "20", self.name).stdout + _docker("logs", "--tail", "20", self.name).stderr
            return False
        self.url = f"http://127.0.0.1:{port[0].rsplit(':', 1)[1]}"
        return self._wait()

    def _wait(self) -> bool:
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if self.session.get(f"{self.url}/api/v1/repositories", timeout=2).status_code == 200:
                    return True
            except requests.RequestException:
                pass
            if _docker("inspect", "-f", "{{.State.Running}}", self.name).stdout.strip() != "true":
                break
            time.sleep(0.3)
        out = _docker("logs", "--tail", "20", self.name)
        self.last_log = out.stdout + out.stderr
        return False

    def stop(self):
        _docker("rm", "-f", self.name)
        shutil.rmtree(self.apps_dir, ignore_errors=True)

    @property
    def is_kaos_lake(self) -> bool:
        """Whether the server is kaos-lake (dataset rights per app, the expected-head merge), not upstream lakeFS."""
        return "kaos" in str(self.api("GET", "/config/version").json().get("version", ""))

    def app_client(self, app: str) -> LakeFS:
        """A client with the app's own key, straight to the server: its rights are the app's, not the admin's."""
        entry = APPS[app]
        return LakeFS(self.url, credentials.Credential(access_key=entry["access_key_id"],
                                                       secret_key=entry["secret_access_key"]), concurrency=4)

    def wait_for_dataset(self, app: str, dataset: str, seconds: int = 90) -> LakeFS:
        """The app's client, once kaos-lake has created the declared dataset and given the app its rights."""
        client, deadline = self.app_client(app), time.time() + seconds
        while True:
            try:
                client.create_branch(dataset, "run-ready-probe", "main")
                client.delete_branch(dataset, "run-ready-probe")
                return client
            except Exception as exc:  # noqa: BLE001 - not there yet, or no right yet
                if "already exists" in str(exc) or getattr(exc, "status", 0) == 409:
                    client.delete_branch(dataset, "run-ready-probe")
                    return client
                if time.time() > deadline:
                    pytest.fail(f"{app} never got the right to write {dataset}: {exc}")
                time.sleep(1)

    def api(self, method, path, ok=(200, 201, 204), **kw):
        resp = self.session.request(method, f"{self.url}/api/v1{path}", timeout=60, **kw)
        assert resp.status_code in ok, f"{method} {path}: HTTP {resp.status_code} {resp.text[:300]}"
        return resp

    def pages(self, path, **params):
        after = ""
        while True:
            body = self.api("GET", path, params={**params, "after": after, "amount": 1000}).json()
            yield from body["results"]
            if not body["pagination"]["has_more"]:
                return
            after = body["pagination"]["next_offset"]


class _Scripted(dict):
    """A snapshot of server state. Reading is fine; writing would have to change the server."""

    def _refuse(self, *a, **k):
        pytest.skip(SCRIPTED)

    __setitem__ = __delitem__ = update = pop = setdefault = clear = _refuse


class _Repos:
    """``fake.repos``: ``name in repos`` and ``repos[name]`` as a read-only snapshot."""

    def __init__(self, real):
        self._real = real

    def __contains__(self, name):
        return self._real.server.api("GET", f"/repositories/{self._real.on_server(name)}",
                                     ok=(200, 404)).status_code == 200

    def __getitem__(self, name):
        return self._real.snapshot(name)


class _Adapter(HTTPAdapter):
    """Records what the client sent, then sends it to the server as the installation admin."""

    def __init__(self, real):
        super().__init__(pool_connections=16, pool_maxsize=16)
        self.real = real

    def send(self, request, **kwargs):
        real, u = self.real, urlsplit(request.url)
        path, q = u.path.removeprefix("/api/v1"), {k: v[0] for k, v in parse_qs(u.query).items()}
        real.calls.append((request.method, path))
        real.auth.append(request.headers.get("Authorization"))
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) == 5 and parts[2] == "branches" and parts[4] == "objects":
            real.writes.append((request.method, parts[1], parts[3], q["path"]))
        scripted = real.scripted(request, path)
        if scripted is not None:
            return _response(request, *scripted)
        if request.method == "POST" and path == "/repositories":
            body = json.loads(request.body)
            body.update(name=real.on_server(body["name"]), storage_namespace=real.to_local(body["storage_namespace"]))
            request.prepare_body(None, None, json=body)
        url = _REPO_IN_URL.sub(lambda m: m.group(1) + real.on_server(m.group(2)), request.url[len(real.base):])
        request.url = real.server.url + url
        request.headers["Authorization"] = real.server.auth
        resp = super().send(request, **kwargs)
        if resp.status_code < 300 and (path == "/repositories" or len(parts) == 2 and parts[0] == "repositories"):
            body = resp.json()           # repository names come back as the test knows them
            if "results" in body:
                body["results"] = [dict(r, id=real.in_test(r["id"])) for r in body["results"] if real.mine(r["id"])]
            elif "id" in body:
                body["id"] = real.in_test(body["id"])
            resp._content = json.dumps(body).encode()
        return resp


_REPO_IN_URL = re.compile(r"^(/api/v1/repositories/)([^/?]+)")


def _response(request, status, body):
    resp = requests.Response()
    resp.status_code, resp.url, resp.request = status, request.url, request
    raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    resp.raw, resp._content = io.BytesIO(raw), raw
    return resp


class RealLakeFS:
    BASE = "http://lakefs.test"

    def __init__(self, server: Server):
        self.server, self.base = server, self.BASE
        self.calls, self.auth, self.writes = [], [], []
        self.kaos, self.templates, self.deny = {}, [], None
        self.upload_answers: list = []                     # statuses the next uploads answer, as on the fake
        self.refused_labels: list = []                     # (repository, label) the server keeps for the platform
        self.storage_prefix = "gs://bucket/lakefs"
        self.repos = _Repos(self)
        # One server serves the whole session and a deleted repository's name stays taken on it, so each test's
        # repositories carry a suffix on the server that the test never sees.
        self._suffix = "-" + uuid.uuid4().hex[:6]
        self._root = f"local://{self._suffix[1:]}/"        # this test's corner of the server's block storage
        self._ns: dict = {}                                # local namespace -> the one the test asked for

    # ---- what a server cannot be told: answered here, as the fake does
    def scripted(self, request, path):
        if path == "/kaos/v1/dataset-templates":
            if self.storage_prefix is None:
                return 404, {}
            return 200, {"storage_namespace_prefix": self.storage_prefix, "templates": self.templates}
        if path.startswith("/kaos/"):
            return self.kaos.get(path, (404, b"<html><body>404 page not found</body></html>"))
        if self.deny:
            return self.deny, {"message": "insufficient permissions"}
        if request.method == "POST" and path.endswith("/objects") and self.upload_answers:
            self.writes.pop()
            return self.upload_answers.pop(0), {"message": "try again"}
        return None

    def on_server(self, repo: str) -> str:
        return repo + self._suffix

    def in_test(self, repo: str) -> str:
        return repo[:-len(self._suffix)]

    def mine(self, repo: str) -> bool:
        return repo.endswith(self._suffix)

    def to_local(self, ns: str) -> str:
        """The server stores on local disk, so a ``gs://`` namespace becomes a folder under this test's root."""
        local = self._root + re.sub(r"^[a-z0-9]+://", "", ns)
        self._ns[local] = ns
        return local

    # ---- the fake's helpers, on the server
    def client(self, bearer="t", credential=None):
        cred = credential or credentials.Credential(token=bearer)
        s = lakefs._session(cred, 8)
        adapter = _Adapter(self)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        return LakeFS(self.base, cred, session=s, concurrency=4)

    def add_repo(self, name, ns="gs://bucket/proj/seed", metadata=None, files=None):
        api = self.server.api
        if name in self.repos:   # the fake replaces a repository; a server keeps a deleted name taken for seconds
            if files or metadata or self.tree(name, "main"):
                pytest.skip(SCRIPTED)
            return self.head(name)
        local = self.to_local(f"{ns}-{uuid.uuid4().hex[:8]}")   # the fake lets seeded repositories share one
        self._ns[local] = ns
        api("POST", "/repositories", json={"name": self.on_server(name), "default_branch": "main",
                                           "storage_namespace": local})
        for key, value in (metadata or {}).items():   # one by one: kaos-lake keeps some labels for the platform
            done = api("POST", f"/repositories/{self.on_server(name)}/metadata", json={"metadata": {key: value}},
                       ok=(200, 201, 204, 400))
            if done.status_code == 400:
                assert "invalid repository label" in done.text, done.text
                self.refused_labels.append((name, key))
        for path, content in (files or {}).items():
            api("POST", f"/repositories/{self.on_server(name)}/branches/main/objects", params={"path": path},
                files={"content": ("f", content)})
        if files:
            api("POST", f"/repositories/{self.on_server(name)}/branches/main/commits", json={"message": "seed"})
        return self.head(name)

    def delete_repo(self, name):
        self.server.api("DELETE", f"/repositories/{self.on_server(name)}", params={"force": "true"})

    def tag(self, repo, name, ref="main"):
        self.server.api("POST", f"/repositories/{self.on_server(repo)}/tags", json={"id": name, "ref": ref})

    def commit_meta(self, repo, commit):
        """`(message, metadata)` of a commit."""
        c = self.server.api("GET", f"/repositories/{self.on_server(repo)}/commits/{commit}").json()
        return c["message"], c.get("metadata") or {}

    def head(self, repo, branch="main"):
        return self.server.api("GET", f"/repositories/{self.on_server(repo)}/branches/{branch}").json()["commit_id"]

    def tree(self, repo, ref):
        out = {}
        for o in self.server.pages(f"/repositories/{self.on_server(repo)}/refs/{ref}/objects/ls"):
            if o.get("path_type", "object") == "object":
                out[o["path"]] = self.server.api("GET", f"/repositories/{self.on_server(repo)}/refs/{ref}/objects",
                                                 params={"path": o["path"]}).content
        return out

    def _log(self, repo, ref):
        return list(self.server.pages(f"/repositories/{self.on_server(repo)}/refs/{ref}/commits", first_parent="true"))

    def snapshot(self, name) -> dict:
        api, pages = self.server.api, self.server.pages
        info = api("GET", f"/repositories/{self.on_server(name)}", ok=(200, 404))
        if info.status_code == 404:
            raise KeyError(name)
        info = info.json()
        repo = f"/repositories/{self.on_server(name)}"
        branches = {b["id"]: _Scripted(commit=b["commit_id"]) for b in pages(f"{repo}/branches")}
        main = [c for c in self._log(name, info["default_branch"]) if c["parents"]]
        seen, log = {c["id"] for c in main}, [(info["default_branch"], c) for c in main]
        for branch in branches:
            if branch != info["default_branch"]:
                for c in self._log(name, branch):
                    if c["id"] in seen or not c["parents"]:
                        break
                    log.append((branch, c))
        log.sort(key=lambda e: e[1]["creation_date"])
        snap = _Scripted(
            ns=self._ns.get(info["storage_namespace"], info["storage_namespace"]),
            default_branch=info["default_branch"],
            metadata=_Scripted(api("GET", f"{repo}/metadata").json() or {}),
            branches=_Scripted(branches), commits=_Scripted(),
            tags=_Scripted({t["id"]: t["commit_id"] for t in pages(f"{repo}/tags")}),
            pulls=list(pages(f"{repo}/pulls")))
        if log:
            dict.__setitem__(snap, "commit_log", [(b, c["id"], c["message"], c.get("metadata") or {}) for b, c in log])
        return snap

    def __getattr__(self, name):   # a fake helper with no server counterpart (_new_commit, ...)
        pytest.skip(f"{SCRIPTED} (FakeLakeFS.{name})")

    def cleanup(self):
        for repo in list(self.server.pages("/repositories")):
            if self.mine(repo["id"]):
                self.delete_repo(self.in_test(repo["id"]))
