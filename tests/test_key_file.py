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
