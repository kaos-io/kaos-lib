"""The step-contract fixtures (kaos-hpc-operator, ``docs/step-contract/fixtures``): pinned bytes, and the ledger and
wire form that must reproduce them. Re-copy them with ``tests/contract_fixtures/sync.py`` when the contract moves."""
import hashlib
import json
import os
import pathlib

import pytest

from kaos_lib import lock

HERE = pathlib.Path(__file__).with_name("contract_fixtures")
NAMES = sorted(p.stem for p in HERE.glob("*.wire"))


def load(name):
    return json.loads((HERE / f"{name}.json").read_text())


def test_the_copied_bytes_match_sha256sums():
    want = dict(reversed(line.split("  ", 1)) for line in (HERE / "SHA256SUMS").read_text().splitlines())
    got = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
           for p in HERE.iterdir() if p.suffix in (".json", ".wire")}
    assert got == want, "a fixture was edited here or not re-copied whole: run tests/contract_fixtures/sync.py"


def test_the_copy_equals_the_contract_checkout_when_one_is_named():
    """``$KAOS_STEP_CONTRACT_DIR`` names ``docs/step-contract/fixtures`` of a kaos-hpc-operator checkout."""
    source = os.environ.get("KAOS_STEP_CONTRACT_DIR")
    if not source:
        pytest.skip("set $KAOS_STEP_CONTRACT_DIR to compare with a checkout of the contract")
    theirs = {p.name: p.read_bytes() for p in pathlib.Path(source).iterdir() if p.suffix in (".json", ".wire")}
    ours = {p.name: p.read_bytes() for p in HERE.iterdir() if p.suffix in (".json", ".wire")}
    drift = sorted(n for n in set(theirs) | set(ours) if theirs.get(n) != ours.get(n))
    assert not drift, f"the contract moved: {drift}. Run tests/contract_fixtures/sync.py"


@pytest.mark.parametrize("name", NAMES)
def test_wire_reproduces_every_wire_file_byte_for_byte(name):
    text = (HERE / f"{name}.wire").read_text()
    assert lock.wire(json.loads(text)) == text
    assert lock.wire(load(name)) == text
    assert "{{" not in text and text.isascii() and not text.endswith("\n")


def test_wire_refuses_what_json_cannot_hold():
    for bad in (float("nan"), {1: "x"}, object(), {"a": {2, 3}}):
        with pytest.raises((TypeError, ValueError)):
            lock.wire(bad)


@pytest.mark.parametrize("name", ["ledger-two-reads", "ledger-run-union"])
def test_a_ledger_parses_and_writes_back_unchanged(name):
    assert lock.DataLock.parse(load(name)).to_dict() == load(name)


@pytest.mark.parametrize("name", ["result-ok", "result-model"])
def test_the_reads_and_writes_of_a_result_are_ledger_entries(name):
    result = load(name)
    ledger = lock.DataLock.parse({"version": 2, "reads": result["reads"], "writes": result["writes"]})
    assert [r.as_dict() for r in ledger.reads] == result["reads"]
    assert [w.as_dict() for w in ledger.writes] == result["writes"]


def test_line_is_kept_and_never_invented():
    entry = {"name": "clean", "repo": "dataset-raw", "owner": None, "ref": "v1", "commit": "c1", "line": "clean"}
    ledger = lock.DataLock.parse({"version": 2, "reads": [entry], "writes": []})
    assert ledger.to_dict()["reads"] == [entry]
    assert "line" not in lock.Read("dataset-raw", "v1", "c1").as_dict()
