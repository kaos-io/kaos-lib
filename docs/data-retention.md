# What is kept, and for how long

Some things a run leaves are removed by themselves, on a schedule. Everything else stays until you remove it. This page
lists both. The numbers are the defaults; each project can set its own.

## Removed by itself

| what | removed when | what goes |
|---|---|---|
| a run branch: the working branch of a dataset you make, left by a step that was stopped | nothing has been written to it for 7 days | the branch and the files staged on it. A branch of a run still writing is never removed |
| the kept name of a version nobody promoted (the name `k-<time>-<run>-<step>-<id>` of [a sealed version](data-writes.md#one-sealed-version-for-each-run)) | the version is older than 30 days, counted from the time in its name, and `latest` never held it | the name only. The checks run every hour |

Both apply to the datasets a step produces only. They do not touch an uploaded dataset, a model or an artifact. The 7 and
30 days are the defaults; each project can set its own.

## Finished runs and their logs

This is what the platform does today. It is not a promise: [the contract](contract.md#what-is-not-promised-today) does not
make one, so copy what you need into an artifact or a dataset.

| what | removed when |
|---|---|
| the record of a finished run, succeeded or failed | 35 days after it ends. A project can set another number of days. A pipeline with a step that can run on HPC (Slurm) is kept at least 32 days, so the month's HPC spend stays counted |
| the logs of its steps | 7 days after the run ends. Read the log of a step within a week |

The files and checkpoint copies a run leaves on the HPC (Slurm) site are on [Clean up](clean-up.md).

## Never removed

- A version that was promoted (a run moved `latest` to it), and a version that carries a name of its own (`v1`, a name
  someone gave).
- The files of a dataset you uploaded.
- Models and artifacts of earlier runs: each run keeps its folder in `outputs-<app>`.

## What "removed" means for a version

When the kept name of a version goes, the version is no longer listed by that name. The platform removes only the name:
it does not delete the files. The files are freed by a separate clean-up that the project owner turns on. Do not rely on
reading a version by its id after its name has gone. To keep one, promote it with `promote-<name>`, or give it a name of
your own.

Next: [Clean up](clean-up.md), or back to [Your contract with the platform](contract.md).
