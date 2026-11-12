"""The writer: seal an output on a run branch, promote it onto main on an expected head, and what a failing,
retried or overlapping step leaves behind."""
import json
import pathlib

import pytest

from kaos_lib import lock, step, transfer, writer
from kaos_lib.errors import AuthError, LakeFSError, StepError

REPO = "dataset-clean"
FIXTURES = pathlib.Path(__file__).with_name("contract_fixtures")
ONE = {"a/1.bin": b"one", "a/2.bin": b"two", "b/3.bin": b"three"}


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
    assert tag == f"k-run-1-prepare-{commit[:12]}" and lake.tree(REPO, commit) == ONE and commit != version


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
    assert one != two and tags(lake) == {f"k-run-1-prepare-{one[:12]}": one, f"k-run-1-prepare-{two[:12]}": two}
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
