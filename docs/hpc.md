# 9. HPC (Slurm)

You have a step that runs on your project's own machines. If your project is connected to an HPC (Slurm) site, the
same step can run there. The code does not change. You choose the place on the run form, one step at a time.

## Pick a Slurm class

The class field of a step, `<step>-class`, lists the Slurm classes next to the platform's own, for every step that may
run on HPC. Pick one for `train` and submit. The other steps stay where they are. If the field has no Slurm class, your
project is not connected to a site, or the allocation of that class is used up: ask your platform contact.

A step does not name a queue or a quality of service. The platform chooses them.

## Set the longest run

Slurm stops a job at its time limit. The limit is the one every step has, wherever it runs: the field `<step>-walltime`
of the run form, whose default is `walltime=` on the step: `"90m"`, `"12h"` or `"720"` (minutes). A step that sets none
gets `4h` ([the limits](contract.md#the-limits)). What a step on HPC may ask for, and why: [A step can be stopped and started again](contract.md#a-step-can-be-stopped-and-started-again)
(the `12h` of the example below is for the platform's own machines; on HPC today a limit above 11 hours 30 minutes needs `resumable=`).
[Long jobs](long-jobs.md#the-time-limit) says what happens when the limit is reached.

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

## When the limit is reached

A step that keeps a checkpoint ([page 8](long-jobs.md)) continues in a new job. It is told to save shortly before the
limit, and `resumable=` on the step sets how long before ([Reference](reference.md#pipelinepy)). A step that does not keep
one ends at its limit.

A step that asks for more time than one run may last is not cut. If it is resumable, it runs as several capped jobs, one
after the other, each from the last checkpoint. If it is not, it is refused before it is sent: make it resumable, or
shorten the limit in the field `<step>-walltime` of the run form (`walltime=` is only its default). `kaosctl lint` reports the default before you push (`L-E01`, `L-E02`).

A step that waits or is refused has a reason in its status:
[Why an HPC (Slurm) step waits or is refused](when-something-goes-wrong.md#why-an-hpc-slurm-step-waits-or-is-refused) lists them.

What a failed step leaves on the site, and what is removed for you: [Clean up](clean-up.md).

Next: [Try it locally](try-it-locally.md).
