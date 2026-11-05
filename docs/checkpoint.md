# Long runs on HPC (Slurm): save and continue

A job on HPC (Slurm) has a wall time. A step that needs longer can save its progress before the wall time and
continue in a new job from what it saved. You write the saving and loading; KAOS sends the signal, uploads the
checkpoint and starts the next job.

## 1. Declare the step resumable

In `pipeline.py`:

```python
train = step("model-training", gpu=True, hpc_time_limit="12h", resumable=True)
```

The stop signal arrives 10 minutes before the wall time. If saving and uploading your checkpoint takes longer, ask
for it earlier: `resumable="20m"`.

## 2. Save at a safe point, resume from the checkpoint

```python
from kaos_lib import checkpoint

state = load_state(checkpoint.resume_path()) if checkpoint.is_resume() else fresh_state()
for epoch in range(state.epoch, epochs):
    train_one_epoch(state)
    if checkpoint.stop_requested():                       # the end of an epoch or a batch
        checkpoint.save(lambda path: save_state(state, path))
```

- `stop_requested()` turns true when the stop signal arrives. Check it where your state is consistent, at the end
  of an epoch or a batch.
- `save(save_fn)` calls `save_fn` with an empty folder. Write everything you need to resume into it. It then
  becomes `checkpoint/` in the step's output folder in one step, and the step ends so it can continue.
- `is_resume()` and `resume_path()` tell a continued step where its checkpoint is.

`save_state` and `load_state` are yours: save whatever your framework needs (weights, optimiser, epoch, random
state).

## What happens

1. The stop signal arrives (10 minutes, or your lead time, before the wall time).
2. At your next check, `save` writes the checkpoint and ends the step.
3. The checkpoint is uploaded with the step's outputs, before the job ends.
4. The step continues in a new job; `is_resume()` is true there. A continued run waits in the queue again, and its
   time counts against your budget.

On your project's own machines there is no stop signal and nothing to resume from: `stop_requested()` and
`is_resume()` stay false, so the same code runs everywhere.

## If it isn't there

| symptom | fix |
|---|---|
| the step ends at its wall time without saving | declare it `resumable=`, and check `stop_requested()` often enough to save before the wall time |
| the checkpoint does not finish uploading | ask for an earlier signal: `resumable="20m"` |
| a continued step starts from scratch | load from `checkpoint.resume_path()` when `checkpoint.is_resume()` is true |
