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
- `checkpoint_every="10m"` in `pipeline.py` makes the platform copy the folder every ten minutes
  ([Reference](reference.md#pipelinepy)).

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

## The time limit

Every step has a time limit, the longest it may run, on the platform's own machines and on HPC (Slurm) alike. The run
form shows it as the field `<step>-walltime` of every step ("The longest the step may run, as minutes or hours: 90m,
12h. Default from pipeline.py."). Its default is `walltime=` in `pipeline.py`, and `4h` when the step sets none. Write
minutes or hours: `90`, `90m`, `12h`. Time spent waiting for a machine does not count.

A step that reaches its limit is ended. What happens next depends on `resumable=`:

| the step | it reaches its limit, loses its machine, or exits with 85 |
|---|---|
| declares `resumable=` | it is run again and continues from its checkpoint, up to 5 times, on the platform's own machines and on HPC (Slurm) alike. Each run has the whole limit again |
| declares none | it is run again from the start when its machine is lost, at most twice; a step that reaches its limit ends, and the run fails |

So a training that needs 30 hours and has a limit of 12 hours is resumable, saves checkpoints, and runs three times. A
`train` step that sets `walltime=` and is not resumable gets a warning from `kaosctl lint`
([L-W06](lint/L-W06.md)). `resumable=True` also makes the step save 10 minutes before its limit; the field
`<step>-walltime` must then be longer than that lead.

`checkpoint_every=` is the default of the field `<step>-checkpoint-every`: how often the platform copies the checkpoint
folder. `kaos_lib.checkpoint` uses the field's value as the interval of `checkpoint.tick()` when your code sets none.

## When a step ends

What the platform does when a step ends early, with and without a checkpoint, is a table in the
[Reference](reference.md#when-a-step-ends). A continued step waits in the queue again, and its time counts against your
budget. `checkpoint.progress(epoch)` tells the platform how far the step is: a continuation that gets no further than the
copy it started from ends with `NoProgress` instead of repeating the same hours.

Next: [HPC (Slurm)](hpc.md).
