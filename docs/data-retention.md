# What is kept, and for how long

Some things a run leaves are removed by themselves, on a schedule. Everything else stays until you remove it. This page
lists both. The numbers are the defaults; the first two are set for each project.

## Removed by itself

| what | removed when | what goes |
|---|---|---|
| a working branch of a dataset you make, left by a step that was stopped | nothing has been written to it for 7 days | the branch and the files staged on it. A branch of a run still writing is never removed |
| the kept name of a version nobody promoted (the name `k-<time>-<run>-<step>-<id>` of [a sealed version](data-writes.md#one-sealed-version-for-each-run)) | the version is older than 30 days, counted from the time in its name, and `latest` never held it | the name only. The checks run every hour |
| checkpoint copies on HPC (Slurm) | the step ended well; or 7 days after the last use, for a step that was abandoned | the copies. A step that failed keeps them, so that a new run can continue |
| checkpoint copies on the platform's own machines | older than 7 days, for a run that never finished | the copies |
| a copy of a dataset the platform put beside an HPC (Slurm) job | 14 days without use | the copy. The next job that needs it makes it again |

The first two rows apply to the datasets a step produces only. They do not touch an uploaded dataset, a model or an artifact.

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

## Not set by the contract

How long a finished run and the logs of its steps are kept is not part of the contract today: do not use them as an archive.
Put what you need to keep in an artifact, a model or a dataset.

Next: [Your contract with the platform](contract.md).
