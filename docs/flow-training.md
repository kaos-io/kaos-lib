# Data flow: train, checkpoint and resume

**You want** a training step that writes a model, keeps its place, and continues after an interruption (a machine
taken back, a node lost, an HPC (Slurm) job at its time limit).

The step reads the dataset a step before it made, saves its state after every pass, and writes the model at the end. If
it is stopped, the platform starts it again and it continues from the saved state.

```python title="pipeline.py"
--8<-- "examples/first-pipeline/long-job/pipeline.py:24:25"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/first-pipeline/long-job/steps/train/app/entry.py"
```

- `step.input("clean")` is the dataset `prepare` made in this run, at that exact version.
- `checkpoint.load` returns the state of the last attempt, or the default on the first.
- `checkpoint.save` writes the state. `checkpoint.stop_requested()` is true when the platform wants the machine
  back, and `checkpoint.exit_for_restart()` ends the step with exit code 85: "saved, run me again".
- `step.output("model")` is the folder of the model. It is saved when `step.result()` runs, at the end of the attempt
  that finished.

**The run records** a read of `clean`, and a write of type `model` named `model`. A stopped attempt records nothing: only
the attempt that ends with `step.result()` makes the result.

`checkpoint_every="10m"` makes the platform copy the checkpoint folder every ten minutes. `resumable=` and `walltime=`
matter on HPC (Slurm). [Long jobs](long-jobs.md) explains each, and
[Test your steps](test-your-steps.md#a-step-that-stops-and-continues) tests the stop on your laptop.
