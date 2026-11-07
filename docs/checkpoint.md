# Long runs on HPC (Slurm): checkpoints that survive interruptions

A job on HPC (Slurm) can be interrupted: it reaches its wall time, the node fails, the site does maintenance, or the
job is pre-empted. A step that saves its progress continues in a new job from the last good checkpoint instead of
starting over. You decide what a checkpoint contains; the platform keeps it safe and brings it back.

## 1. The checkpoint folder (no library needed)

Every step gets a folder in the environment variable `KAOS_CHECKPOINT_DIR`. The platform saves a copy of it every
few minutes and shortly before the wall time, and puts the newest verified copy back into that folder when the step
continues. Point your framework at it:

```python
import os
ckpt = os.environ.get("KAOS_CHECKPOINT_DIR", "runs/checkpoints")     # your own default elsewhere

# Ultralytics: YOLO(...).train(project=ckpt, name="run", exist_ok=True, resume=os.path.exists(f"{ckpt}/run/weights/last.pt"))
# PyTorch Lightning: ModelCheckpoint(dirpath=ckpt); trainer.fit(model, ckpt_path="last")
# Hugging Face: TrainingArguments(output_dir=ckpt); trainer.train(resume_from_checkpoint=True)
# Plain PyTorch: torch.save(state, f"{ckpt}/last.pt") and torch.load it at start if it exists
```

On a continued step the folder already holds the earlier files, so code that resumes "if the file exists" works
unchanged. A step that writes nothing there is simply re-run from the start if the node fails (up to twice).

## 2. Or register save and load

If you want a progress value, a checked checkpoint, or a framework-free save, tell the library how to save and
load:

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
| a continued step starts from scratch | load from the folder when files exist; or use `register(load=...)` |
| `NoProgress` | the step restarted without loading, or saved the same state: check that `load` restores your counters |
| the checkpoint is large and saving is slow | `checkpoint_every=30`, or save less (weights only, skip the optimiser) |
