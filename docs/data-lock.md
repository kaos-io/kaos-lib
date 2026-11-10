# Data lock

Every `datasets.resolve` (and so every `materialize`) records `(owner, repository, ref) -> commit` in the
process's lock. Add reads that bypass kaos-lib (an S3-gateway stream) with `lock.record`.

**In a pipeline step you call nothing:** when the step's MLflow run ends (`mlflow.end_run()`, leaving
`with mlflow.start_run()`, or a framework's own MLflow logging ending its run), kaos-lib writes the lock to that
run. A run that fails gets it too. A tracking problem at that moment is reported in the step's log and never
fails the step.

On a laptop, or to write it earlier or to another run, do it yourself:

```python
from kaos_lib import lock
lock.record("dataset-default", "v2", commit)        # owner="team-a" for a shared dataset
lock.write()                                        # the active run, $MLFLOW_RUN_ID, or write(run_id)
locked = lock.load(run_id)                          # DataLock; .reads, .to_json(), .pinned(repo, ref, owner)
lock.DataLock.replay(locked)                        # later resolves of those repositories return the locked commits
```

`write` sets the tags `kaos_lib.data.<repo>.commit` (comma-separated when a run read several commits of one
repository) and `kaos_lib.data.<repo>.owner` for a shared dataset, and logs `data.lock.json`:

```json
{"version": 1, "reads": [{"repo": "dataset-default", "owner": null, "ref": "v2", "commit": "c0042..."},
                         {"repo": "dataset-cats", "owner": "team-a", "ref": "v1", "commit": "a1b2..."}]}
```

It merges with a `data.lock.json` already on the run, so several steps logging to one run add up. Replay matches
a resolve on (owner, repository, ref), then on (owner, repository) when the lock holds one commit for it; a commit
the caller pins (`ref.with_commit`, `commit=`) is used as given.

Replay a run's reads from the command line:

```
kaosctl run --lock <mlflow-run-id> -- python -m app.entry --params "$(cat params.yaml)"
```

(`--params` takes the YAML text itself, not a file name, as on the platform.) It loads the lock (MLflow auth from the chain above), prints the pinned reads and runs the command with
`$KAOS_LIB_LOCK` set to the lock's JSON, which kaos-lib honours in the child exactly like `DataLock.replay`. A
malformed `$KAOS_LIB_LOCK` is a one-line `LockError` naming what is wrong. Running a pipeline step by name
(`kaosctl run <step>`) is not part of this release.
