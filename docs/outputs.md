# Outputs

Each ML app writes its results to its own lakeFS repository `outputs-<app>`, on `main`, **one commit per step per
run**, under `<kind>/<experiment>/<run>/` (`kind` is `checkpoints` by default). In a pipeline step the repository name is in
`$CHECKPOINT_BUCKET` and the run id in `$KUBECORE_RUN_ID`.

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

## Long runs on HPC (Slurm): saved before the time limit

A job on HPC (Slurm) has a time limit. About 10 minutes before it, the platform tells the step to stop. While a run
writer is open, kaos-lib then:

1. uploads again everything the step passed to `save`, with what the files hold now;
2. uploads the paths named in `autosave`, even if the step never saved them;
3. commits on the run's branch and ends the step with exit code 85.

The platform sees 85 and continues the run in a new job under the same run name. The new job is often on another
machine, so its disk is empty. When its run writer opens, every `autosave` **file** the run holds is put back where it
was. Code that already loads its checkpoint "if the file exists" resumes with no change:

```python
CKPT = "state.pt"
with outputs.run(app, experiment, run, autosave=CKPT) as r:   # a continued run gets state.pt back here
    state = torch.load(CKPT) if os.path.exists(CKPT) else fresh_state()
    for epoch in range(state.epoch, epochs):
        train_one_epoch(state)
        torch.save(state, CKPT)                                # saved again before the time limit
    r.save(CKPT)
```

- A file that is already on the local disk is never replaced.
- Folders are not put back: their files are saved without the folder's name. Use `r.latest("folder/")`.
- If the file cannot be downloaded, opening the run writer fails, so a run never quietly starts over.
- Two `autosave` files need different names: each is saved under its name.

When saving at the stop signal:

- A path that is missing or empty is skipped; the others are still saved.
- Steps that do not open a run writer are not stopped early; they run to the time limit as before.
- PyTorch Lightning: pass `plugins=[SLURMEnvironment(auto_requeue=False)]` to the `Trainer`. Lightning's own handler
  for this signal tries to requeue the job, which HPC sites usually refuse.
- A continued run waits in the queue again and its time counts against your budget.

