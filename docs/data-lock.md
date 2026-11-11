# Data lock: run on exactly the data a past run read

Every dataset version a step reads is recorded with its exact commit, and so is everything it writes. Together
they are the run's ledger ([Results](results.md#the-ledger-what-a-run-read-and-wrote)). The data lock is the use
of that record to read the same data again.

**In a pipeline step you call nothing.** `step.input()` reads what the run pinned, `step.result()` records what
was read and written, and kaos-lib puts the same record on the step's MLflow run as `ledger/<step>.json`. A
tracking problem at that moment is reported in the step's log and never fails the step.

## Replay a run's reads

```
kaosctl run --lock <mlflow-run-id> -- python my_evaluation.py
```

It loads the record of that MLflow run, prints the pinned reads and runs the command with `$KAOS_LIB_LOCK` set.
Inside the command every `datasets.resolve` and `datasets.materialize` of a recorded dataset returns the recorded
commit, whatever the dataset's newest version is by now. A dataset the record does not hold is read as usual.

It works for runs made with kaos-lib 0.4 too: their record is the single artifact `data.lock.json`, which is
still read and never written.

## In Python

```python
from kaos_lib import lock

locked = lock.load(run_id)                  # the reads and writes of an MLflow run
locked.reads, locked.writes                 # lists; .pinned(repo, ref, owner) gives one commit
lock.DataLock.replay(locked)                # later resolves of those datasets return the recorded commits
lock.record("dataset-default", "v2", commit)   # add a read that did not go through kaos-lib (owner="team-a" if shared)
```

Replay matches a read on (owner, repository, version asked for), then on (owner, repository) when the record
holds one commit for it. A commit the caller pins (`ref.with_commit`, `commit=`) is used as given.

The record's form:

```json
{"version": 2,
 "reads":  [{"name": "dataset", "repo": "dataset-default", "owner": null, "ref": "v2", "commit": "c0042..."}],
 "writes": [{"name": "model", "type": "model", "repo": "outputs-myapp", "commit": "a1b2..."}]}
```

A malformed `$KAOS_LIB_LOCK` is a one-line `LockError` naming what is wrong.
