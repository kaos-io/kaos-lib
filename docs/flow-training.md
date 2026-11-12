# Data flow: train, checkpoint and resume

**You want** a training step that writes a model, keeps its place, and continues after an interruption (a machine
taken back, a node lost, an HPC (Slurm) job at its time limit).

The lines of `pipeline.py`: the step reads the dataset a step before it made, and declares the model it writes.

```python title="pipeline.py"
--8<-- "examples/first-pipeline/long-job/pipeline.py:24:25"
```

The step code, with `checkpoint.load`, `checkpoint.save` and the exit with code 85, and the test that stops it on your
laptop, are the tutorial [Long jobs](long-jobs.md). [Test your steps](test-your-steps.md#a-step-that-stops-and-continues)
shows the same test among the others.

**The run records** a read of `clean`, and a write of type `model` named `model`. A stopped attempt records nothing: only
the attempt that ends with `step.result()` makes the result. What a retry does with what it wrote is in
[Datasets, versions and hashes](datasets-versions-hashes.md#when-a-step-is-run-again).
