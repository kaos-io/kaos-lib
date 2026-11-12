# 9. HPC (Slurm)

You have a step that runs on your project's own machines. If your project is connected to an HPC (Slurm) site, the
same step can run there. The code does not change. You choose the place on the run form, one step at a time.

## Pick a Slurm class

The class field of a step, `<step>-class`, lists the Slurm classes next to the platform's own, for every kind of step
that may run on HPC. Pick one for `train` and submit. The other steps stay where they are. If the field has no Slurm
class, your project is not connected to a site, or the allocation of that class is used up: ask your platform contact.

A step does not name a queue or a quality of service. The platform chooses them.

## Set the longest run

Slurm stops a job at its time limit. `walltime=` on the step sets the limit as text: `"90m"`, `"12h"` or `"720"`
(minutes).

```python title="pipeline.py" hl_lines="24"
--8<-- "examples/first-pipeline/hpc/pipeline.py"
```

`walltime` has an effect only when the step runs on a Slurm class. A step of kind `ingest`, `publish` or `control` never
runs there, and `walltime=` on one is refused.

## What differs from the platform's machines

| | the platform's machines | HPC (Slurm) |
|---|---|---|
| steps | every step | every step except `ingest`, `publish` and `control` kinds, and a step that produces a dataset |
| inputs | downloaded once for each version | copied beside the job before it starts; `step.input()` returns the copy |
| waiting | the step starts at once | the job waits in the Slurm queue first, for minutes or hours |
| time limit | none from `walltime=` | `walltime=` |
| outputs, result, MLflow | the same calls | the same calls |

A step that produces a dataset runs on the platform's own machines for now, so `prepare` stays where it is. `train`
reads `clean` from the copy that the platform puts beside the job. The step code never names a place.

## When the limit is reached

A step that keeps a checkpoint ([page 8](long-jobs.md)) continues in a new job. It is told to save before the limit:
`resumable="30m"` on the step sets how long before, and `resumable=True` uses ten minutes. A step that does not keep one
ends at its limit.

A step that asks for more time than the longest run the site allows is not cut:

- If it can continue, it runs as several capped jobs, one after the other, each from the last checkpoint. The platform
  allows up to five continuations.
- If it cannot continue, it is refused before it is sent, with the reason `TooLongNotResumable`. Make it resumable, or
  shorten `walltime=`. `kaosctl lint` reports this before you push (`L-E01`, `L-E02`).

## Why a step waits or is refused

The status of a step says why. These are the reasons you can meet:

| reason | meaning | what to do |
|---|---|---|
| `WaitingForBudget` | the project's allocation covers the step once running steps end | wait |
| `ConcurrencyLimit` | the project runs as many Slurm jobs as it may | wait |
| `BudgetBlocked` | the step needs more node-hours than the project's share has left this month | shorten it, or ask your platform contact |
| `SiteLimit` | the site's monthly limit for the account is used up | ask your platform contact |
| `SubmitLimit` | the site allows only so many queued and running jobs, and the project has that many. The step fails | run it again when jobs have ended |
| `TooLongNotResumable`, `TooLongBeyondContinuations` | the time limit is longer than the site allows | make it resumable, or shorten it |
| `GPUViolation` | the step used a GPU that was not its own, on a node several steps share | use only the GPU the step is given |

Several steps of one project on one class may share a node: each gets its own GPU and its share of the CPUs and the
memory. Compute only on the GPU the step is given.

Next: [Try it locally](try-it-locally.md).
