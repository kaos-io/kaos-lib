"""A job on HPC gets the key pair of its app in a file (LAKEFS_KEY_FILE) that the platform keeps fresh."""
import base64
import json
import os
import time

import pytest

from fake_lakefs import FakeLakeFS
from kaos_lib import credentials, datasets, lakefs
from kaos_lib.errors import AuthError
from kaos_lib.lakefs import LakeFS

URL = "https://lakefs.example"
OWN_BASE, A_ENDPOINT = "http://b-lakefs.ml-b.svc.cluster.local", "http://a-lakefs.ml-a.svc.cluster.local"
PEERS = {"project": "b", "peers": [{"project": "a", "endpoint": A_ENDPOINT, "url": "https://lakefs-a.example"}]}
REF = datasets.DatasetRef.parse("a/dataset-raw@v1")
SECRETS = ("file-secret-AAA", "file-secret-BBB", "bearer-secret-token")


def iso(offset):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


def write_key(path, key="KAOSXFILEKEY000001", secret="file-secret-AAA", expires=3600, bump=0):
    path.write_text(json.dumps({"access_key_id": key, "secret_access_key": secret, "expiration": iso(expires)}))
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + bump))   # a coarse file clock must not hide a rewrite


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    monkeypatch.setenv("KUBECORE_ML_HOME", str(tmp_path / "home"))
    path = tmp_path / "key.json"
    monkeypatch.setenv("LAKEFS_KEY_FILE", str(path))
    return path


def basic(key, secret):
    return "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()


def test_the_key_file_gives_a_key_pair(keyfile):
    write_key(keyfile)
    cred = credentials.resolve(URL)
    assert (cred.access_key, cred.secret_key, cred.token) == ("KAOSXFILEKEY000001", "file-secret-AAA", None)
    assert cred.expires and abs(cred.expires - (time.time() + 3600)) < 5


def test_a_key_pair_wins_over_a_bearer(keyfile, monkeypatch):
    write_key(keyfile)
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "bearer-secret-token")
    cred = credentials.resolve(URL)
    assert cred.access_key == "KAOSXFILEKEY000001" and cred.token is None


def test_the_environment_pair_still_wins_over_the_file(keyfile, monkeypatch):
    write_key(keyfile)
    monkeypatch.setenv("LAKEFS_ACCESS_KEY", "AK")
    monkeypatch.setenv("LAKEFS_SECRET_KEY", "SK")
    assert credentials.resolve(URL).access_key == "AK"


@pytest.mark.parametrize("damage", ["expired", "garbage", "missing", "half"])
def test_a_bad_file_falls_back_to_the_bearer(keyfile, monkeypatch, damage):
    if damage == "expired":
        write_key(keyfile, expires=-10)
    elif damage == "garbage":
        keyfile.write_text("not json")
    elif damage == "half":
        keyfile.write_text(json.dumps({"access_key_id": "AK"}))
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "bearer-secret-token")
    assert credentials.resolve(URL).token == "bearer-secret-token"


@pytest.mark.parametrize("damage,words", [("expired", "has ended"), ("garbage", "cannot be read"),
                                          ("missing", "does not exist")])
def test_without_a_bearer_a_bad_file_says_what_is_missing(keyfile, damage, words):
    if damage == "expired":
        write_key(keyfile, expires=-10)
    elif damage == "garbage":
        keyfile.write_text("not json")
    with pytest.raises(AuthError, match=words) as err:
        credentials.resolve(URL)
    text = str(err.value)
    assert "key file" in text and "kaosctl login" in text
    assert "KAOS_" not in text and "kubectl" not in text


def test_the_client_rereads_a_changed_file(keyfile):
    write_key(keyfile)
    client = LakeFS(URL, credentials.resolve(URL))
    assert client.session.auth == ("KAOSXFILEKEY000001", "file-secret-AAA")
    client._fresh_key()
    assert client.session.auth == ("KAOSXFILEKEY000001", "file-secret-AAA")
    write_key(keyfile, key="KAOSXFILEKEY000002", secret="file-secret-BBB", bump=5)
    client._fresh_key()
    assert client.session.auth == ("KAOSXFILEKEY000002", "file-secret-BBB")
    assert client.credential.access_key == "KAOSXFILEKEY000002"


def test_the_client_rereads_a_key_near_its_end_and_keeps_it_when_nothing_new_is_there(keyfile, monkeypatch):
    write_key(keyfile, expires=60)
    client = LakeFS(URL, credentials.resolve(URL))
    client._fresh_key()                      # near the end, nothing new: the old key goes on, no error here
    assert client.session.auth[0] == "KAOSXFILEKEY000001"
    write_key(keyfile, key="KAOSXFILEKEY000002", secret="file-secret-BBB")   # same mtime second is possible
    client._fresh_key()
    assert client.session.auth[0] == "KAOSXFILEKEY000002"


def test_a_request_goes_with_the_key_the_file_holds_now(keyfile):
    write_key(keyfile)
    owner = FakeLakeFS(URL)
    owner.valid_auth = {basic("KAOSXFILEKEY000002", "file-secret-BBB")}
    cred = credentials.resolve(URL)
    s = lakefs._session(cred, 4)
    s.mount("https://", owner)
    client = LakeFS(URL, cred, session=s)
    write_key(keyfile, key="KAOSXFILEKEY000002", secret="file-secret-BBB", bump=5)
    client._call("GET", "/repositories")
    assert owner.denied == 0


@pytest.fixture
def world(mesh, keyfile, monkeypatch):
    own, owner = FakeLakeFS(OWN_BASE), FakeLakeFS(A_ENDPOINT)
    own.kaos["/kaos/v1/peers"] = (200, PEERS)
    owner.add_repo("dataset-raw", files={"f.bin": b"data"})
    owner.tag("dataset-raw", "v1")
    mesh.update({OWN_BASE: own, A_ENDPOINT: owner})
    peer_auth = own.serve_peer_key()
    owner.valid_auth = {peer_auth}
    own.valid_auth = {basic("KAOSXFILEKEY000001", "file-secret-AAA")}
    monkeypatch.setenv("LAKEFS_ENDPOINT", OWN_BASE)
    write_key(keyfile)
    return own, owner


def test_the_job_reads_a_shared_dataset_with_the_file_key(world, tmp_path):
    own, owner = world
    path = datasets.materialize(REF, client=LakeFS.connect())
    assert (path / "f.bin").read_bytes() == b"data"
    assert own.exchanges() == [{"owner": "a"}]
    assert own.denied == 0 and owner.denied == 0
    assert credentials.resolve(OWN_BASE).token is None      # the bearer was never needed


def test_no_secret_is_in_a_repr_or_an_error(keyfile, monkeypatch):
    write_key(keyfile)
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "bearer-secret-token")
    cred = credentials.resolve(URL)
    bearer = credentials.Credential(token="bearer-secret-token")
    for obj in (cred, bearer, LakeFS(URL, cred), LakeFS(URL, bearer)):
        for text in (repr(obj), str(obj)):
            assert not any(s in text for s in SECRETS), text
    keyfile.write_text('{"access_key_id": "KAOSXFILEKEY000001", "secret_access_key": "file-secret-AAA"')
    monkeypatch.delenv("LAKEFS_BEARER_TOKEN")
    with pytest.raises(AuthError) as err:
        credentials.resolve(URL)
    assert not any(s in str(err.value) for s in SECRETS)


# -- review findings: the bearer is left for good once the file holds a key ------------------------------

BEARER = "Bearer bearer-secret-token"


def bearer_client(keyfile, monkeypatch, base=URL, server=None):
    """A client made while the key file is absent, on the bearer."""
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "bearer-secret-token")
    cred = credentials.resolve(base)
    assert cred.token and cred.key_file == str(keyfile)
    s = lakefs._session(cred, 4)
    if server is not None:
        s.mount(base, server)
    return LakeFS(base, cred, session=s)


def test_a_client_on_the_bearer_takes_the_key_once_the_file_holds_one(keyfile, monkeypatch):
    server = FakeLakeFS(URL)
    client = bearer_client(keyfile, monkeypatch, server=server)
    client._call("GET", "/repositories")
    assert server.auth[-1] == BEARER
    write_key(keyfile)
    client._call("GET", "/repositories")
    assert server.auth[-1] == basic("KAOSXFILEKEY000001", "file-secret-AAA")
    assert "Authorization" not in client.session.headers and client.credential.token is None
    write_key(keyfile, key="KAOSXFILEKEY000002", secret="file-secret-BBB", bump=5)
    client._call("GET", "/repositories")
    assert server.auth[-1] == basic("KAOSXFILEKEY000002", "file-secret-BBB")


def test_the_peer_path_after_the_switch_uses_the_key_not_the_bearer(world, keyfile, monkeypatch):
    own, owner = world
    keyfile.unlink()
    own.valid_auth = {BEARER, basic("KAOSXFILEKEY000001", "file-secret-AAA")}
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "bearer-secret-token")
    client = LakeFS.connect()
    assert client.credential.token
    write_key(keyfile)
    path = datasets.materialize(REF, client=client)
    assert (path / "f.bin").read_bytes() == b"data"
    assert own.exchanges() == [{"owner": "a"}]          # the key-pair branch: an app's key in the owner's lakeFS
    assert BEARER not in own.auth[-2:] and own.auth[-1] == basic("KAOSXFILEKEY000001", "file-secret-AAA")
    peer = client._peer_clients["a"]
    assert peer.credential.token is None and "Authorization" not in peer.session.headers


def test_a_peer_client_made_on_the_bearer_is_not_kept_after_the_switch(world, keyfile, monkeypatch):
    own, owner = world
    keyfile.unlink()
    own.valid_auth = None
    owner.valid_auth = None
    monkeypatch.setenv("LAKEFS_BEARER_TOKEN", "bearer-secret-token")
    client = LakeFS.connect()
    old = client.for_owner("a")
    assert old.credential.token
    write_key(keyfile)
    new = client.for_owner("a")
    assert new is not old and new.credential.token is None


def test_a_replacement_that_keeps_the_mtime_is_picked_up_even_without_expiration(keyfile):
    keyfile.write_text(json.dumps({"access_key_id": "KAOSXFILEKEY000001", "secret_access_key": "file-secret-AAA"}))
    st = keyfile.stat()
    client = LakeFS(URL, credentials.resolve(URL))
    other = keyfile.with_name("next.json")
    other.write_text(json.dumps({"access_key_id": "KAOSXFILEKEY000002", "secret_access_key": "file-secret-BBB"}))
    os.utime(other, ns=(st.st_atime_ns, st.st_mtime_ns))        # same mtime, same size, another inode
    os.replace(other, keyfile)
    assert keyfile.stat().st_mtime_ns == st.st_mtime_ns
    client._fresh_key()
    assert client.session.auth == ("KAOSXFILEKEY000002", "file-secret-BBB")


def test_a_file_near_its_end_and_unchanged_is_read_at_most_every_few_seconds(keyfile, monkeypatch):
    write_key(keyfile, expires=60)
    client = LakeFS(URL, credentials.resolve(URL))
    clock = [time.time()]
    monkeypatch.setattr(lakefs, "_now", lambda: clock[0])
    reads = []
    real = credentials.read_key_file
    monkeypatch.setattr(credentials, "read_key_file", lambda p: reads.append(p) or real(p))
    for _ in range(50):
        client._fresh_key()
    assert len(reads) == 1
    clock[0] += lakefs.REREAD_GAP + 1
    for _ in range(50):
        client._fresh_key()
    assert len(reads) == 2


def test_two_threads_never_interleave_the_swap(keyfile):
    import threading
    write_key(keyfile)
    client = LakeFS(URL, credentials.resolve(URL))
    creds = [credentials.Credential(access_key=f"K{i}", secret_key=f"S{i}") for i in range(2)]
    stop, bad = threading.Event(), []

    def swap(cred):
        while not stop.is_set():
            client._install(cred)

    def watch():
        for _ in range(20000):
            with client._swapping:
                if client.session.auth != (client.credential.access_key, client.credential.secret_key):
                    bad.append(1)
    threads = [threading.Thread(target=swap, args=(c,)) for c in creds]
    for t in threads:
        t.start()
    watch()
    stop.set()
    for t in threads:
        t.join()
    assert not bad and client._generation > 0


def test_a_refusal_rereads_the_file_and_retries_once_with_a_different_key(keyfile):
    write_key(keyfile)
    server = FakeLakeFS(URL)
    server.valid_auth = {basic("KAOSXFILEKEY000001", "file-secret-AAA")}
    cred = credentials.resolve(URL)
    s = lakefs._session(cred, 4)
    s.mount("https://", server)
    client = LakeFS(URL, cred, session=s)
    # the platform writes a new key and the old one stops working before the stamp is looked at again
    server.valid_auth = {basic("KAOSXFILEKEY000002", "file-secret-BBB")}
    keyfile.write_text(json.dumps({"access_key_id": "KAOSXFILEKEY000002", "secret_access_key": "file-secret-BBB"}))
    st = client._key_stamp
    client._stamp_of_key_file = lambda: st          # the refusal, not the stamp, finds the change
    client._call("GET", "/repositories")
    assert server.denied == 1 and server.auth[-1] == basic("KAOSXFILEKEY000002", "file-secret-BBB")


def test_a_refusal_with_an_unchanged_file_is_raised_without_a_retry(keyfile):
    write_key(keyfile)
    server = FakeLakeFS(URL)
    server.valid_auth = set()
    cred = credentials.resolve(URL)
    s = lakefs._session(cred, 4)
    s.mount("https://", server)
    client = LakeFS(URL, cred, session=s)
    with pytest.raises(AuthError, match="rejected"):
        client._call("GET", "/repositories")
    assert server.denied == 1
