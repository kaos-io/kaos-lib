# Long runs: checkpoints that survive interruptions

A step can be interrupted: a spot or preemptible node is reclaimed, a node fails or is drained, or an HPC (Slurm) job
reaches its wall time. A step that keeps its progress in the **checkpoint folder** continues from it instead of
starting over. The platform saves the folder every few minutes, checks it, and puts the newest good copy back when the
step continues. You decide what goes in it. The same code works on the platform's own nodes and on HPC.

A step that writes nothing there is simply run again from the start after a node failure or pre-emption (up to twice).
Outputs are published only when a run succeeds, so a re-run never leaves half a result.

## 1. Point your framework at the folder

`checkpoint.dir()` is the folder (the platform sets `KAOS_CHECKPOINT_DIR`; on your own machine it is a fresh
temporary folder). Give it to any framework's own checkpoint or output directory:

```python
from kaos_lib import checkpoint
YOLO("yolo11n.pt").train(data="data.yaml", project=str(checkpoint.dir()), name="run", exist_ok=True)   # Ultralytics
trainer = pl.Trainer(callbacks=[ModelCheckpoint(dirpath=checkpoint.dir(), save_last=True)])             # Lightning
args = TrainingArguments(output_dir=str(checkpoint.dir()), save_steps=500)                              # Hugging Face
```

On a continued step the folder already holds the earlier files, so code that resumes "if the file exists" (Keras,
orbax, your own) works unchanged.

## 2. Save and load your own state

For a custom loop, three lines each way. `save` writes bytes, JSON-able data (dict, list, numbers, text) or any
picklable object atomically; `load` returns it, or the default on a first run:

```python
state = checkpoint.load("state", default={"epoch": 0})              # first run: the default; a continued step: where it stopped
for epoch in range(state["epoch"], epochs):
    train_one_epoch(); checkpoint.save({"epoch": epoch + 1})        # a different name keeps separate state: save(x, name="model")
```

`load` unpickles what `save` pickled: only use it on your own folder.

`checkpoint.progress(n)` is optional: it tells the platform how far you are (an int, or a dict such as
`{"epoch": 3, "step": 1200}`, most significant counter first). A continuation that gets no further than the checkpoint
it started from ends with the reason `NoProgress` instead of repeating the same hours. Without it, any change in the
folder counts as progress.

## 3. Stop cleanly

`checkpoint.stop_requested()` becomes true on SIGTERM or SIGUSR1: a reclaimed or drained node, or the wall time of an
HPC job. Check it at a safe point (the end of a batch or an epoch), save, and end the step so it is continued:

```python
if checkpoint.stop_requested():
    checkpoint.save({"epoch": epoch + 1}); checkpoint.exit_for_restart()    # exit code 85: "saved, continue me"
```

Nothing changes for a step that never calls `stop_requested()`: SIGTERM ends it as before.

## 4. Or let the library hook your framework

When `kaos_lib` is imported in a step that has the checkpoint folder, it attaches to the framework you use, with no code
from you. It only touches a framework your step already imported, and `kaos_lib` depends on none of them.

| framework | saved into the folder | on a continued step |
|---|---|---|
| Ultralytics (YOLO) | `last.pt` at the end of an epoch, and `best.pt` once one exists | resumes with the same total epochs, in the same MLflow run; `best.pt` is put back in the run directory (a new job starts with an empty one) |
| PyTorch Lightning | a full Lightning checkpoint | `fit` continues from it (`ckpt_path`) |
| Hugging Face `Trainer` | the Trainer's `checkpoint-*` | `train` resumes from it (`resume_from_checkpoint`) |

Saving happens every few minutes (about 10 % of the run time at most, between 5 and 60 minutes) and at the next safe
point after a stop request, when the step then ends with exit code 85. A run you already told to resume
(`resume=...`, `ckpt_path=...`, `resume_from_checkpoint=...`) is left alone. Turn the hooks off with the environment
variable `KAOS_CHECKPOINT_HOOKS=0`.

A continued step logs into the MLflow run it continues. MLflow does not let a run's parameter change, and a continuation
changes some (the model path now points at the checkpoint, the data file is this attempt's copy). Where a framework's
MLflow logging (Ultralytics, Lightning `MLFlowLogger`, Hugging Face `MLflowCallback`) meets that, the parameter is
logged as `resume.<name>` (for example `resume.model`) and the first attempt's value stays under `<name>`; new
parameters are logged as usual. Metrics keep the framework's own step numbers, which continue from the checkpoint.

## What the platform does when a step ends

| the run ended with | a step that kept a checkpoint | a step that did not |
|---|---|---|
| node failure, maintenance, pre-emption, reclaimed spot node | continues from the newest good checkpoint | re-runs from the start, at most twice |
| wall time reached (HPC) | continues from the newest good checkpoint | ends: "wall time reached" (a step that asked for longer than the class allows is refused before it starts, see below) |
| ended as idle (no GPU work and no log output for 20 minutes; `idle_timeout="40m"` on a GPU step raises it, `idle_timeout=0` turns it off) | continues from the newest good checkpoint | ends: idle |
| an error in your own code (non-zero exit) | ends: failed | ends: failed |

A continued run waits in the queue again and its time counts against your budget. A checkpoint is used only when it
verifies; if the newest does not, the previous one is. `resumable=False` on the step turns continuing off.

## Declare it in the pipeline, or let the platform learn it

On HPC (Slurm) a step can say how it wants to be stopped: `resumable="3m"` on the step (a lead time such as `"3m"` or
`"1h"`) asks for the stop signal that long before the time limit, so a large checkpoint has time to be written.
`resumable=True` takes the default lead (10 minutes). Only GPU steps can declare it. You do not have to declare it: once a continuation of the step has loaded
its checkpoint and made progress, the platform treats that step as resumable from then on and keeps it that way.
The pipeline templates ([hera](https://novelcore.github.io/hera-pipeline-template/),
[yolo](https://novelcore.github.io/yolo-pipelines-template/)) show the declaration in context.

A step that asks for more time than the longest run the HPC class allows is handled before it is submitted:

| the step | what happens |
|---|---|
| resumable, and fits in the allowed number of continuations | runs as capped attempts, each at most the class's longest run, one after the other, each continuing from the last checkpoint |
| resumable, but needs more attempts than allowed | refused, with the longest time it can ask for |
| not resumable | refused (`TooLongNotResumable`) rather than cut at the limit: make it resumable (write into `checkpoint.dir()`) or shorten it |

You never name a queue or a QoS: the time limit and the lane a step runs in are chosen by the platform.

## If it isn't there

| symptom | fix |
|---|---|
| a continued step starts from scratch | your code must read the folder: point the framework at `checkpoint.dir()`, or use `load` |
| `NoProgress` | the step restarted without loading, or saved the same state: check that you load what you saved |
| saving is slow or the checkpoint is large | save less (weights only), or save less often |
| the hooks did nothing | `KAOS_CHECKPOINT_HOOKS` must not be 0; framework versions the hooks do not know are left alone, with a message in the log |
