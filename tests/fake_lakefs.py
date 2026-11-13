"""In-memory lakeFS for tests: a requests transport adapter, so the real client code runs unchanged."""
from __future__ import annotations

import base64
import hashlib
import io
import itertools
import json
import re
from email.parser import BytesParser
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from requests.adapters import BaseAdapter

from kaos_lib import credentials, lakefs
from kaos_lib.lakefs import LakeFS

BRANCH_ID = re.compile(r"^\w[-\w]*$")  # lakeFS's branch id rule
DATASET_ID = re.compile(r"^dataset-[a-z0-9-]{3,48}$")  # kaos-lake: what may carry kaos.kind=dataset
REPO_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")  # and its repository id rule


class FakeLakeFS(BaseAdapter):
    """Repos with branches (committed + staged), commits, tags, metadata and pulls."""

    BASE = "http://lakefs.test"

    def __init__(self, base: str = BASE):
        super().__init__()
        self.base = base
        self.repos: dict = {}
        self.used_ns: set = set()    # storage namespaces ever used: a deleted repo's stays used
        self.calls: list = []        # (method, path-without-query)
        self.auth: list = []         # the Authorization header of every request (None when absent)
        self.kaos: dict = {}         # "/kaos/v1/..." -> (status, JSON body or raw bytes); others: 404 HTML
        self.deny = None             # an HTTP status every /api/v1 call answers: 401 is a credential this server does
                                     # not know, 403 and "refused" (kaos-lake's 401 for a policy) are rights
        self.valid_auth = None       # a set of Authorization headers this server accepts on /api/v1; None: any
        self.refuse_repos = set()    # repositories every /api/v1 call on which is refused (not shared): 401, "insufficient permissions"
        self.denied = 0              # /api/v1 requests refused because their key was not in valid_auth
        self.hook = None             # called with (fake, request) before each /api/v1 request is answered
        self.posted: list = []       # (path, JSON body) of every POST to "/kaos/v1/..."
        self.writes: list = []       # (kind, repo, branch, path) for object uploads/deletes
        self.upload_answers: list = []   # statuses the next uploads answer instead of storing the object
        self.storage_prefix = "gs://bucket/lakefs"   # None: kaos-lake publishes no prefix
        self.templates: list = []                    # /kaos/v1/dataset-templates entries (layouts kaos-lake serves)
        self._ids = itertools.count(1)

    # ---- test helpers
    def delete_repo(self, name):
        """As lakeFS: the repository goes, its storage namespace stays used."""
        del self.repos[name]

    def add_repo(self, name, ns="gs://bucket/proj/seed", metadata=None, files=None):
        commit = self._new_commit(name, files or {})
        self.used_ns.add(ns)
        self.repos[name] = {"ns": ns, "metadata": dict(metadata or {}), "commits": {commit[0]: commit[1]},
                            "branches": {"main": {"commit": commit[0], "staged": {}}},
                            "tags": {}, "pulls": []}
        return commit[0]

    def _new_commit(self, repo, objects):
        cid = f"c{next(self._ids):04d}" + "0" * 8
        if repo in self.repos:
            self.repos[repo]["commits"][cid] = dict(objects)
        return cid, dict(objects)

    def tag(self, repo, name, ref="main"):
        self.repos[repo]["tags"][name] = self._resolve(repo, ref)

    def commit_meta(self, repo, commit):
        """`(message, metadata)` of a commit."""
        return next((message, meta) for _, cid, message, meta in self.repos[repo]["commit_log"] if cid == commit)

    def head(self, repo, branch="main"):
        return self.repos[repo]["branches"][branch]["commit"]

    def tree(self, repo, ref):
        return self._view(repo, ref)

    def serve_peer_key(self, access_key="KAOSXPEERAAAAAAAAAA", secret="peer-secret"):
        """Answer ``POST /kaos/v1/shared-credentials`` as the own lakeFS of an app does; returns the
        ``Authorization`` header a request signed with that key carries."""
        self.kaos["/kaos/v1/shared-credentials"] = (200, {"access_key_id": access_key, "secret_access_key": secret,
                                                          "expiration": "2099-01-01T00:00:00Z"})
        return "Basic " + base64.b64encode(f"{access_key}:{secret}".encode()).decode()

    def exchanges(self):
        """The JSON bodies of the requests for a peer key this lakeFS got."""
        return [body for path, body in self.posted if path == "/kaos/v1/shared-credentials"]

    def client(self, bearer="t", credential=None):
        """A real client (real session code, so real auth headers) whose every request reaches this fake."""
        cred = credential or credentials.Credential(token=bearer)
        s = lakefs._session(cred, 8)
        s.mount("http://", self)
        s.mount("https://", self)
        return LakeFS(self.base, cred, session=s, concurrency=4)

    # ---- state
    def _resolve(self, repo, ref):
        r = self.repos[repo]
        if ref in r["branches"]:
            return r["branches"][ref]["commit"]
        if ref in r["tags"]:
            return r["tags"][ref]
        if ref in r["commits"]:
            return ref
        raise KeyError(ref)

    def _view(self, repo, ref):
        r = self.repos[repo]
        if ref in r["branches"]:
            b = r["branches"][ref]
            view = dict(r["commits"][b["commit"]])
            for p, c in b["staged"].items():
                if c is None:
                    view.pop(p, None)
                else:
                    view[p] = c
            return view
        return dict(r["commits"][self._resolve(repo, ref)])

    # ---- transport
    def send(self, request, **kwargs):
        u = urlsplit(request.url)
        path, q = u.path.removeprefix("/api/v1"), {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((request.method, path))
        self.auth.append(request.headers.get("Authorization"))
        try:
            if not path.startswith("/kaos/"):
                if self.hook:
                    self.hook(self, request)
                if self.valid_auth is not None and request.headers.get("Authorization") not in self.valid_auth:
                    self.denied += 1
                    return self._response(request, 401, {"message": "error authenticating request"})
            if self.deny and not path.startswith("/kaos/"):
                raise PermissionError
            if path.startswith("/repositories/") and path.split("/")[2] in self.refuse_repos:
                return self._response(request, 401, {"message": "insufficient permissions"})
            status, body = self._route(request, path, q)
        except PermissionError:
            status = 401 if self.deny == "refused" else self.deny
            body = {"message": "error authenticating request" if self.deny == 401 else "insufficient permissions"}
        except KeyError:
            status, body = 404, {"message": "not found"}
        return self._response(request, status, body)

    def _response(self, request, status, body):
        resp = requests.Response()
        resp.status_code = status
        resp.url = request.url
        raw = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        resp.raw = io.BytesIO(raw)
        resp._content = raw
        resp.request = request
        return resp

    def close(self):
        pass

    def _route(self, req, path, q):
        if path == "/kaos/v1/dataset-templates":
            if self.storage_prefix is None:
                return 404, {}
            return 200, {"storage_namespace_prefix": self.storage_prefix, "templates": self.templates}
        if path.startswith("/kaos/"):
            if req.method == "POST":
                self.posted.append((path, json.loads(req.body) if req.body else None))
            answer = self.kaos.get(path, (404, b"<html><body>404 page not found</body></html>"))
            return answer(req) if callable(answer) else answer
        m, body = req.method, (json.loads(req.body) if req.body and not _is_multipart(req) else {})
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if parts == ["repositories"]:
            if m == "GET":
                return 200, {"results": [{"id": n, "storage_namespace": r["ns"]} for n, r in sorted(self.repos.items())],
                             "pagination": {"has_more": False}}
            if body["name"] in self.repos:                          # lakeFS: the name is taken
                return 409, {"message": "error creating repository: repository already exists"}
            if body["storage_namespace"] in self.used_ns:        # lakeFS keeps a deleted repo's storage and refuses it
                return 400, {"message": "failed to create repository: storage namespace already in use"}
            self.add_repo(body["name"], body["storage_namespace"])
            self.repos[body["name"]]["metadata"] = {}
            return 201, {"id": body["name"]}
        repo, rest = parts[1], parts[2:]
        if not REPO_ID.match(repo):                                  # lakeFS: 400, not 404, for a name it cannot hold
            return 400, {"message": "argument repository: repository id: invalid value: validation error"}
        if repo not in self.repos:
            return 404, {"message": "repository not found"}
        r = self.repos[repo]
        if not rest:
            return 200, {"id": repo, "storage_namespace": r["ns"], "default_branch": r.get("default_branch", "main")}
        return self._repo_route(m, repo, r, rest, body, q, req)

    def _repo_route(self, m, repo, r, rest, body, q, req):
        kind = rest[0]
        if kind == "metadata":
            if m == "GET":
                return 200, dict(r["metadata"])  # lakeFS: a flat object, not {"metadata": ...}
            if body["metadata"].get("kaos.kind") == "dataset" and not DATASET_ID.match(repo):   # kaos-lake's rule
                return 400, {"message": "invalid repository label: a dataset's name is dataset- followed by 3-48 "
                                        f"lowercase letters, digits or hyphens; \"{repo}\" is not"}
            r["metadata"].update(body["metadata"])
            return 204, None
        if kind == "branches":
            return self._branches(m, repo, r, rest[1:], body, req, q)
        if kind == "commits":
            meta = next((m for _, cid, _, m in r.get("commit_log", []) if cid == rest[1]), {})
            return (200, {"id": rest[1], "parents": r.get("parents", {}).get(rest[1], []), "metadata": meta,
                          "creation_date": int(rest[1][1:-8] or 0) if rest[1][1:-8].isdigit() else 0}) \
                if rest[1] in r["commits"] else (404, {})
        if kind == "tags":
            if len(rest) == 1 and m == "GET":
                return 200, {"results": [{"id": t, "commit_id": c} for t, c in sorted(r["tags"].items())
                                         if t.startswith(q.get("prefix", "")) and t > q.get("after", "")],
                             "pagination": {"has_more": False}}
            if len(rest) == 1:
                if body["id"] in r["tags"]:                          # lakeFS: a tag is never moved
                    return 409, {"message": "tag already exists"}
                r["tags"][body["id"]] = self._resolve(repo, body["ref"])
                return 201, {"id": body["id"], "commit_id": r["tags"][body["id"]]}
            return 200, {"id": rest[1], "commit_id": r["tags"][rest[1]]}
        if kind == "refs" and rest[2] == "merge":
            return self._merge(r, rest[1], rest[3], body)
        if kind == "refs":
            return self._refs(repo, rest[1], rest[2:], q)
        if kind == "pulls":
            pid = str(len(r["pulls"]) + 1)
            r["pulls"].append({"id": pid, **body})
            return 201, {"id": pid}
        return 404, {}

    def _branches(self, m, repo, r, rest, body, req, q):
        if not rest:
            if not BRANCH_ID.match(body["name"]):  # lakeFS refuses any other branch id
                return 400, {"message": "argument branch: branch id: invalid value: validation error"}
            base = self._resolve(repo, body["source"])
            r["branches"][body["name"]] = {"commit": base, "base": base, "staged": {}}
            return 201, body["name"]
        b = r["branches"][rest[0]]
        if len(rest) == 1 and m == "DELETE":
            del r["branches"][rest[0]]
            return 204, None
        if len(rest) == 1:
            return 200, {"id": rest[0], "commit_id": b["commit"]}
        if rest[1] == "objects" and len(rest) == 3 and rest[2] == "copy":     # copyObject: inside one repository
            src = self._view(repo, body.get("src_ref") or rest[0])[body["src_path"]]        # KeyError: 404
            b["staged"][q["dest_path"]] = src
            r.setdefault("mtimes", {})[q["dest_path"]] = next(self._ids)
            return 201, {"path": q["dest_path"]}
        if rest[1] == "objects":
            self.writes.append((m, repo, rest[0], q["path"]))
            if m == "POST" and self.upload_answers:                 # a server that is busy, restarting, refusing
                self.writes.pop()
                return self.upload_answers.pop(0), {"message": "try again"}
            if m == "POST":
                b["staged"][q["path"]] = _multipart_content(req)
                r.setdefault("mtimes", {})[q["path"]] = next(self._ids)   # write order stands in for mtime
            else:
                b["staged"][q["path"]] = None
            return (201 if m == "POST" else 204), {}
        if rest[1] == "commits":
            view = self._view(repo, rest[0])
            if view == r["commits"][b["commit"]]:
                return 400, {"message": "commit: no changes"}
            cid, _ = self._new_commit(repo, view)
            r["commits"][cid] = view
            r.setdefault("parents", {})[cid] = [b["commit"]]
            b.update(commit=cid, staged={})
            r.setdefault("commit_log", []).append((rest[0], cid, body["message"], body.get("metadata", {})))
            return 201, {"id": cid}
        return 404, {}

    def _merge(self, r, source, dest, body):
        """Three-way merge of a branch or a commit into dest: dest's tree plus the source's changes since its base."""
        dst = r["branches"][dest]
        want = body.get("expected_head")                             # kaos-lake: merge only onto this head
        if want and want != dst["commit"]:
            return 412, {"message": f"expected head {want} but {dest} is at {dst['commit']}"}
        if source in r["branches"]:
            src_commit, base_id = r["branches"][source]["commit"], r["branches"][source]["base"]
        else:                                                        # a commit id: its base is its parent
            src_commit, base_id = source, r.get("parents", {})[source][0]
        base, head = r["commits"][base_id], r["commits"][src_commit]
        tree = dict(r["commits"][dst["commit"]])
        for path in set(base) | set(head):
            if head.get(path) == base.get(path):
                continue
            if path in head:
                tree[path] = head[path]
            else:
                tree.pop(path, None)
        if tree == r["commits"][dst["commit"]]:
            return 400, {"message": "merge: no changes"}
        repo = next(n for n, x in self.repos.items() if x is r)
        cid, _ = self._new_commit(repo, tree)
        r.setdefault("parents", {})[cid] = [dst["commit"], src_commit]
        dst["commit"] = cid
        r.setdefault("commit_log", []).append((dest, cid, body["message"], body.get("metadata", {})))
        return 200, {"reference": cid}

    def _refs(self, repo, ref, rest, q):
        view = self._view(repo, ref)
        if rest[0] == "objects" and len(rest) == 2:  # objects/ls
            pre = q.get("prefix", "")
            return 200, {"results": [{"path": p, "path_type": "object", "size_bytes": len(c), "mtime": self.repos[repo].get("mtimes", {}).get(p, 0),
                                      "checksum": hashlib.md5(c).hexdigest()}
                                     for p, c in sorted(view.items()) if p.startswith(pre)],
                         "pagination": {"has_more": False}}
        return 200, view[q["path"]]  # objects?path=


def _is_multipart(req):
    return "multipart" in (req.headers.get("Content-Type") or "")


def _multipart_content(req) -> bytes:
    raw = b"Content-Type: " + req.headers["Content-Type"].encode() + b"\r\n\r\n" + req.body
    for part in BytesParser().parsebytes(raw).get_payload():
        return part.get_payload(decode=True) or b""
    return b""
