"""A key for another project's lakeFS expires; a long read gets a fresh one without the app noticing.

Two fake lakeFS: the own one (project b) gives an app a key of the owner's (project a) at each request for one; the owner's
accepts only the keys it gave and not the ones that expired.
"""
import base64
import datetime as dt
import threading
import time

import pytest

from fake_lakefs import FakeLakeFS
from kaos_lib import credentials, datasets, lakefs
from kaos_lib.errors import AuthError
from kaos_lib.lakefs import LakeFS

OWN_BASE, A_ENDPOINT = "http://b-lakefs.ml-b.svc.cluster.local", "http://a-lakefs.ml-a.svc.cluster.local"
PEERS = {"project": "b", "peers": [{"project": "a", "endpoint": A_ENDPOINT, "url": "https://lakefs-a.example"}]}
REF = datasets.DatasetRef.parse("a/dataset-raw@v1")
FILES = {f"f{i:02d}.bin": f"data-{i}".encode() for i in range(12)}


class Issuer:
    """What the own lakeFS answers to a request for a key: a new one each time, which the owner then accepts."""

    def __init__(self, owner, ttls=(3600,)):
        self.owner, self.ttls, self.n = owner, list(ttls), 0
        owner.valid_auth = set()
        self.lock = threading.Lock()

    def __call__(self, request):
        with self.lock:
            self.n += 1
            key, secret = f"KAOSX{self.n:015d}", f"secret-{self.n}"
            self.owner.valid_auth.add("Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode())
            ttl = self.ttls[min(self.n, len(self.ttls)) - 1]
        expires = dt.datetime.fromtimestamp(lakefs._now() + ttl, dt.timezone.utc)   # the clock the client reads
        return 200, {"access_key_id": key, "secret_access_key": secret,
                     "expiration": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}

    def expire_all(self):
        self.owner.valid_auth.clear()


@pytest.fixture
def world(mesh, monkeypatch, tmp_path):
    own, owner = FakeLakeFS(OWN_BASE), FakeLakeFS(A_ENDPOINT)
    own.kaos["/kaos/v1/peers"] = (200, PEERS)
    owner.add_repo("dataset-raw", files=dict(FILES))
    owner.tag("dataset-raw", "v1")
    mesh.update({OWN_BASE: own, A_ENDPOINT: owner})
    issuer = Issuer(owner)
    own.kaos["/kaos/v1/shared-credentials"] = issuer
    monkeypatch.setenv("LAKEFS_ENDPOINT", OWN_BASE)
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK-B")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK-B")
    monkeypatch.setenv("KUBECORE_ML_HOME", str(tmp_path / "home"))
    return own, owner, issuer


def on_object_get(owner, nth, action):
    """Run action at the nth object download the owner gets (before it is answered)."""
    seen = []
    lock = threading.Lock()

    def hook(fake, request):
        if request.method == "GET" and request.url.split("?")[0].endswith("/objects"):
            with lock:
                seen.append(1)
                if len(seen) == nth:
                    action()
    owner.hook = hook


def app(concurrency):
    return LakeFS(OWN_BASE, credentials.resolve(OWN_BASE), concurrency=concurrency)


def downloaded(path):
    return {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}


def test_an_expired_key_is_replaced_in_the_middle_of_a_download(world):
    own, owner, issuer = world
    on_object_get(owner, 5, issuer.expire_all)
    path = datasets.materialize(REF, client=app(1))
    assert downloaded(path) == FILES                         # every object, from the first to the last
    assert len(own.exchanges()) == 2 and owner.denied == 1   # one refusal, one new key, no more
    gets = [c for c in owner.calls if c[0] == "GET" and c[1].endswith("/objects")]
    assert len(gets) == len(FILES) + 1                       # the refused request is the only one repeated


def test_a_key_near_its_end_is_replaced_before_it_is_refused(world, monkeypatch):
    own, owner, issuer = world
    offset = [0]
    monkeypatch.setattr(lakefs, "_now", lambda: time.time() + offset[0])
    on_object_get(owner, 4, lambda: offset.__setitem__(0, 3550))     # 50 s before the key's end
    path = datasets.materialize(REF, client=app(1))
    assert downloaded(path) == FILES
    assert len(own.exchanges()) == 2 and owner.denied == 0


def test_concurrent_downloads_share_one_new_key(world):
    own, owner, issuer = world
    on_object_get(owner, 3, issuer.expire_all)
    path = datasets.materialize(REF, client=app(16))
    assert downloaded(path) == FILES
    assert len(own.exchanges()) == 2                        # not one for each of the 16 workers


def test_a_share_withdrawn_in_the_middle_is_said_so_and_does_not_loop(world):
    own, owner, issuer = world

    def withdraw():
        issuer.expire_all()
        own.kaos["/kaos/v1/shared-credentials"] = (403, {"message": "a shares no dataset with your project"})
    on_object_get(owner, 5, withdraw)
    with pytest.raises(AuthError, match="the share was withdrawn") as err:
        datasets.materialize(REF, client=app(1))
    assert "expired" not in str(err.value) and "a" in str(err.value)
    assert len(own.exchanges()) == 2                         # the first key and one try for another


def test_a_dataset_no_longer_shared_with_a_fresh_key_is_said_so(world):
    own, owner, issuer = world

    def withdraw():
        issuer.expire_all()
        owner.deny = "refused"                                # the group still exists, the dataset is out of it
    on_object_get(owner, 5, withdraw)
    with pytest.raises(AuthError, match="the share was withdrawn"):
        datasets.materialize(REF, client=app(1))
    assert len(own.exchanges()) == 2


def test_the_first_refusal_is_not_a_withdrawal(world):
    own, owner, issuer = world
    owner.deny = "refused"                                    # never shared: nothing was read before
    with pytest.raises(AuthError, match="not shared with your project") as err:
        datasets.materialize(REF, client=app(1))
    assert "withdrawn" not in str(err.value)


def test_a_person_with_a_token_has_no_key_to_replace(world, monkeypatch):
    own, owner, issuer = world
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "person")
    monkeypatch.delenv("LAKEFS_ACCESS_KEY")
    monkeypatch.delenv("LAKEFS_SECRET_KEY")
    owner.valid_auth = {"Bearer person"}
    on_object_get(owner, 3, lambda: owner.valid_auth.clear())
    with pytest.raises(AuthError):
        datasets.materialize(REF, client=app(1))
    assert own.exchanges() == []
