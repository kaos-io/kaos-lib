"""Layouts as a mechanism: sources (built-in, installed, project, local), a team's own layout end to end, hooks, CLI."""
import json
import re
import sys
import textwrap

import pytest
import yaml

from kaos_lib import cli, datasets, layouts
from kaos_lib.errors import DatasetError
from kaos_lib.layouts import local, spec

SAMPLES = """\
layout: 1
name: samples
title: Samples
description: one JSON per sample and a classes list
version: "3"
parameters:
  - {key: classes, label: Classes, type: list, required: true, form_key: classes}
  - {key: owner, label: Owner, type: text}
form_file: meta.yaml
skeleton:
  folders: [data]
  files:
    meta.yaml: |
      owner: {{owner|quote}}
      classes:
      {{#each classes}}
        - {{@item|quote}}
      {{/each}}
rules:
  required: [meta.yaml, "data/*.json"]
  allowed: [meta.yaml, README.md, "data/*.json"]
  manifests:
    - file: meta.yaml
      schema: {type: object, required: [classes], properties: {classes: {type: array, minItems: 1}}}
materialize:
  include: [meta.yaml, "data/**"]
"""


@pytest.fixture
def samples_dir(tmp_path):
    folder = tmp_path / "samples-layout"
    folder.mkdir()
    (folder / "layout.yaml").write_text(SAMPLES)
    return folder


def write_samples(root, n=2):
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "meta.yaml").write_text("owner: me\nclasses: [a, b]\n")
    for i in range(n):
        (root / "data" / f"{i}.json").write_text("{}")
    return root


class EP:
    """An importlib.metadata entry point stand-in."""
    def __init__(self, name, obj):
        self.name, self.value, self._obj = name, f"pkg:{name}", obj

    def load(self):
        if isinstance(self._obj, Exception):
            raise self._obj
        return self._obj


@pytest.fixture
def entry_points(monkeypatch):
    eps: list = []
    monkeypatch.setattr(layouts, "_entry_points", lambda: eps)
    return eps


def project_entry(text, source="project"):
    return {"name": "x", "source": source, "spec": spec.parse(text)}


# ------------------------------------------------------------------ sources
def test_builtin_layouts():
    assert [lay.name for lay in layouts.available()] == ["raw", "yolo"]
    assert layouts.load("yolo").source == "builtin" and layouts.load("yolo").spec["hook"] == "kaos_lib.layouts.yolo"


def test_a_path_is_read_as_a_local_layout(samples_dir):
    for given in (str(samples_dir), str(samples_dir / "layout.yaml")):
        lay = layouts.load(given)
        assert (lay.name, lay.source, lay.version) == ("samples", "local", "3")
    with pytest.raises(DatasetError, match="no layout at ./nowhere"):
        layouts.load("./nowhere")


def test_a_name_is_never_read_from_a_folder_of_that_name(tmp_path, samples_dir, monkeypatch, client):
    monkeypatch.chdir(samples_dir.parent)
    with pytest.raises(DatasetError, match="unknown layout 'samples-layout'"):
        layouts.load("samples-layout", client)
    assert layouts.load("./samples-layout").name == "samples"


@pytest.mark.parametrize("kind", ["path", "folder", "module", "dict", "layout"])
def test_installed_layouts_from_entry_points(entry_points, samples_dir, kind):
    import types
    module = types.ModuleType("teamlayouts")
    module.__file__ = str(samples_dir / "__init__.py")
    obj = {"path": str(samples_dir / "layout.yaml"), "folder": samples_dir, "module": module,
           "dict": yaml.safe_load(SAMPLES), "layout": layouts.load(str(samples_dir))}[kind]
    entry_points.append(EP("samples", obj))
    lay = layouts.load("samples")
    assert lay.name == "samples" and lay.source == "installed"


def test_a_broken_installed_layout_is_skipped_with_a_warning(entry_points, samples_dir, capsys):
    entry_points += [EP("bad", ImportError("no module teamx")), EP("ok", samples_dir)]
    assert [lay.name for lay in layouts.available()] == ["raw", "yolo", "samples"]
    assert "skipping layout entry point bad" in capsys.readouterr().err


def test_project_layouts_come_from_kaos_lake(fake, client):
    fake.templates = [project_entry(SAMPLES), {"name": "yolo", "source": "builtin", "spec": {"junk": 1}},
                      {"name": "old-style", "title": "no spec"}]
    lay = layouts.load("samples", client)
    assert lay.source == "project" and "lakefs.test" in lay.origin
    assert [x.name for x in layouts.available(client)] == ["raw", "yolo", "samples"]


def test_a_project_layout_that_is_not_valid_is_skipped(fake, client, capsys):
    fake.templates = [{"source": "project", "spec": {"layout": 1, "name": "Bad", "title": "x"}}]
    assert layouts.project(client) == []
    assert "skipping project layout Bad" in capsys.readouterr().err


def test_precedence_builtin_then_installed_then_project(fake, client, entry_points, samples_dir, capsys):
    fake.templates = [project_entry(SAMPLES), project_entry(SAMPLES.replace("name: samples", "name: yolo"))]
    entry_points.append(EP("samples", samples_dir))
    assert layouts.load("samples", client).source == "installed"
    assert layouts.load("yolo", client).source == "builtin"
    names = [(x.name, x.source) for x in layouts.available(client)]
    assert names == [("raw", "builtin"), ("yolo", "builtin"), ("samples", "installed")]
    err = capsys.readouterr().err
    assert "project layout samples" in err and "shadowed" in err


def test_project_lookup_only_when_needed(fake, client):
    layouts.load("yolo", client)
    assert not any(p == "/kaos/v1/dataset-templates" for _, p in fake.calls)


def test_unknown_layout_without_a_connection_says_so(monkeypatch):
    with pytest.raises(DatasetError, match="not signed in: the project's layouts were not looked up"):
        layouts.load("samples")


# ------------------------------------------------------------------ a team's own layout, end to end
def test_own_layout_create_validate_push_pull(fake, client, samples_dir, tmp_path):
    fake.templates = [project_entry(SAMPLES)]
    repo = datasets.create_dataset("pets", "samples", "pet samples", client,
                                   {"classes": ["cat", " dog"], "owner": "lab"})
    assert fake.repos[repo]["metadata"]["kaos.template"] == "samples"
    tree = fake.tree(repo, "main")
    assert set(tree) == {"meta.yaml", "data/.keep"}
    assert tree["meta.yaml"] == b'owner: "lab"\nclasses:\n  - "cat"\n  - "dog"\n'
    lay = layouts.load("samples", client)
    assert lay.parse(tree["meta.yaml"].decode()) == {"classes": ["cat", "dog"]}

    work = tmp_path / "work"
    assert lay.validate(work).errors == [f"{work} is not a directory"]
    work.mkdir()
    (work / "stray.txt").write_text("x")
    assert lay.validate(work).errors == ["meta.yaml: no file matches (required)",
                                         "data/*.json: no file matches (required)",
                                         "stray.txt: not part of this layout"]
    (work / "stray.txt").unlink()
    write_samples(work)
    assert lay.validate(work).ok
    result = lay.publish(work, repo, "two samples", client=client)
    r = fake.repos[repo]
    r["branches"]["main"]["commit"] = r["branches"][result.branch]["commit"]     # the pull request is merged
    r["branches"]["main"]["staged"] = {}
    commit = fake.head(repo)
    r["commits"][commit]["notes/skip.txt"] = b"not downloaded"

    out = datasets.materialize(datasets.DatasetRef.parse(f"{repo}@latest"), client=client)   # by the label
    assert out.is_dir() and (out / "data/1.json").is_file() and not (out / "notes").exists()
    marker = json.loads(local.marker_file(out).read_text())
    assert marker["include"] == ["meta.yaml", "data/**"]
    n = len(fake.calls)
    assert datasets.materialize(datasets.DatasetRef.parse(f"{repo}@latest"), client=client) == out
    assert not any(p.endswith("/objects") for _, p in fake.calls[n:])            # cached


def test_a_copy_pulled_with_another_layout_is_fetched_again(fake, client, tmp_path):
    fake.add_repo("dataset-mixed", files={"data.yaml": b"x", "images/a.jpg": b"a", "other/z": b"z"})
    ref = datasets.DatasetRef.parse("dataset-mixed@latest")
    dest = tmp_path / "copy"
    datasets.materialize(ref, dest, layout="raw", client=client)
    assert (dest / "other/z").is_file()
    custom = layouts.Layout(spec.parse(SAMPLES.replace('"data/**"]\n', '"images/**"]\n')))
    datasets.materialize(ref, dest, layout=custom, client=client)
    assert (dest / "images/a.jpg").is_file() and not (dest / "other").exists()


# ------------------------------------------------------------------ hooks
HOOK = textwrap.dedent('''
    def validate(root, layout):
        return [f"hook saw {layout.name}"]

    def materialize(data_dir, out_dir, layout):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "entry.txt").write_text(str(data_dir))
        return out_dir / "entry.txt"
''')


@pytest.fixture
def hooked(tmp_path, monkeypatch, samples_dir):
    (tmp_path / "pkgs").mkdir()
    (tmp_path / "pkgs" / "team_hook.py").write_text(HOOK)
    monkeypatch.syspath_prepend(str(tmp_path / "pkgs"))
    yield SAMPLES + "hook: team_hook\n"
    sys.modules.pop("team_hook", None)


def test_hook_validate_adds_problems_after_the_rules(tmp_path, hooked):
    lay = layouts.Layout(spec.parse(hooked), "local")
    root = write_samples(tmp_path / "d")
    assert lay.check(root) == [] and lay.validate(root).errors == ["hook saw samples"]


def test_hook_materialize_gives_the_entry(fake, client, tmp_path, hooked):
    fake.add_repo("dataset-h", files={"meta.yaml": b"classes: [a]\n", "data/1.json": b"{}"})
    lay = layouts.Layout(spec.parse(hooked), "local")
    entry = lay.materialize(datasets.DatasetRef.parse("dataset-h@latest"), tmp_path / "h", client)
    assert entry == tmp_path / "h" / "entry.txt" and entry.read_text() == str(tmp_path / "h")


def test_a_hook_that_does_not_import(tmp_path):
    lay = layouts.Layout(spec.parse(SAMPLES + "hook: no_such_module_xyz\n"), "local")
    with pytest.raises(DatasetError, match="cannot load its hook no_such_module_xyz"):
        lay.validate(write_samples(tmp_path / "d"))
    project = layouts.Layout(lay.spec, "project")
    assert project.validate(write_samples(tmp_path / "e")).ok      # warned, the declarative rules still ran


def test_yolo_is_a_layout_like_any_other(dataset_dir):
    yolo = layouts.load("yolo")
    assert yolo.check(dataset_dir) == [] and yolo.validate(dataset_dir).ok
    (dataset_dir / "labels/train/a.txt").write_text("1 0.5 0.5 0.2 1.5\n")
    assert yolo.check(dataset_dir) == []                               # the declarative line rule passes it
    assert yolo.validate(dataset_dir).errors == [
        "labels/train/a.txt:1: coordinates must be within [0,1]: 1 0.5 0.5 0.2 1.5"]   # the hook does not


# ------------------------------------------------------------------ CLI
@pytest.fixture
def use_fake(fake, monkeypatch):
    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_layout_list_and_show(capsys, use_fake, fake):
    fake.templates = [project_entry(SAMPLES)]
    code, out, _ = run(capsys, "layout", "list")
    assert code == 0 and "(hook)" in out
    rows = [ln.split()[:2] for ln in out.splitlines()[:3]]
    assert rows == [["raw", "builtin"], ["yolo", "builtin"], ["samples", "project"]]
    code, out, _ = run(capsys, "layout", "show", "yolo")
    assert code == 0 and out.startswith("# yolo: builtin")
    assert yaml.safe_load(out)["rules"]["required"] == ["data.yaml", "images/**"]


def test_cli_layout_list_without_a_connection_lists_the_local_ones(capsys):
    code, out, err = run(capsys, "layout", "list")
    assert code == 0 and "raw" in out and "not looked up" in err


def test_cli_layout_init_starter_and_copy(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capsys, "layout", "init", "my-layout")
    assert code == 0 and "--layout ./my-layout" in out
    lay = layouts.load("./my-layout")
    assert lay.name == "my-layout" and lay.parameters[0]["key"] == "classes"
    files = lay.skeleton("dataset-x", values={"classes": ["a", "b"]})
    assert files["classes.txt"] == b"a\nb\n"
    code, _, err = run(capsys, "layout", "init", "my-layout")
    assert code == 1 and "already exists" in err
    code, _, _ = run(capsys, "layout", "init", "copy", "--from", "yolo", "--name", "my-yolo")
    copy = layouts.load("./copy")
    assert copy.name == "my-yolo" and copy.spec["rules"] == layouts.load("yolo").spec["rules"]


def test_cli_layout_validate(capsys, dataset_dir, tmp_path, samples_dir):
    code, out, _ = run(capsys, "layout", "validate", str(dataset_dir), "--layout", "yolo")
    assert code == 0 and "valid yolo dataset" in out and "kaos_lib.layouts.yolo" in out
    code, _, err = run(capsys, "layout", "validate", str(dataset_dir), "--layout", str(samples_dir))
    assert code == 2 and "problem(s) for layout samples" in err and "data.yaml: not part of this layout" in err


def test_cli_create_with_params_and_a_local_layout(capsys, use_fake, fake, samples_dir):
    code, out, _ = run(capsys, "dataset", "create", "pets", "--layout", str(samples_dir),
                       "--param", "classes=cat, dog", "--param", "owner=lab")
    assert code == 0 and "layout samples" in out
    assert fake.tree("dataset-pets", "main")["meta.yaml"].startswith(b'owner: "lab"')
    code, _, err = run(capsys, "dataset", "create", "cats", "--layout", str(samples_dir), "--param", "colour=red")
    assert code == 1 and "has no parameter 'colour' (its parameters: classes, owner)" in err


def test_cli_push_validates_with_the_project_layout_of_the_label(capsys, use_fake, fake, tmp_path):
    fake.templates = [project_entry(SAMPLES)]
    fake.add_repo("dataset-pets", metadata={"kaos.kind": "dataset", "kaos.template": "samples"})
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "x.csv").write_text("1")
    code, _, err = run(capsys, "dataset", "push", str(bad), "dataset-pets", "-m", "m")
    assert code == 2 and "x.csv: not part of this layout" in err
    code, out, _ = run(capsys, "dataset", "push", str(write_samples(tmp_path / "ok")), "dataset-pets", "-m", "m")
    assert code == 0 and "/pulls/1" in out


def test_cli_layout_publish_opens_a_pull_request(capsys, use_fake, fake, samples_dir):
    code, out, _ = run(capsys, "layout", "publish", str(samples_dir))
    assert code == 0 and "http://lakefs.test/repositories/layouts/pulls/1" in out
    r = fake.repos["layouts"]
    assert re.fullmatch(r"gs://bucket/lakefs/layouts-[0-9a-f]{8}", r["ns"])
    branch = r["pulls"][0]["source_branch"]
    assert fake.tree("layouts", branch) == {"samples/layout.yaml": SAMPLES.encode()}
    assert fake.tree("layouts", "main") == {}
    r["branches"]["main"]["commit"] = r["branches"][branch]["commit"]
    code, out, _ = run(capsys, "layout", "publish", str(samples_dir / "layout.yaml"))
    assert code == 0 and "nothing to publish" in out


def test_cli_layout_publish_refuses_builtin_names_and_invalid_specs(capsys, use_fake, tmp_path):
    (tmp_path / "y.yaml").write_text(SAMPLES.replace("name: samples", "name: yolo"))
    code, _, err = run(capsys, "layout", "publish", str(tmp_path / "y.yaml"))
    assert code == 1 and "yolo is a built-in layout" in err
    (tmp_path / "bad.yaml").write_text("layout: 1\nname: x y\n")
    code, _, err = run(capsys, "layout", "publish", str(tmp_path / "bad.yaml"))
    assert code == 1 and "is not a valid layout" in err and "title is required" in err


def test_the_guide_layout_is_valid_and_works(tmp_path):
    import pathlib
    text = (pathlib.Path(__file__).parents[1] / "docs" / "examples" / "layout" / "layout.yaml").read_text()
    lay = layouts.Layout(spec.parse(text, "the guide"))
    files = lay.skeleton("dataset-birds", "Garden", {"classes": ["robin", "wren"]})
    assert files["classes.yaml"] == b'classes:\n  - "robin"\n  - "wren"\n' and b"2 classes" in files["README.md"]
    root = tmp_path / "birds"
    for p, content in files.items():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_bytes(content)
    for split in ("train", "val"):
        (root / "clips" / split / "a.wav").write_bytes(b"RIFF")
        (root / "labels" / split / "a.json").write_text("{}")
    assert lay.validate(root).ok
    (root / "clips/train/b.mp3").write_bytes(b"x")
    assert lay.validate(root).errors == ["clips/train/b.mp3: extension .mp3 is not allowed here (.wav)",
                                         "clips/train/b.mp3 has no labels/train/b.json"]
