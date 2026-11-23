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
- The platform copies the folder at an interval the library chooses ([Nothing to set](#nothing-to-set)).

## Test the stop on your machine

The test asks the step to stop after the second epoch, checks that it ended with 85, and runs it again. Save it as
`step_tests/test_train.py` in your app. Install pytest once, in the Python environment where you installed kaos-lib:
`pip install pytest`.

```python title="step_tests/test_train.py"
--8<-- "examples/first-pipeline/long-job/step_tests/test_train.py"
```

```bash
python -m pytest step_tests/test_train.py
```

The test passes when the step stopped with 85 and finished after it was run again.

## A framework with its own checkpoints

Give the framework the folder: `checkpoint.dir()` is the platform's checkpoint folder (a new temporary folder on your
machine).

```python title="Ultralytics, PyTorch Lightning, Hugging Face"
--8<-- "examples/frameworks/checkpoint_folder.py"
```

Importing `kaos_lib` in a step that uses Ultralytics, PyTorch Lightning or Hugging Face attaches to them: they save
into the folder, and a continued step resumes from it, with no code from you. A run you told to resume yourself
(`resume=`, `ckpt_path=`, `resume_from_checkpoint=`) is left alone. [Reference](reference.md#run-tools) says how to turn
the hooks off.

## Nothing to set

You set no time limit and no checkpoint interval, in `pipeline.py` or anywhere else. The platform chooses the time
of a step, and finds out by itself whether the step saves progress: a step that does is continued after it was
cut, a step that does not is run again from the start. `kaosctl lint` refuses `walltime=`, `resumable=` and
`checkpoint_every=` on a step ([L-E06](lint/L-E06.md)).

How often progress is saved is chosen by the library: about every 15 minutes, adapting to the time a save takes,
never more often than every 5 minutes or less often than every hour. A step whose own code wants another interval
passes it where it registers its state: `checkpoint.register(save=..., load=..., every=...)`.

## Four ways to save progress

```python
from kaos_lib import checkpoint

# 1. Point any framework at the folder; the platform keeps it and gives it back when the step continues.
YOLO("yolo11n.pt").train(project=str(checkpoint.dir()), name="run", exist_ok=True)

# 2. Save and load your own state.
state = checkpoint.load("state", default={"epoch": 0})
for epoch in range(state["epoch"], epochs):
    train_one_epoch(); checkpoint.save({"epoch": epoch + 1})

# 3. Stop cleanly when the platform asks.
if checkpoint.stop_requested():
    checkpoint.save({"epoch": epoch + 1}); checkpoint.exit_for_restart()

# 4. Ultralytics, PyTorch Lightning and Hugging Face are attached automatically: no code.
```

## How a step can end

| ending | what you read |
|---|---|
| done | the step finished |
| one job, no saved progress | "Ended: it ran <limit> on HPC (Slurm) without saving progress. A step that saves progress through the library is continued instead." |
| a continuation saved nothing new | "Ended: the last job saved nothing new, so it did not get past <its checkpoint>." |
| the cap reached | "Ended: it reached the platform's cap of 7 days." |
| the budget used up | "Ended: the project's HPC budget is used up." |

The step's own error is shown as it is. A machine lost under a step is replaced and the step is run again from its
last saved state; with nothing saved it starts again from the start, at most twice.

`checkpoint.progress(epoch)` tells the platform how far the step is: a continuation that gets no further than the
copy it started from ends instead of repeating the same hours. A continued step waits in the queue again, and its
time counts against your budget.

Next: [HPC (Slurm)](hpc.md).
