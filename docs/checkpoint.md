# Long runs on HPC (Slurm): checkpoints that survive interruptions

A job on HPC (Slurm) can be interrupted: it reaches its wall time, the node fails, the site does maintenance, or the
job is pre-empted. A step that saves its progress continues in a new job from the last good checkpoint instead of
starting over. You decide what a checkpoint contains; the platform keeps it safe and brings it back.

## 1. It works without code

Every step gets a checkpoint folder in the environment variable `KAOS_CHECKPOINT_DIR`. The platform saves a copy of
it every few minutes and when the step is asked to stop, and puts the newest verified copy back when the step
continues. When `kaos_lib` is imported in a step that has this folder, it hooks the training framework you use,
with nothing to call:

| framework | what is saved | on a continued step |
|---|---|---|
| Ultralytics (YOLO) | `last.pt` at the end of an epoch | resumes with the same total epochs, in the same MLflow run |
| PyTorch Lightning | a full Lightning checkpoint | `fit` continues from it (`ckpt_path`) |
| Hugging Face `Trainer` | the Trainer's `checkpoint-*` | `train` resumes from it (`resume_from_checkpoint`) |
| anything else, plain PyTorch | see section 2 | see section 2 |

- The hooks attach only to a framework your step already imported. `kaos_lib` never imports one and depends on none.
- Saving happens every few minutes (about 10 % of the run time at most; 5 to 60 minutes), and right away at the next
  safe point (end of an epoch or a batch) when the step is told to stop: a pre-empted or reclaimed node, a drain, or
  the wall time of an HPC job. The step then ends with exit code 85 so it is continued rather than counted as done.
- A run you already told to resume (`resume=...`, `ckpt_path=...`, `resume_from_checkpoint=...`) is left alone.
- Turn the hooks off with the environment variable `KAOS_CHECKPOINT_HOOKS=0`. Your own framework checkpoints in the
  folder keep working: you can also point your framework at `KAOS_CHECKPOINT_DIR` yourself and resume "if the file
  exists", and the platform will keep it safe the same way.

On your own machine `KAOS_CHECKPOINT_DIR` is not set and none of this happens.

## 2. Your own state: register save and load

For plain PyTorch, or anything the hooks do not cover, tell the library how to save and load:

```python
from kaos_lib import checkpoint

model = build_model()
checkpoint.register(save=lambda path: save_state(model, path),    # writes into `path`, returns the progress
                    load=lambda path: load_state(model, path))
for epoch in range(first_epoch, epochs):
    train_one_epoch(model)
    checkpoint.tick()                                             # a safe point: end of a batch or an epoch
```

- `save(path)` writes everything needed to continue into the empty folder `path` and returns the progress it
  reached: an int (`epoch`) or a dict (`{"epoch": 3, "step": 1200}`, most significant counter first).
- `load(path)` restores from such a folder. `register` calls it for you when the step continues, and returns the
  progress that was loaded (`None` on a first run).
- `tick()` writes a checkpoint every N minutes. N follows the measured save time so saving stays near 10 % of the run
  time (between 5 and 60 minutes). `checkpoint_every=20` sets minutes yourself; `checkpoint_every=False` turns
  periodic saving off. When the platform asks the step to stop before the wall time, the next `tick()` saves and
  ends the step so it continues.
- Every checkpoint is written to a temporary folder and moved into place when complete, with a manifest of file
  checksums. On load, a checkpoint whose files do not match is skipped and the previous one is used. The last two
  are kept.

A step that registers its own functions is not also hooked automatically.
`checkpoint(save=..., load=...)` is the same call as `checkpoint.register(...)`. The earlier calls
`stop_requested()`, `save(save_fn)`, `is_resume()` and `resume_path()` keep working.

## When the platform continues a step

| the job ended with | a step with a checkpoint | a step without one |
|---|---|---|
| wall time reached | continues from the newest checkpoint | ends: "wall time reached" |
| node failure, maintenance, pre-emption | continues from the newest checkpoint | re-runs from the start, at most twice |
| killed as idle (no GPU work, no log output) | continues from the newest checkpoint | ends: idle |
| an error in your own code (non-zero exit) | ends: failed | ends: failed |

A continued run waits in the queue again and its time counts against your budget. A continuation that does not get
past the previous checkpoint's progress (the progress you return, or any change in the folder) ends with the reason
`NoProgress` instead of repeating the same hours.

On your project's own machines there is no platform folder and nothing to resume from: `register` and `tick()` write
into `output/checkpoint` and the same code runs everywhere.

## If it isn't there

| symptom | fix |
|---|---|
| a continued step starts from scratch | your code resumes only if you pass the folder to the framework: use the automatic hooks, or `register(load=...)` |
| the hooks did nothing | the step must import the framework before or after `kaos_lib`, and `KAOS_CHECKPOINT_HOOKS` must not be 0; unknown framework versions are left alone with a message in the log |
| `NoProgress` | the step restarted without loading, or saved the same state: check that `load` restores your counters |
| the checkpoint is large and saving is slow | `checkpoint_every=30`, or save less (weights only, skip the optimiser) |
