# Outputs

Each ML app writes its results to its own lakeFS repository `outputs-<app>`, on `main`, **one commit per step per
run**, under `<kind>/<experiment>/<run>/` (`kind` is `checkpoints` by default). In a pipeline step the platform
injects the repository as `$CHECKPOINT_BUCKET` and the run as `$KUBECORE_RUN_ID`.

```python
from kaos_lib import outputs

with outputs.run("myapp", "exp1", "run-7", "checkpoints") as r:   # "myapp" or "outputs-myapp"
    resume = r.latest("weights/")    # local path of what the run's branch already holds, or None
    r.save("./ckpt")                 # upload and commit on the run's branch (durable)
    commit = r.finish({"dataset_ref": "dataset-default@v2", "mlflow_run_id": "..."})   # merge into main

outputs.write_run("myapp", "exp1", "run-7", "./ckpt")   # shortcut: open, save once, finish
```

How a run stays safe:

- Every save lands on the run's own branch `run-<run>-<kind>`, created from `main` or **reused** when it exists. So
  simultaneous runs never mix, and a retry or a preempted pod resumes where it stopped (`latest`).
- `finish` merges the branch into `main` (exactly one new commit) and deletes it. It returns the merge commit id.
- An exception inside the `with` block neither merges nor deletes the branch, so the retry resumes. Leaving the block
  normally without `finish` finishes with no extra metadata.
- An empty commit or an empty merge is a success and returns the existing commit.

Writing needs write rights on `outputs-<app>` only: the app's own key has them, other apps' keys do not.
