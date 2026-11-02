"""Datasets and code from before yolo got its name keep working, silently: the old id reads as yolo everywhere
it is read (layouts, the 0.3 formats API, repository labels), is never listed, and is never written."""
import pytest

from conftest import write_dataset
from kaos_lib import cli, datasets, layouts
from kaos_lib.formats import format_names, get_format

LEGACY = "ultralytics"


def test_the_legacy_id_resolves_to_yolo():
    assert layouts.load(LEGACY) is layouts.load("yolo")
    fmt = get_format(LEGACY)
    assert fmt.name == "yolo" and fmt.creator.layout is layouts.load("yolo")
    assert LEGACY not in format_names() and LEGACY not in [lay.name for lay in layouts.available()]


@pytest.fixture
def legacy_repo(fake, tmp_path):
    root = write_dataset(tmp_path / "src")
    files = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    fake.add_repo("dataset-old", metadata={"kaos.kind": "dataset", "kaos.template": LEGACY}, files=files)
    return datasets.DatasetRef.parse("dataset-old@latest")


def test_a_legacy_label_reads_validates_and_lists_as_yolo(fake, client, legacy_repo, tmp_path, capsys, monkeypatch):
    assert datasets.layout_of("dataset-old", client) == "yolo"
    assert datasets.materialize(legacy_repo, tmp_path / "out", client=client).name == "data.yaml"
    assert get_format(LEGACY).consumer.materialize(legacy_repo, tmp_path / "out2", client).name == "data.yaml"
    assert next(r for r in datasets.list_datasets(client) if r.repo == "dataset-old").template == "yolo"

    monkeypatch.setattr(cli, "_connect", lambda args: fake.client())
    bad = write_dataset(tmp_path / "bad", bad_label="7 0.5 0.5 0.1 0.1")
    assert cli.main(["dataset", "push", str(bad), "dataset-old", "-m", "x"]) == 2     # validated as yolo
    assert "class id 7 is outside" in capsys.readouterr().err
    assert cli.main(["dataset", "validate", str(bad), "--format", LEGACY]) == 2
    assert "WARNING" not in capsys.readouterr().err                                 # silently
    assert fake.repos["dataset-old"]["metadata"]["kaos.template"] == LEGACY          # never relabelled


def test_new_datasets_are_labelled_yolo(fake, client):
    datasets.create_dataset("fresh", LEGACY, "", client, classes=["a"])
    assert fake.repos["dataset-fresh"]["metadata"]["kaos.template"] == "yolo"


def test_the_0_3_formats_api_keeps_its_signatures(fake, client, dataset_dir, tmp_path):
    fmt = get_format("yolo")
    assert "data.yaml" in fmt.creator.skeleton(["cat"], "pets")
    assert fmt.creator.validate(dataset_dir).ok
    assert fmt.creator.publish(dataset_dir, "dataset-default", "m", client=client).pull_id
    fake.add_repo("plain", files={"a.txt": b"A"})
    out = datasets.materialize(datasets.DatasetRef.parse("plain@main"), tmp_path / "r", fmt_name="raw", client=client)
    assert out.is_dir()
