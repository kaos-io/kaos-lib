# 9. HPC (Slurm)

You have a step that runs on your project's own machines. If your project is connected to an HPC (Slurm) site, the
same step can run there. The code does not change. You choose the place on the run form, one step at a time.

## Pick a Slurm class

The class field of a step, `<step>-class`, lists the Slurm classes next to the platform's own, for every step that may
run on HPC. Pick one for `train` and submit. The other steps stay where they are. If the field has no Slurm class, your
project is not connected to a site, or the allocation of that class is used up: ask your platform contact.

A step does not name a queue or a quality of service. The platform chooses them.

## The time of a step

You set no time limit. The platform chooses the time of a job on the site, and a step that saves progress
([page 8](long-jobs.md)) is continued when a job ends. [Long jobs](long-jobs.md#how-a-step-can-end) says how a step can end.

```python title="pipeline.py" hl_lines="24"
--8<-- "examples/first-pipeline/hpc/pipeline.py"
```

## What differs on HPC (Slurm)

A step that produces a dataset runs on the platform's own machines, so `prepare` stays where it is. Every other step
except the step types `ingest`, `publish` and `control` may run on HPC. `train` reads `clean` from a copy that the platform
puts beside the job before it starts, and `step.input()` returns that copy. What is copied, when, and what the next run reuses: [a dataset a step made, read on HPC (Slurm)](data-reads.md#a-dataset-a-step-made-read-on-hpc-slurm). The job waits in the Slurm queue first, for
minutes or hours. Outputs, result and MLflow use the same calls as anywhere. The step code never names a place.

Several steps of one project on one class may share a node: each gets its own GPU and its share of the CPUs and the
memory. Compute only on the GPU the step is given. [GPUs on HPC (Slurm)](gpus-on-hpc.md) shows how a step
reads what it got.

## When a job ends

A step that keeps a checkpoint ([page 8](long-jobs.md)) continues in a new job, from the last saved state. A step that
does not keep one ends after one job, and the status says so.

A step that waits or is refused has a reason in its status:
[Why an HPC (Slurm) step waits or is refused](when-something-goes-wrong.md#why-an-hpc-slurm-step-waits-or-is-refused) lists them.

What a failed step leaves on the site, and what is removed for you: [Clean up](clean-up.md).

Next: [Try it locally](try-it-locally.md).
