"""raw layout: any repository, whole tree or a prefix; label-driven layout choice; empty datasets."""
import pytest

from conftest import write_dataset
from kaos_lib import cli, datasets
from kaos_lib.errors import DatasetError, EmptyDataset
from kaos_lib import layouts

FILES = {"a.txt": b"A", "sub/b.txt": b"B", "sub/deep/c.bin": b"C", "other/d.txt": b"D"}


@pytest.fixture
def repo(fake):
    fake.add_repo("my-repo", ns="gs://b/x/my-repo", files=FILES)           # no kaos.template label
    return datasets.DatasetRef.parse("my-repo@latest")


def gets(fake):
    return [c for c in fake.calls if c[0] == "GET" and c[1].endswith("/objects")]


def test_raw_downloads_whole_tree_and_returns_the_directory(repo, fake, client, tmp_path):
    out = datasets.materialize(repo, tmp_path / "all", client=client)
    assert out == tmp_path / "all" and out.is_dir()
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file() and p.name[0] != "."} == set(FILES)
    assert (out / "sub/deep/c.bin").read_bytes() == b"C"


def test_raw_prefix_downloads_only_that_folder_relative_to_it(repo, fake, client, tmp_path):
    out = datasets.materialize(repo, tmp_path / "sub", client=client, prefix="sub")
    assert {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file() and p.name[0] != "."} == {
        "b.txt", "deep/c.bin"}


def test_raw_cache_is_keyed_by_repo_commit_and_prefix(repo, fake, client, tmp_path):
    whole = datasets.materialize(repo, client=client)
    sub = datasets.materialize(repo, client=client, prefix="sub")
    other = datasets.materialize(repo, client=client, prefix="other/")
    assert len({whole, sub, other}) == 3 and whole.parent == tmp_path / "cache" / "my-repo"
    n = len(gets(fake))
    assert datasets.materialize(repo, client=client) == whole
    assert datasets.materialize(repo, client=client, prefix="sub") == sub     # second calls are free
    assert len(gets(fake)) == n


def test_raw_new_commit_means_new_cache_entry(repo, fake, client):
    first = datasets.materialize(repo, client=client)
    fake.repos["my-repo"]["commits"]["cnew000"] = {"a.txt": b"A2"}
    fake.repos["my-repo"]["branches"]["main"]["commit"] = "cnew000"
    second = datasets.materialize(repo, client=client)
    assert first != second and (second / "a.txt").read_bytes() == b"A2"


def test_raw_pinned_commit(repo, fake, client, tmp_path):
    head = fake.head("my-repo")
    fake.repos["my-repo"]["commits"]["cnew000"] = {"a.txt": b"A2"}
    fake.repos["my-repo"]["branches"]["main"]["commit"] = "cnew000"
    out = datasets.materialize(repo, tmp_path / "o", client=client, commit=head)
    assert (out / "a.txt").read_bytes() == b"A"


def test_raw_uses_staged_dir_whole_and_prefix(repo, fake, client, tmp_path, monkeypatch):
    staged = tmp_path / "lustre" / fake.head("my-repo")
    (staged / "sub").mkdir(parents=True)
    (staged / "sub" / "b.txt").write_text("B")
    (staged / ".kaos-ready").write_text("")
    monkeypatch.setenv("KAOS_STAGED_DIR", str(staged))
    assert datasets.materialize(repo, client=client) == staged
    assert datasets.materialize(repo, client=client, prefix="sub") == staged / "sub/"
    assert gets(fake) == []                                               # nothing downloaded
    with pytest.raises(DatasetError, match="no files under missing/"):      # not staged: falls back to a download
        datasets.materialize(repo, client=client, prefix="missing")


def test_raw_empty_prefix_is_a_clear_error(repo, client):
    with pytest.raises(DatasetError, match="holds no files under nothing/"):
        datasets.materialize(repo, client=client, prefix="nothing")


def test_an_empty_repository_raises_empty_dataset_a_dataset_error(fake, client):
    # A new project's dataset-default has only its initial commit. EmptyDataset lets a step tell
    # "no data yet" apart from every other dataset failure; it stays a DatasetError for old callers.
    fake.add_repo("dataset-default", files={})
    with pytest.raises(EmptyDataset, match="holds no files") as err:
        datasets.materialize(datasets.DatasetRef.parse("dataset-default@latest"), client=client)
    assert isinstance(err.value, DatasetError)


def test_raw_refuses_foreign_nonempty_dest(repo, client, tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "x").write_text("keep")
    with pytest.raises(DatasetError, match="not empty"):
        datasets.materialize(repo, tmp_path / "mine", client=client)


def test_raw_skeleton_is_a_readme_validates_nothing_publishes_as_is(fake, client, tmp_path):
    raw = layouts.load("raw")
    assert set(raw.skeleton("dataset-x")) == {"README.md"}
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "anything.bin").write_bytes(b"\x00")
    assert raw.validate(junk).ok
    result = raw.publish(junk, "my-repo", "first", client=client)
    assert result.created and fake.repos["my-repo"]["metadata"] == {"kaos.kind": "dataset", "kaos.template": "raw"}
    assert "anything.bin" in fake.tree("my-repo", result.branch)


def test_pulled_copy_pushes_back_without_its_marker(repo, fake, client, tmp_path):
    """A folder made by pull carries the cache marker; pushing it unchanged has nothing to publish."""
    out = datasets.materialize(repo, tmp_path / "copy", client=client)
    assert (out / ".kaos-dataset.json").is_file()
    with pytest.raises(DatasetError, match="nothing to publish"):
        datasets.publish_tree(out, "my-repo", "unchanged", client=client)
    (out / "new.txt").write_bytes(b"N")
    result = datasets.publish_tree(out, "my-repo", "one more", client=client)
    assert set(fake.tree("my-repo", result.branch)) == set(FILES) | {"new.txt"}


# ---- label-driven layout choice
def labelled(fake, name, template, files):
    fake.add_repo(name, ns=f"gs://b/x/{name}", metadata={"kaos.template": template} if template else {}, files=files)
    return datasets.DatasetRef.parse(f"{name}@latest")


def yolo_files(tmp_path):
    root = write_dataset(tmp_path / "u")
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_label_yolo_selects_the_yolo_layout(fake, client, tmp_path):
    out = datasets.materialize(labelled(fake, "pics", "yolo", yolo_files(tmp_path)), client=client)
    assert out.name == "data.yaml"


def test_no_label_or_unknown_label_selects_raw(fake, client, tmp_path):
    for name, label in (("plain", None), ("odd", "something-else")):
        out = datasets.materialize(labelled(fake, name, label, yolo_files(tmp_path)), client=client)
        assert out.is_dir() and (out / "data.yaml").is_file()


def test_explicit_layout_wins_over_the_label(fake, client, tmp_path):
    ref = labelled(fake, "pics", "yolo", yolo_files(tmp_path))
    out = datasets.materialize(ref, tmp_path / "as-raw", layout="raw", client=client)
    assert out.is_dir() and (out / "data.yaml").is_file()
    with pytest.raises(DatasetError, match="unknown layout 'coco'"):
        datasets.materialize(ref, layout="coco", client=client)


def test_prefix_is_rejected_by_yolo(fake, client, tmp_path):
    ref = labelled(fake, "pics", "yolo", yolo_files(tmp_path))
    with pytest.raises(DatasetError, match="prefix= only works with layouts that download the whole tree"):
        datasets.materialize(ref, client=client, prefix="images")


def test_layout_of(fake, client):
    labelled(fake, "pics", "yolo", {})
    labelled(fake, "plain", None, {})
    labelled(fake, "odd", "something-else", {})
    assert datasets.layout_of("pics", client) == "yolo"
    assert datasets.layout_of("plain", client) == "raw"
    assert datasets.layout_of("odd", client) == "raw"
    assert datasets.layout_of("does-not-exist", client) == "raw"


# ---- create --layout none
def test_create_empty_dataset_only_kind_label_no_commit(fake, client):
    repo = datasets.create_dataset("mine", "none", "my files", client)
    assert repo == "dataset-mine"
    assert fake.repos[repo]["metadata"] == {"kaos.kind": "dataset", "kaos.description": "my files"}
    assert fake.tree(repo, "main") == {} and "commit_log" not in fake.repos[repo]


def test_cli_create_template_none_explains_next_steps(fake, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())
    code = cli.main(["dataset", "create", "mine", "--layout", "none", "--description", "d"])
    out = capsys.readouterr().out
    assert code == 0 and "empty, no layout" in out
    assert "http://lakefs.test/repositories/dataset-mine/objects" in out
    assert "once its first commit lands" in out and "kaosctl dataset push" in out
    assert fake.repos["dataset-mine"]["metadata"]["kaos.kind"] == "dataset"


# ---- CLI on any repository
@pytest.fixture
def use_fake(fake, monkeypatch):
    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())


def test_cli_versions_and_pull_work_on_any_repository(fake, use_fake, capsys):
    fake.add_repo("my-repo", ns="gs://b/x/my-repo", files=FILES)
    fake.tag("my-repo", "v1")
    assert cli.main(["dataset", "versions", "my-repo"]) == 0
    assert "my-repo: v1" in capsys.readouterr().out
    assert cli.main(["dataset", "pull", "my-repo@v1"]) == 0
    assert "Ready:" in capsys.readouterr().out
    assert cli.main(["dataset", "pull", "my-repo@main", "--prefix", "sub"]) == 0
    assert "your files are in" in capsys.readouterr().out


def test_cli_push_without_template_label_validates_nothing(fake, use_fake, capsys, tmp_path):
    fake.add_repo("my-repo", ns="gs://b/x/my-repo")
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hi")
    assert cli.main(["dataset", "push", str(junk), "my-repo", "-m", "files"]) == 0
    assert "/repositories/my-repo/pulls/1" in capsys.readouterr().out


def test_cli_push_with_yolo_label_validates(fake, use_fake, capsys, tmp_path):
    fake.add_repo("pics", ns="gs://b/x/pics", metadata={"kaos.template": "yolo"})
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hi")
    assert cli.main(["dataset", "push", str(junk), "pics", "-m", "files"]) == 2
    assert "data.yaml: no file matches (required)" in capsys.readouterr().err


def test_a_first_push_that_loses_the_create_race_pushes_into_the_winners_repository(fake, client, tmp_path, monkeypatch):
    # Two people push into the same new dataset at once: both see no repository, the other one
    # creates it first, and this create answers 409. The push must carry on into that repository.
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.txt").write_text("A")
    real = client.repository
    seen = []

    def racing(repo):
        if not seen:                        # the check before the other push's create landed
            seen.append(repo)
            fake.add_repo(repo, ns="gs://b/x/winner")
            return None
        return real(repo)

    monkeypatch.setattr(client, "repository", racing)
    result = datasets.publish_tree(src, "dataset-race", "first images", client=client)
    assert result.created is False and result.pull_id
    assert fake.repos["dataset-race"]["ns"] == "gs://b/x/winner", "the winner's repository, not a second one"


def test_a_409_for_a_repository_that_does_not_exist_is_raised(fake, client, monkeypatch):
    from kaos_lib.errors import LakeFSError

    def taken(*a, **kw):
        raise LakeFSError("create repository dataset-x failed: HTTP 409 conflict", 409)

    monkeypatch.setattr(client, "create_repository", taken)
    with pytest.raises(LakeFSError, match="409"):
        datasets.ensure_repository(client, "dataset-x", {})
