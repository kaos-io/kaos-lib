"""The writer: seal an output on a run branch, promote it onto main on an expected head, and what a failing,
retried or overlapping step leaves behind."""
import datetime as dt
import json
import pathlib
import time

import pytest

from kaos_lib import lock, step, transfer, writer
from kaos_lib.errors import AuthError, LakeFSError, StepError

REPO = "dataset-clean"
FIXTURES = pathlib.Path(__file__).with_name("contract_fixtures")
ONE = {"a/1.bin": b"one", "a/2.bin": b"two", "b/3.bin": b"three"}
START = dt.datetime(2026, 11, 12, 10, 0, 0, tzinfo=dt.timezone.utc)


class Clock:
    """The time a run seals at: the names of the kept versions carry it. Moves only when a test says so."""
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def stamp(self, when=None):
        return writer._stamp(when or self.now)


def kept(run, commit, step="prepare", stamp=writer._stamp(START)):
    """The tag a sealed version is kept under."""
    return f"k-{stamp}-{run}-{step}-{commit[:12]}"


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(writer, "_now", c)
    return c


@pytest.fixture
def small_files_count(monkeypatch):
    """The tests use files of a few bytes: look for a version to copy from whatever the size."""
    monkeypatch.setattr(writer, "MIN_REUSE_BYTES", 0)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(transfer, "RETRY_PAUSE_S", 0)


@pytest.fixture
def lake(fake):
    fake.add_repo(REPO, metadata={"kaos.kind": "dataset"})
    return fake


def folder(tmp_path, files, name="out"):
    root = tmp_path / name
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(content)
    return root


def sealed(client, root, run="run-1", repo=REPO, prefix="", dataset=True):
    return writer.seal(client, repo, root, name="clean", prefix=prefix, branch=writer.run_branch(run, "prepare", "clean"),
                       tag_prefix=writer.keep_prefix(run, "prepare") if dataset else None,
                       message=f"clean: {run}", meta={"kaos.run": run, "kaos.step": "prepare"})


def save(client, root, promote=False, **kw):
    """What ``step.result()`` does for one output: seal, then promote when asked."""
    s = sealed(client, root, **kw)
    try:
        return writer.promote(s) if promote else s.commit
    finally:
        writer.discard(s)


def uploads(fake):
    return sorted(path for kind, _, _, path in fake.writes if kind == "POST")


def tags(fake, repo=REPO):
    return fake.repos[repo]["tags"]


def test_a_promoted_run_makes_main_hold_exactly_the_folder_and_keeps_the_sealed_commit(lake, client, tmp_path):
    first = lake.head(REPO)
    version = save(client, folder(tmp_path, ONE), promote=True)
    assert version == lake.head(REPO) != first and lake.tree(REPO, version) == ONE
    assert set(lake.repos[REPO]["branches"]) == {"main"}                           # the run branch is gone
    assert all(branch == "run-run-1-prepare-clean" for _, _, branch, _ in lake.writes)   # nothing written to main
    (tag, commit), = tags(lake).items()
    assert tag == kept("run-1", commit) and lake.tree(REPO, commit) == ONE and commit != version
    # the merge that moved `latest` names the version it promoted, so the data store never expires that version
    assert client.commit_info(REPO, version)["metadata"]["kaos.promoted"] == commit


def test_a_run_that_does_not_promote_seals_a_version_and_leaves_latest_alone(lake, client, tmp_path):
    first = lake.head(REPO)
    version = save(client, folder(tmp_path, ONE))
    assert lake.head(REPO) == first and lake.tree(REPO, "main") == {}
    assert list(tags(lake).values()) == [version] and lake.tree(REPO, version) == ONE
    assert set(lake.repos[REPO]["branches"]) == {"main"}


def test_the_commit_says_which_run_made_it(lake, client, tmp_path):
    version = save(client, folder(tmp_path, ONE), promote=True)
    message, meta = lake.commit_meta(REPO, version)
    assert message == "clean: run-1" and meta["kaos.run"] == "run-1" and meta["kaos.step"] == "prepare"


def test_a_second_run_with_one_changed_file_uploads_one_file(lake, client, tmp_path):
    save(client, folder(tmp_path, ONE), promote=True)
    lake.writes.clear()
    changed = {**ONE, "a/2.bin": b"two, changed"}
    version = save(client, folder(tmp_path, changed, "second"), promote=True, run="run-2")
    assert uploads(lake) == ["a/2.bin"] and lake.tree(REPO, version) == changed


def test_a_file_that_is_gone_from_the_folder_is_gone_from_the_version(lake, client, tmp_path):
    save(client, folder(tmp_path, ONE), promote=True)
    lake.writes.clear()
    fewer = {k: v for k, v in ONE.items() if k != "b/3.bin"}
    version = save(client, folder(tmp_path, fewer, "second"), promote=True, run="run-2")
    assert lake.writes == [("DELETE", REPO, "run-run-2-prepare-clean", "b/3.bin")]
    assert lake.tree(REPO, version) == fewer


def test_the_same_content_as_main_makes_no_new_version(lake, client, tmp_path):
    first = save(client, folder(tmp_path, ONE), promote=True)
    lake.writes.clear()
    assert save(client, folder(tmp_path, ONE, "same"), promote=True, run="run-2") == first == lake.head(REPO)
    assert lake.writes == [] and len(tags(lake)) == 1 and set(lake.repos[REPO]["branches"]) == {"main"}


def test_a_retry_with_the_same_content_reuses_the_sealed_commit_and_its_tag(lake, client, tmp_path):
    """The engine retries a step: every attempt writes the same files. Nothing new is made, however often."""
    commits = {save(client, folder(tmp_path, ONE, f"o{i}")) for i in range(8)}
    assert len(commits) == 1 and list(tags(lake).values()) == list(commits)


def test_a_retry_with_other_content_seals_another_commit_with_its_own_tag(lake, client, tmp_path):
    one = save(client, folder(tmp_path, ONE))
    two = save(client, folder(tmp_path, {"other.bin": b"o"}, "second"))
    assert one != two and tags(lake) == {kept("run-1", one): one, kept("run-1", two): two}
    assert save(client, folder(tmp_path, ONE, "third")) == one                     # an earlier attempt's: reused


def test_a_sealed_commit_is_not_reused_once_main_has_moved(lake, client, tmp_path):
    """Promoting a commit that was staged on an older head would mix in what the other run changed."""
    save(client, folder(tmp_path, {"x": b"x"}))
    save(client, folder(tmp_path, {"other": b"o"}, "other"), promote=True, run="run-2")
    again = save(client, folder(tmp_path, {"x": b"x"}, "again"), promote=True)
    assert lake.tree(REPO, again) == {"x": b"x"} and len(tags(lake)) == 3


def test_two_promoting_runs_the_second_is_refused_restages_and_main_is_never_a_mix(lake, client, tmp_path):
    if hasattr(lake, "server") and not lake.server.is_kaos_lake:
        pytest.skip("needs kaos-lake: upstream lakeFS ignores expected_head")
    a = folder(tmp_path, {"only-a.bin": b"a", "shared.bin": b"from a"}, "a")
    b = folder(tmp_path, {"only-b.bin": b"b", "shared.bin": b"from b"}, "b")
    real, seen = client.merge, []

    def merge(*args, **kw):
        if not seen:                                  # B is about to merge: A gets in first
            seen.append("a")
            save(lake.client(), a, promote=True, run="run-a")
        try:
            return real(*args, **kw)
        except LakeFSError as exc:
            seen.append(exc.status)
            raise

    client.merge = merge
    version = save(client, b, promote=True, run="run-b")
    assert seen == ["a", 412] and version == lake.head(REPO)
    assert lake.tree(REPO, "main") == {"only-b.bin": b"b", "shared.bin": b"from b"}


def test_a_dataset_that_keeps_moving_fails_after_three_tries_naming_the_tag_of_the_commit_it_kept(lake, client, tmp_path):
    client.merge = lambda *a, **k: (_ for _ in ()).throw(LakeFSError("main moved", 412))
    s = sealed(client, folder(tmp_path, ONE))
    with pytest.raises(StepError) as err:
        writer.promote(s)
    assert (f"dataset-clean changed 3 times while this step was promoting it. Another run is writing the same "
            f"dataset. The sealed version {s.commit[:12]} is kept as {s.tag}.") in str(err.value)
    assert tags(lake)[s.tag] == s.commit and lake.tree(REPO, "main") == {}
    writer.discard(s)
    assert set(lake.repos[REPO]["branches"]) == {"main"}


def test_a_merge_names_the_head_it_expects_and_merges_the_sealed_commit_not_the_branch_name(lake, client, tmp_path):
    first, calls = lake.head(REPO), []
    real = client.merge
    client.merge = lambda *a, **k: calls.append((a[1], k.get("expected_head"))) or real(*a, **k)
    s = sealed(client, folder(tmp_path, ONE))
    writer.promote(s)
    assert calls == [(s.commit, first)]


def test_a_second_live_attempt_cannot_swap_content_under_the_first(lake, client, tmp_path):
    """Attempt A sealed; attempt B of the same step restages the same branch name and seals other content; A then
    promotes. A's commit is merged, not whatever the branch name holds now."""
    a, b = folder(tmp_path, {"a.bin": b"a"}, "a"), folder(tmp_path, {"b.bin": b"b"}, "b")
    s = sealed(client, a)
    sealed(lake.client(), b)                          # B: restages run-run-1-prepare-clean, seals, pauses
    version = writer.promote(s)
    assert lake.tree(REPO, "main") == {"a.bin": b"a"} and lake.tree(REPO, version) == {"a.bin": b"a"}


def test_an_output_below_a_prefix_is_exactly_what_this_attempt_wrote(lake, client, tmp_path):
    """A model or an artifact: a retry never leaves a file of an earlier attempt (the old RunWriter kept them)."""
    lake.add_repo("outputs-myapp", metadata={"kaos.kind": "outputs"})
    prefix = "report/exp/run-1/"
    for attempt, name in enumerate(("shard-attempt1.bin", "shard-attempt2.bin")):
        s = sealed(client, folder(tmp_path, {name: b"data", "same.bin": b"s"}, f"o{attempt}"), repo="outputs-myapp",
                   prefix=prefix, dataset=False)
        merged = writer.promote(s)
        writer.discard(s)
    assert sorted(lake.tree("outputs-myapp", merged)) == [prefix + "same.bin", prefix + "shard-attempt2.bin"]
    assert not lake.repos["outputs-myapp"]["tags"]                                   # no tags for outputs


def test_an_output_below_a_prefix_leaves_what_other_steps_wrote(lake, client, tmp_path):
    lake.add_repo("outputs-myapp", metadata={"kaos.kind": "outputs"}, files={"model/exp/run-1/w.pt": b"w"})
    s = sealed(client, folder(tmp_path, {"r.json": b"{}"}), repo="outputs-myapp", prefix="report/exp/run-1/",
               dataset=False)
    merged = writer.promote(s)
    assert sorted(lake.tree("outputs-myapp", merged)) == ["model/exp/run-1/w.pt", "report/exp/run-1/r.json"]


def test_a_step_killed_while_uploading_leaves_no_version_and_the_retry_seals_once(lake, client, tmp_path):
    first, real, count = lake.head(REPO), client.upload_object, []

    def dies(repo, branch, path, local):
        count.append(path)
        if len(count) == 2:
            raise KeyboardInterrupt("killed")
        return real(repo, branch, path, local)

    client.upload_object, client.concurrency = dies, 1
    with pytest.raises(KeyboardInterrupt):
        save(client, folder(tmp_path, ONE), promote=True)
    assert lake.head(REPO) == first and tags(lake) == {} and lake.repos[REPO].get("commit_log", []) == []
    client.upload_object = real
    version = save(client, folder(tmp_path, ONE), promote=True)
    assert lake.tree(REPO, version) == ONE
    assert [c for branch, c, *_ in lake.repos[REPO]["commit_log"] if branch == "main"] == [version]
    assert len(tags(lake)) == 1


@pytest.mark.parametrize("fails", ["upload", "commit", "verify"])
def test_a_failing_seal_leaves_no_run_branch_behind(lake, client, tmp_path, fails):
    if fails == "upload":
        client.upload_object = lambda *a: (_ for _ in ()).throw(LakeFSError("refused", 400))
    elif fails == "commit":
        client.commit = lambda *a, **k: (_ for _ in ()).throw(LakeFSError("boom", 500))
    else:
        real = client.list_objects
        client.list_objects = lambda repo, ref, prefix="": (o for o in real(repo, ref, prefix) if o["path"] != "b/3.bin")
    with pytest.raises((LakeFSError, StepError)):
        save(client, folder(tmp_path, ONE), promote=True)
    assert set(lake.repos[REPO]["branches"]) == {"main"} and lake.tree(REPO, "main") == {}


def test_an_upload_that_fails_in_passing_is_tried_again(lake, client, tmp_path):
    lake.upload_answers = [503, 502, 500]
    client.concurrency = 1
    version = save(client, folder(tmp_path, {"only.bin": b"x"}), promote=True)
    assert lake.tree(REPO, version) == {"only.bin": b"x"} and lake.upload_answers == []


def test_an_upload_that_keeps_failing_fails_the_step_and_seals_nothing(lake, client, tmp_path):
    lake.upload_answers = [503] * 4
    with pytest.raises(LakeFSError, match="HTTP 503"):
        save(client, folder(tmp_path, {"only.bin": b"x"}), promote=True)
    assert lake.repos[REPO].get("commit_log", []) == [] and tags(lake) == {}


def test_a_refused_upload_is_not_tried_again(lake, client, tmp_path):
    lake.upload_answers = [403, 201]
    with pytest.raises(AuthError):
        save(client, folder(tmp_path, {"only.bin": b"x"}))
    assert lake.upload_answers == [201]


def test_a_branch_that_does_not_hold_what_the_step_wrote_is_not_sealed(lake, client, tmp_path):
    real = client.upload_object
    client.upload_object = lambda repo, branch, path, local: None if path == "a/2.bin" else real(repo, branch, path, local)
    with pytest.raises(StepError, match=r"output 'clean': 1 files differ between what the step wrote and what "
                                        r"lakeFS holds in dataset-clean at run-run-1-prepare-clean \(first: a/2.bin\). "
                                        r"Nothing was sealed."):
        save(client, folder(tmp_path, ONE), promote=True)
    assert lake.repos[REPO].get("commit_log", []) == [] and lake.tree(REPO, "main") == {}


def test_a_sealed_version_that_is_not_what_the_step_wrote_is_not_promoted(lake, client, tmp_path):
    real = client.list_objects

    def listing(repo, ref, prefix=""):
        for o in real(repo, ref, prefix):
            yield dict(o, checksum="0" * 32) if ref not in ("main", "run-run-1-prepare-clean") and o["path"] == "b/3.bin" else o

    client.list_objects = listing
    with pytest.raises(StepError, match=r"\(first: b/3.bin\). It was not promoted."):
        save(client, folder(tmp_path, ONE), promote=True)
    assert lake.tree(REPO, "main") == {}


def test_a_dataset_the_platform_has_not_created_yet(client, tmp_path):
    with pytest.raises(StepError, match="dataset-ghost does not exist. The platform creates the dataset or the "
                                        "outputs of an app when its pipeline declares them"):
        sealed(client, folder(tmp_path, ONE), repo="dataset-ghost")


def test_names_of_the_branch_and_the_tag():
    assert writer.run_branch("run 7/x", "prep.data", "clean") == "run-run-7-x-prep-data-clean"
    assert writer.keep_prefix("hera-demo-x7k2p", "prepare") == "k-hera-demo-x7k2p-prepare"


# ----------------------------------------------------------------------------------- through the step API
@pytest.fixture
def started(lake, monkeypatch, tmp_path):
    lake.add_repo("dataset-raw-images", metadata={"kaos.kind": "dataset"}, files={"x.bin": b"x"})
    lake.add_repo("dataset-hera-demo-embeddings", metadata={"kaos.kind": "dataset"})
    lake.add_repo("outputs-hera-demo", metadata={"kaos.kind": "outputs"})
    monkeypatch.setattr(step, "_connect", lambda: lake.client())

    def start(name="context-no-upstream", edit=lambda c: c, attempt=0):
        work = tmp_path / f"work{attempt}"                        # a new pod: an empty /work
        monkeypatch.setattr(step, "WORK", str(work))
        monkeypatch.setattr(step, "RESULT_FILE", str(work / "output" / "kaos-result.json"))
        text = (FIXTURES / f"{name}.json").read_text().replace("1" * 64, lake.head("dataset-raw-images"))
        monkeypatch.setenv(step.ENV, lock.wire(edit(json.loads(text))))
        return step.start()

    yield start
    step.stop()


def result_file():
    return pathlib.Path(step.RESULT_FILE)


@pytest.mark.parametrize("context,promoted", [("context-no-upstream", False), ("context-promote", True)])
def test_a_step_that_produces_a_dataset_seals_it_and_promotes_only_when_the_run_asks(started, lake, context, promoted):
    first = lake.head("dataset-hera-demo-embeddings")
    started(context)
    step.input("raw")
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    step.result(rows=1)
    got = json.loads(result_file().read_text())
    commit = got["writes"][0]["commit"]
    assert got["writes"] == [{"name": "embeddings", "type": "dataset", "repo": "dataset-hera-demo-embeddings",
                              "commit": commit}]
    assert lake.tree("dataset-hera-demo-embeddings", commit) == {"e.npy": b"emb"}
    assert (lake.head("dataset-hera-demo-embeddings") == commit) is promoted
    assert (lake.head("dataset-hera-demo-embeddings") == first) is not promoted
    _, meta = lake.commit_meta("dataset-hera-demo-embeddings", commit)
    assert meta["kaos.read.raw"] == lake.head("dataset-raw-images") and meta["kaos.step"] == "prepare"


def two_outputs(c):
    c["produces"] = [{"name": "embeddings", "type": "dataset", "repo": "dataset-hera-demo-embeddings", "promote": True},
                     {"name": "second", "type": "dataset", "repo": "dataset-missing"}]
    return c


def test_a_step_that_fails_while_sealing_moves_no_latest(started, lake):
    """The first output is promoted only after every output is sealed: the second one cannot be, so nothing moves."""
    first = lake.head("dataset-hera-demo-embeddings")
    started(edit=two_outputs)
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    (step.output("second") / "s").write_bytes(b"s")
    with pytest.raises(StepError, match="dataset-missing does not exist"):
        step.result()
    assert lake.head("dataset-hera-demo-embeddings") == first and lake.tree("dataset-hera-demo-embeddings", "main") == {}
    assert not result_file().exists() and set(lake.repos["dataset-hera-demo-embeddings"]["branches"]) == {"main"}


def test_a_step_that_fails_while_promoting_the_second_dataset_has_moved_the_first(started, lake, monkeypatch):
    """The one case that cannot be undone (two repositories, two merges): documented, and the step still fails."""
    lake.add_repo("dataset-second", metadata={"kaos.kind": "dataset"})
    first, real = lake.head("dataset-hera-demo-embeddings"), lake.client

    def edit(c):
        two_outputs(c)["produces"][1].update(repo="dataset-second", promote=True)
        return c

    def client():
        c = real()
        merge = c.merge
        c.merge = lambda repo, *a, **k: (_ for _ in ()).throw(LakeFSError("down", 500)) if repo == "dataset-second" \
            else merge(repo, *a, **k)
        return c

    monkeypatch.setattr(step, "_connect", client)
    started(edit=edit)
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    (step.output("second") / "s").write_bytes(b"s")
    with pytest.raises(LakeFSError):
        step.result()
    assert lake.head("dataset-hera-demo-embeddings") != first and not result_file().exists()
    assert lake.tree("dataset-second", "main") == {}


def test_a_model_holds_only_the_files_of_the_attempt_that_made_the_result(started, lake):
    def edit(c):
        c["produces"] = [{"name": "report", "type": "artifact", "repo": "outputs-" + c["app"]},
                         {"name": "second", "type": "dataset", "repo": "dataset-missing"}]
        return c

    started(edit=edit, attempt=1)
    for name in ("report", "second"):
        (step.output(name) / "shard-attempt1.bin").write_bytes(b"data")
    with pytest.raises(StepError):
        step.result()
    step.stop()
    lock.reset()
    started(edit=lambda c: edit(c) | {"produces": edit(c)["produces"][:1]}, attempt=2)
    (step.output("report") / "shard-attempt2.bin").write_bytes(b"data")
    step.result()
    write = json.loads(result_file().read_text())["writes"][0]
    assert sorted(lake.tree(write["repo"], write["commit"])) == ["report/baseline/hera-demo-x7k2p/shard-attempt2.bin"]


def test_an_output_folder_is_empty_each_time_a_step_starts(started, tmp_path):
    started(attempt=1)
    (step.output("embeddings") / "left-over.bin").write_bytes(b"x")
    step.stop()
    lock.reset()
    started(attempt=1)                                              # the same /work again: a retry on the same pod
    assert list(step.output("embeddings").iterdir()) == []


def test_a_dataset_may_not_hold_a_file_in_the_platforms_folder(started, lake):
    started()
    out = step.output("embeddings")
    (out / ".kaos").mkdir()
    (out / ".kaos" / "notes").write_bytes(b"x")
    with pytest.raises(StepError, match=r"output 'embeddings' holds a file in \.kaos/, which the platform keeps"):
        step.result()
    assert lake.repos["dataset-hera-demo-embeddings"].get("commit_log", []) == []


def test_the_next_step_reads_exactly_what_the_step_before_wrote(started, lake, monkeypatch):
    started()
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    step.result()
    written = json.loads(result_file().read_text())
    step.stop()
    lock.reset()
    context = json.loads((FIXTURES / "context-one-upstream.json").read_text())
    context["ledger"]["reads"] = []
    context["upstream"]["prepare"] = written
    monkeypatch.setenv(step.ENV, lock.wire(context))
    step.start()
    assert (step.input("embeddings") / "e.npy").read_bytes() == b"emb"
    assert [r.as_dict() for r in lock.current().reads] == [
        {"name": "embeddings", "repo": "dataset-hera-demo-embeddings", "owner": None,
         "ref": written["writes"][0]["commit"], "commit": written["writes"][0]["commit"]}]


def test_an_app_that_may_not_write_says_so_and_a_rejected_credential_says_that(started, lake):
    started()
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    lake.deny = "refused"  # kaos-lake answers a policy refusal with 401 and "insufficient permissions"
    with pytest.raises(StepError, match="this app may not write dataset-hera-demo-embeddings: only what the step declares"):
        step.result()
    lake.deny = 401          # a credential the server does not know
    with pytest.raises(StepError, match=r"lakeFS rejected the credential this step was given, or it has expired. "
                                        r"The app cannot fix this: report it to the platform team with the run's "
                                        r"name \(hera-demo-x7k2p\)"):
        step.result()


# ------------------------------------------------- a run that does not promote reuses what the last run sealed
def copies(fake):
    return sorted(path for method, path in fake.calls if method == "POST" and path.endswith("/objects/copy"))


def test_a_second_unpromoted_run_with_the_same_files_copies_them_and_has_its_own_commit_and_tag(small_files_count, lake, client, tmp_path, capsys):
    a = save(client, folder(tmp_path, ONE), run="run-a")
    lake.writes.clear()
    lake.calls.clear()
    capsys.readouterr()
    b = save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert uploads(lake) == [] and len(copies(lake)) == 3
    assert b != a and lake.tree(REPO, b) == lake.tree(REPO, a) == ONE and lake.tree(REPO, "main") == {}
    assert sorted(tags(lake)) == sorted([kept("run-a", a), kept("run-b", b)])
    assert lake.commit_meta(REPO, b)[1]["kaos.run"] == "run-b"
    assert (f"output 'clean': 0 file(s) to upload, 0 to delete, 0 unchanged since the last version of {REPO}, "
            "3 reused from an earlier run (copied, not uploaded).") in capsys.readouterr().out


def test_a_third_run_that_changes_one_file_uploads_one_and_copies_the_rest(small_files_count, lake, client, tmp_path):
    save(client, folder(tmp_path, ONE), run="run-a")
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    lake.writes.clear()
    lake.calls.clear()
    changed = {**ONE, "a/2.bin": b"two, changed"}
    c = save(client, folder(tmp_path, changed, "third"), run="run-c")
    assert uploads(lake) == ["a/2.bin"] and len(copies(lake)) == 2 and lake.tree(REPO, c) == changed


def test_a_file_with_the_same_path_and_other_content_in_the_last_sealed_version_is_uploaded(small_files_count, lake, client, tmp_path):
    save(client, folder(tmp_path, {**ONE, "a/2.bin": b"other"}), run="run-a")
    lake.writes.clear()
    lake.calls.clear()
    b = save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert uploads(lake) == ["a/2.bin"] and len(copies(lake)) == 2 and lake.tree(REPO, b) == ONE


def test_the_newest_sealed_version_is_the_one_copied_from(small_files_count, lake, client, tmp_path, clock):
    save(client, folder(tmp_path, {"x": b"old"}), run="run-z")      # newest by time, not by the tag's name
    clock.now += dt.timedelta(minutes=5)
    newest = save(client, folder(tmp_path, {"x": b"new"}, "n"), run="run-a")
    lake.writes.clear()
    save(client, folder(tmp_path, {"x": b"new"}, "again"), run="run-b")
    assert uploads(lake) == [] and len(copies(lake)) == 1 and lake.tree(REPO, newest) == {"x": b"new"}


def test_a_copy_that_fails_uploads_the_file_and_the_step_succeeds(small_files_count, lake, client, tmp_path, monkeypatch, capsys):
    save(client, folder(tmp_path, ONE), run="run-a")
    lake.writes.clear()

    def refused(*a, **k):
        raise LakeFSError("copy failed: HTTP 404 gone", 404)

    monkeypatch.setattr(client, "copy_object", refused)
    capsys.readouterr()
    b = save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert uploads(lake) == sorted(ONE) and lake.tree(REPO, b) == ONE
    assert "3 of the 3 file(s) could not be copied and were uploaded." in capsys.readouterr().out


def test_a_copied_file_that_is_not_what_the_step_wrote_is_not_sealed(small_files_count, lake, client, tmp_path, monkeypatch):
    save(client, folder(tmp_path, ONE), run="run-a")
    monkeypatch.setattr(client, "copy_object", lambda repo, branch, path, src, ref: client.upload_object(
        repo, branch, path, folder(tmp_path, {"wrong": b"not it"}, "w") / "wrong"))
    with pytest.raises(StepError, match="files differ between what the step wrote and what lakeFS holds"):
        save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert set(lake.repos[REPO]["branches"]) == {"main"}


def test_without_a_kept_version_the_run_uploads_everything_as_before(small_files_count, lake, client, tmp_path, capsys):
    save(client, folder(tmp_path, ONE), run="run-a", dataset=False)      # sealed without a tag: nothing kept
    lake.calls.clear()
    capsys.readouterr()
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert copies(lake) == [] and len(uploads(lake)) >= 3
    assert f"output 'clean': 3 file(s) to upload, 0 to delete, 0 unchanged since the last version of {REPO}." \
        in capsys.readouterr().out


def test_promoting_a_run_that_copied_every_file_moves_latest_to_a_tree_that_holds_them_all(small_files_count, lake, client, tmp_path):
    save(client, folder(tmp_path, ONE), run="run-a")
    lake.calls.clear()
    version = save(client, folder(tmp_path, ONE, "second"), run="run-b", promote=True)
    assert len(copies(lake)) == 3 and version == lake.head(REPO) and lake.tree(REPO, version) == ONE


def test_a_dataset_that_main_already_holds_needs_no_copy(small_files_count, lake, client, tmp_path, capsys):
    save(client, folder(tmp_path, ONE), run="run-a", promote=True)
    lake.calls.clear()
    capsys.readouterr()
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert copies(lake) == []
    assert f"output 'clean': 0 file(s) to upload, 0 to delete, 3 unchanged since the last version of {REPO}." \
        in capsys.readouterr().out


def test_a_file_that_main_holds_and_the_last_sealed_version_changed_is_copied_over_main_s(small_files_count, lake, client, tmp_path):
    save(client, folder(tmp_path, {"x": b"v1", "y": b"y"}), run="run-a", promote=True)
    save(client, folder(tmp_path, {"x": b"v2", "y": b"y"}, "s"), run="run-b")        # sealed, not promoted
    lake.writes.clear()
    lake.calls.clear()
    c = save(client, folder(tmp_path, {"x": b"v2", "y": b"y"}, "t"), run="run-c")
    assert uploads(lake) == [] and len(copies(lake)) == 1 and lake.tree(REPO, c) == {"x": b"v2", "y": b"y"}


def calls_of(fake, kind):
    return [p for m, p in fake.calls if m == "GET" and p.endswith(kind)]


def test_looking_for_the_previous_version_never_reads_a_version(small_files_count, lake, client, tmp_path):
    save(client, folder(tmp_path, ONE), run="run-a")
    lake.calls.clear()
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert not [p for m, p in lake.calls if m == "GET" and "/commits/" in p]
    assert len(calls_of(lake, "/tags")) == 2          # one for an earlier attempt of this step, one for the newest version


def test_more_than_300_kept_versions_the_newest_is_still_found_with_a_bounded_number_of_calls(
        small_files_count, lake, client, tmp_path, clock):
    clock.now = START - dt.timedelta(hours=3)
    old = save(client, folder(tmp_path, {"x": b"old"}), run="run-z")
    clock.now = START - dt.timedelta(hours=1)
    newest = save(client, folder(tmp_path, {"x": b"new"}, "n"), run="run-a")
    for i in range(350):                                  # kept versions of other content, all older than the newest
        lake.tag(REPO, kept("run-f", old, stamp=writer._stamp(START - dt.timedelta(hours=2, seconds=i))), old)
    clock.now = START
    lake.writes.clear()
    lake.calls.clear()
    b = save(client, folder(tmp_path, {"x": b"new"}, "again"), run="run-b")
    assert uploads(lake) == [] and len(copies(lake)) == 1 and lake.tree(REPO, b) == lake.tree(REPO, newest)
    assert len(calls_of(lake, "/tags")) <= 3
    assert not [p for m, p in lake.calls if m == "GET" and "/commits/" in p]


@pytest.mark.parametrize("days_back, listings", [(3, 2), (20, 3), (200, 4)])
def test_a_version_sealed_long_ago_is_found_in_a_few_calls(small_files_count, lake, client, tmp_path, clock,
                                                             days_back, listings):
    clock.now = START - dt.timedelta(days=days_back)
    save(client, folder(tmp_path, ONE), run="run-a")
    clock.now = START
    lake.writes.clear()
    lake.calls.clear()
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert uploads(lake) == [] and len(copies(lake)) == 3
    assert len(calls_of(lake, "/tags")) == 1 + listings        # an earlier attempt, then the windows


def test_a_version_sealed_over_a_year_ago_is_not_looked_for(small_files_count, lake, client, tmp_path, clock):
    clock.now = START - dt.timedelta(days=400)
    save(client, folder(tmp_path, ONE), run="run-a")
    clock.now = START
    lake.writes.clear()
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert uploads(lake) == sorted(ONE)


def test_a_tag_of_another_form_is_never_a_source(small_files_count, lake, client, tmp_path):
    a = save(client, folder(tmp_path, ONE), run="run-a")
    lake.repos[REPO]["tags"].pop(kept("run-a", a))
    lake.repos[REPO]["tags"][f"k-run-a-prepare-{a[:12]}"] = a                  # the old form
    lake.writes.clear()
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert uploads(lake) == sorted(ONE)


@pytest.mark.parametrize("broken", ["tags", "listing"])
def test_a_lookup_that_fails_uploads_everything_and_the_step_succeeds(small_files_count, lake, client, tmp_path,
                                                                       monkeypatch, broken):
    a = save(client, folder(tmp_path, ONE), run="run-a")

    def refuse(*args, **kw):
        raise LakeFSError("refused", 401)

    if broken == "tags":
        real = client.tags
        monkeypatch.setattr(client, "tags", lambda repo, prefix="", after="": refuse() if after else real(repo, prefix))
    else:
        real = client.list_objects
        monkeypatch.setattr(client, "list_objects", lambda repo, ref, prefix="": refuse() if ref == a else real(repo, ref, prefix))
    lake.writes.clear()
    b = save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert uploads(lake) == sorted(ONE) and lake.tree(REPO, b) == ONE


def test_the_upload_after_a_failed_copy_is_tried_again_like_any_upload(small_files_count, lake, client, tmp_path,
                                                                        monkeypatch):
    save(client, folder(tmp_path, {"x": b"x"}), run="run-a")

    def refused(*a, **k):
        raise LakeFSError("copy failed", 404)

    monkeypatch.setattr(client, "copy_object", refused)
    lake.upload_answers.extend([503])                     # the first upload is answered "try again"
    b = save(client, folder(tmp_path, {"x": b"x"}, "second"), run="run-b")
    assert lake.tree(REPO, b) == {"x": b"x"} and lake.upload_answers == []


def test_a_promotion_refused_on_a_moved_head_seals_again_and_copies_from_the_last_version(
        small_files_count, lake, client, tmp_path, clock):
    if hasattr(lake, "server") and not lake.server.is_kaos_lake:
        pytest.skip("needs kaos-lake: upstream lakeFS ignores expected_head")
    save(client, folder(tmp_path, ONE), run="run-a")
    real, seen = client.merge, []

    def merge(*args, **kw):
        if not seen:                                  # run-b is about to merge: run-c gets in first
            seen.append("c")
            clock.now = START - dt.timedelta(hours=1)          # sealed earlier than run-b's version: the newest is run-b's
            save(lake.client(), folder(tmp_path, {"other": b"o"}, "c"), promote=True, run="run-c")
            clock.now = START
            lake.calls.clear()
            lake.writes.clear()
        return real(*args, **kw)

    client.merge = merge
    b = save(client, folder(tmp_path, ONE, "second"), run="run-b", promote=True)
    assert uploads(lake) == [] and len(copies(lake)) == 3          # the second seal copied them again
    assert lake.tree(REPO, b) == {**ONE}
    assert lake.head(REPO) == b


def test_a_dataset_sealed_below_a_prefix_copies_the_files_below_it(small_files_count, lake, client, tmp_path):
    save(client, folder(tmp_path, {"p/other.bin": b"o"}, "zero"), run="run-0", promote=True)       # not below q/
    files = {"q/a.bin": b"a", "q/d/b.bin": b"b"}
    first = save(client, folder(tmp_path, {"a.bin": b"a", "d/b.bin": b"b"}), run="run-a", prefix="q/")
    lake.writes.clear()
    lake.calls.clear()
    second = save(client, folder(tmp_path, {"a.bin": b"a", "d/b.bin": b"b"}, "second"), run="run-b", prefix="q/")
    assert uploads(lake) == [] and len(copies(lake)) == 2
    assert {p: c for p, c in lake.tree(REPO, second).items() if p.startswith("q/")} == files == \
        {p: c for p, c in lake.tree(REPO, first).items() if p.startswith("q/")}
    assert lake.tree(REPO, second)["p/other.bin"] == b"o"


def test_paths_with_spaces_and_unicode_go_through_a_copy(small_files_count, lake, client, tmp_path):
    files = {"dir é/ファイル 1.bin": b"one", "a b/c#d?e&f.bin": b"two", "plain.bin": b"three"}
    save(client, folder(tmp_path, files), run="run-a")
    lake.writes.clear()
    lake.calls.clear()
    b = save(client, folder(tmp_path, files, "second"), run="run-b")
    assert uploads(lake) == [] and len(copies(lake)) == 3 and lake.tree(REPO, b) == files


def test_two_runs_sealing_at_once_each_get_their_own_version_and_copy_everything(small_files_count, lake, client, tmp_path):
    import concurrent.futures as cf
    a = save(client, folder(tmp_path, ONE), run="run-a")
    lake.writes.clear()
    lake.calls.clear()
    roots = {run: folder(tmp_path, ONE, run) for run in ("run-b", "run-c")}
    with cf.ThreadPoolExecutor(2) as ex:
        done = dict(zip(roots, ex.map(lambda r: save(lake.client(), roots[r], run=r), roots)))
    assert uploads(lake) == [] and len(copies(lake)) == 6
    assert len({a, *done.values()}) == 3 and all(lake.tree(REPO, c) == ONE for c in done.values())
    assert sorted(tags(lake)) == sorted([kept("run-a", a), kept("run-b", done["run-b"]), kept("run-c", done["run-c"])])


class CountingClient:
    """What a plan needs of a client: the objects of a version. Counts the calls."""
    def __init__(self, held):
        self.held, self.listed = held, 0

    def list_objects(self, repo, ref, prefix=""):
        self.listed += 1
        return self.held


def test_twenty_thousand_reusable_files_are_planned_in_one_pass(tmp_path):
    from kaos_lib.transfer import MirrorPlan
    n = 20_000
    files = {f"d/{i:05d}.bin": (4, f"{i:032x}") for i in range(n)}
    held = [{"path": p, "size_bytes": size, "checksum": md5} for p, (size, md5) in files.items()]
    s = writer.Sealed(CountingClient(held), REPO, "clean", tmp_path, "", "b", "k-r-s", "m", {}, files=files)
    plan = MirrorPlan(add=[(tmp_path / p, p) for p in files] + [(tmp_path / "new", "new")])
    s.files["new"] = (1, "0" * 32)
    started = time.monotonic()
    same = writer._reuse(s, plan, "previous")
    assert len(same) == n and [p for _, p in plan.add] == ["new"] and s.client.listed == 1
    assert time.monotonic() - started < 3        # the quadratic filter took minutes


def test_a_small_output_looks_for_no_earlier_version(lake, client, tmp_path):
    save(client, folder(tmp_path, ONE), run="run-a")
    lake.calls.clear()
    lake.writes.clear()
    save(client, folder(tmp_path, ONE, "second"), run="run-b")
    assert copies(lake) == [] and len(calls_of(lake, "/tags")) == 1 and uploads(lake) == sorted(ONE)       # the retry lookup only


def test_an_output_of_a_megabyte_or_more_looks_for_one(lake, client, tmp_path):
    big = {"big.bin": b"x" * (1 << 20)}
    save(client, folder(tmp_path, big), run="run-a")
    lake.writes.clear()
    save(client, folder(tmp_path, big, "second"), run="run-b")
    assert uploads(lake) == [] and len(copies(lake)) == 1


# ---------------------------------------------------------------------- an earlier attempt is this run's and this step's
def _seal_as(client, root, run, step_name):
    return writer.seal(client, REPO, root, name="clean", branch=writer.run_branch(run, step_name, "clean"),
                       tag_prefix=writer.keep_prefix(run, step_name), message=f"m {run} {step_name}",
                       meta={"kaos.run": run, "kaos.step": step_name})


def test_reuse_commit_of_other_run_or_step(lake, client, tmp_path):
    a = _seal_as(client, folder(tmp_path, {"f": b"1"}), "r1-x", "y")
    writer.discard(a)
    b = _seal_as(client, folder(tmp_path, {"f": b"1"}, "o2"), "r1", "x-y")
    assert b.commit != a.commit


def test_reuse_commit_of_other_step_same_run(lake, client, tmp_path):
    a = _seal_as(client, folder(tmp_path, {"f": b"1"}), "r1", "prepare-2")
    writer.discard(a)
    b = _seal_as(client, folder(tmp_path, {"f": b"1"}, "o2"), "r1", "prepare")
    assert b.commit != a.commit


def test_a_tag_of_this_run_and_step_is_reused_only_when_it_is_exact_and_names_this_run_and_step(lake, client, tmp_path):
    a = _seal_as(client, folder(tmp_path, {"f": b"1"}), "r1", "p")
    writer.discard(a)
    assert _seal_as(client, folder(tmp_path, {"f": b"1"}, "o2"), "r1", "p").commit == a.commit      # the real reuse
    prefix = writer.keep_prefix("r1", "p")
    # a tag with another suffix than the commit's own first 12 characters is not a candidate
    lake.repos[REPO]["tags"].pop(a.tag)
    lake.repos[REPO]["tags"][f"k-{writer._stamp(START)}-{prefix[2:]}-{'0' * 12}"] = a.commit
    assert _seal_as(client, folder(tmp_path, {"f": b"1"}, "o3"), "r1", "p").commit != a.commit


def test_a_model_merged_before_a_failing_dataset_promotion_stays_on_main_under_its_run_folder_until_a_retry(
        started, lake, monkeypatch):
    """Order of promotion, as documented: models and artifacts reach `main` first, then datasets. When a dataset's
    merge fails the model stays under `<name>/<experiment>/<run>/`, no result names it, and a retry replaces that
    folder with exactly what the retry wrote."""
    first, real = lake.head("dataset-hera-demo-embeddings"), lake.client

    def edit(c):
        c["produces"] = [{"name": "embeddings", "type": "dataset", "repo": "dataset-hera-demo-embeddings",
                          "promote": True},
                         {"name": "model", "type": "model", "repo": "outputs-hera-demo"}]
        return c

    def failing():
        c = real()
        merge = c.merge
        c.merge = lambda repo, *a, **k: (_ for _ in ()).throw(LakeFSError("down", 500)) \
            if repo == "dataset-hera-demo-embeddings" else merge(repo, *a, **k)
        return c

    folder = "model/baseline/hera-demo-x7k2p/"
    monkeypatch.setattr(step, "_connect", failing)
    started(edit=edit, attempt=1)
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    (step.output("model") / "first.bin").write_bytes(b"1")
    (step.output("model") / "gone-after-retry.bin").write_bytes(b"1")
    with pytest.raises(LakeFSError):
        step.result()
    assert lake.head("dataset-hera-demo-embeddings") == first and not result_file().exists()      # the dataset did not move
    assert sorted(lake.tree("outputs-hera-demo", "main")) == [folder + "first.bin", folder + "gone-after-retry.bin"]
    step.stop()
    lock.reset()
    monkeypatch.setattr(step, "_connect", lambda: real())
    started(edit=edit, attempt=2)
    (step.output("embeddings") / "e.npy").write_bytes(b"emb")
    (step.output("model") / "retry.bin").write_bytes(b"2")
    step.result()
    assert sorted(lake.tree("outputs-hera-demo", "main")) == [folder + "retry.bin"]
