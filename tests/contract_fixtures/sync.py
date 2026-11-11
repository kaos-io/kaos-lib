#!/usr/bin/env python3
"""Copy the step-contract fixtures from kaos-hpc-operator and pin their bytes.

    python tests/contract_fixtures/sync.py <kaos-hpc-operator git folder> [<ref>]     # default ref: HEAD

Writes every fixture, ``SHA256SUMS`` and ``SOURCE`` (the commit they came from). The fixtures are never edited
here: ``tests/test_contract_fixtures.py`` fails when a file and the list differ, and, with
``$KAOS_STEP_CONTRACT_DIR`` naming a checkout of the fixtures folder, when that checkout and this copy differ.
"""
import hashlib
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
FOLDER = "docs/step-contract/fixtures"


def git(repo, *args) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout


def main(argv) -> int:
    if len(argv) not in (2, 3):
        sys.stderr.write(__doc__)
        return 2
    repo, ref = argv[1], argv[2] if len(argv) == 3 else "HEAD"
    commit = git(repo, "rev-parse", ref).decode().strip()
    names = sorted(n for n in git(repo, "ls-tree", "--name-only", f"{commit}:{FOLDER}").decode().split()
                   if n.endswith((".json", ".wire")))
    for old in list(HERE.glob("*.json")) + list(HERE.glob("*.wire")):
        old.unlink()
    sums = []
    for name in names:
        data = git(repo, "show", f"{commit}:{FOLDER}/{name}")
        (HERE / name).write_bytes(data)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (HERE / "SHA256SUMS").write_text("".join(sums))
    (HERE / "SOURCE").write_text(f"kaos-io/kaos-hpc-operator {FOLDER} at {commit}\n")
    print(f"{len(names)} fixtures from {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
