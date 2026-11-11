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
| ended as idle (a GPU step whose GPU use stays below 5 % and whose log gets no new line for 20 minutes; `idle_timeout="40m"` on the step raises it, `idle_timeout=0` turns it off) | on HPC (Slurm): continues from the newest good checkpoint. On the platform's own machines: ends as failed with the reason `Idle`, and is not repeated | ends: idle |
| an error in your own code (non-zero exit) | ends: failed | ends: failed |

A continued run waits in the queue again and its time counts against your budget. A checkpoint is used only when it
verifies; if the newest does not, the previous one is. `resumable=False` on the step turns continuing off.

The platform copies the folder every 10 minutes by default, and when the machine is being taken away. A slow copy
lengthens the interval, so copying stays near 10 % of the run time. It keeps the two newest copies and deletes them
all when the step succeeds. `checkpoint_every=`, `idle_timeout=` and the HPC time limit are set on the step in
`pipeline.py` ([What you declare](steps.md#what-you-declare)); a CPU step is copied only when it sets
`checkpoint_every=`. The folder is on the step's own disk, so a checkpoint of several GB needs room: raise `disk=`
on the step (for example `disk="30Gi"`).

## What you see in the step's log

| message | meaning |
|---|---|
| `[kaos-checkpoint] continuing from the checkpoint saved at 12:03:11 UTC (3 files)` | this is a repeat; the step picks up from that copy |
| `[kaos-checkpoint] no saved checkpoint for this step: starting from the beginning` | a first run, or nothing had been saved yet |
| `[kaos-checkpoint] saved a checkpoint copy: 3 files, 212.4 MB, 4 s` | a regular copy |
| `[kaos-checkpoint] skipping checkpoint ...: the copy does not match its checksum` | a damaged copy was ignored; the previous one is used |
| `[kaos-checkpoint] could not save a checkpoint copy (...); the step is not affected` | the copy failed; the step carries on and tries again later |
| `[kaos-checkpoint] step finished; its checkpoint copies were removed` | the step succeeded and the copies were cleaned up |

A repeated step shows its attempts one after the other in the run (`train(1)`, `train(2)`). On HPC (Slurm) the
step's status line says why a job was repeated.

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
| the step ends as failed after its machine was reclaimed | it ran out of its two repeats: run it again, or pick an on-demand class for this step |
| copies fail with a disk message | raise `disk=` on the step |
| the step was ended as idle but was working | raise `idle_timeout=` on the step (`idle_timeout=0` turns the rule off) |
| a GPU step on the platform's own machines fails with `KaosIdle: ended by the idle watchdog ...` | the platform saw GPU use below 5 % and no new log line for the idle time and stopped the step, so the GPU stops costing money. It is not repeated: raise `idle_timeout=` if the step was working, and run it again |
| a CPU step is not copied | set `checkpoint_every=` on it (a short CPU step is simply repeated) |
| the hooks did nothing | `KAOS_CHECKPOINT_HOOKS` must not be 0; framework versions the hooks do not know are left alone, with a message in the log |
