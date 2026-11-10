# Progress of a step

The run page shows how far a step is: "epoch 34 of 100". You get it in one of two ways.

## Nothing to do: Ultralytics, PyTorch Lightning, Hugging Face Trainer

When a step that uses one of these runs in a pipeline, kaos-lib reports its progress by itself: epochs for
Ultralytics and Lightning (steps for a Lightning run limited by `max_steps`), steps for the Hugging Face Trainer.
Your code calls nothing. The step only has to import `kaos_lib` (any use of datasets, outputs or MLflow does).

## One line: anything else

```python
from kaos_lib import progress

for epoch in range(epochs):
    train_one_epoch()
    progress.report(epoch + 1, epochs, unit="epoch")
```

It works the same for a data step:

```python
for i, path in enumerate(files, start=1):
    convert(path)
    progress.report(i, len(files), unit="file")
```

- `done` and `total` are numbers. Leave `total` out when you do not know it.
- `unit` is a short word: `epoch`, `step`, `file`, `batch`.
- Call it as often as you like, on every batch if that is simplest: at most one line every 10 seconds is written,
  and the last one (`done == total`) always is.
- It never fails your step. A value that is not a number is reported once in the step's log and dropped.

## What it does

It writes one line to the step's log, which the platform reads, wherever the step runs (a cluster or HPC (Slurm)):

```
KAOS_PROGRESS {"done":34,"t":1731240000,"total":100,"unit":"epoch","v":1}
```

When the step has an active MLflow run, the same values are set as the run's tags `kaos.progress.done`,
`kaos.progress.total` and `kaos.progress.unit`.

## A step that reports nothing

It is still shown honestly: how long it has been running, how long it usually takes, and whether it is active.
Nothing is guessed from the text of your logs.

## Turning it off

Set `KAOS_PROGRESS=0` in the step's environment: nothing is written, by you or by the framework hooks.

`kaos_lib.checkpoint.progress(...)` is a different call: it tells the platform how far a *checkpoint* is, so a
continued run is known to have advanced (see [Long runs](checkpoint.md)).
