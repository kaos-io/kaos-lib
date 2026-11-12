# 8. Long jobs

A long step can be cut short. A machine is taken back, a node fails, or a Slurm job reaches its time limit. A step that
keeps its progress in a checkpoint folder continues from it. A step that does not starts again from the beginning.

You add a `train` step that makes several passes over `clean`, and keeps its place:

```python title="pipeline.py" hl_lines="16 24 25"
--8<-- "examples/first-pipeline/long-job/pipeline.py"
```

```yaml title="config/train.yaml (new)"
--8<-- "examples/first-pipeline/long-job/config/train.yaml"
```

```yaml title="config/config.yaml" hl_lines="11"
--8<-- "examples/first-pipeline/long-job/config/config.yaml"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/first-pipeline/long-job/steps/train/app/entry.py"
```

- `checkpoint.load("state", default=...)` returns what the last attempt saved, or the default on the first run.
- `checkpoint.save(state)` writes it into the checkpoint folder, atomically. Save at a point where a restart is safe.
- `checkpoint.stop_requested()` is true when the platform wants the machine back. `checkpoint.exit_for_restart()` ends
  the step with exit code 85: "saved, run me again". The platform starts it again, with the folder as you left it.
- `checkpoint_every="10m"` in `pipeline.py` makes the platform copy the folder every ten minutes. A GPU step is copied
  without it, every ten minutes by default. `checkpoint_every=False` turns copying off.

## Test the stop on your machine

The test asks the step to stop after the second epoch, checks that it ended with 85, and runs it again:

```python title="step_tests/test_train.py"
--8<-- "examples/first-pipeline/long-job/step_tests/test_train.py"
```

```bash
python -m pytest step_tests/test_train.py
```

```text
step_tests/test_train.py .                                               [100%]

============================== 1 passed in 0.08s ===============================
```

## A framework with its own checkpoints

Give the framework the folder: `checkpoint.dir()` is the platform's checkpoint folder (a new temporary folder on your
machine).

```python title="Ultralytics, PyTorch Lightning, Hugging Face"
--8<-- "examples/frameworks/checkpoint_folder.py"
```

Importing `kaos_lib` in a step that uses Ultralytics, PyTorch Lightning or Hugging Face attaches to them: they save
into the folder, and a continued step resumes from it, with no code from you. A run you told to resume yourself
(`resume=`, `ckpt_path=`, `resume_from_checkpoint=`) is left alone. `KAOS_CHECKPOINT_HOOKS=0` turns the hooks off.

## What the platform does when a step ends

| the step ended because | with a checkpoint | without one |
|---|---|---|
| its machine was lost (reclaimed, failed, drained) | continues from the newest good copy | runs again from the start, at most twice |
| the time limit of a Slurm job was reached ([page 9](hpc.md)) | continues in a new job | ends |
| a GPU step showed no GPU use and no new log line for 20 minutes | ends as idle, and is not run again | ends as idle |
| your code failed (non-zero exit) | ends as failed | ends as failed |

A continued step waits in the queue again, and its time counts against your budget. A copy is used only after the
platform verified it. `checkpoint.progress(epoch)` tells the platform how far the step is: a continuation that gets no
further than the copy it started from ends with `NoProgress` instead of repeating the same hours.

Next: [HPC (Slurm)](hpc.md).
