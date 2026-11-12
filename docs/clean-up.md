# Clean up

**You want** to know what your runs leave behind, what the platform removes for you and when, and how to free the rest.

## What grows

| What | Where it is | Why it is kept |
|---|---|---|
| Finished runs and their records | the run page of your project | to look at a run again |
| Work folders of steps that **failed, were cancelled or stopped as idle** | on the HPC (Slurm) site, in your project's storage | so you can see what the step left |
| Checkpoint copies of steps that are not finished | on the HPC (Slurm) site | so a step can continue where it stopped |
| Job output files | on the HPC (Slurm) site | what the job printed |
| Datasets copied to the site | on the HPC (Slurm) site | the next step reads them without copying again |
| Step images on the site | on the HPC (Slurm) site | the next step starts without a download |
| Branches of runs and versions nobody promoted | your datasets | they expire by themselves ([Datasets](datasets-versions-hashes.md)) |

Work folders, checkpoint copies and job output count against your project's storage on the site. A step that **succeeds**
removes its own work folder and checkpoint copies when it ends.

## What is removed for you

| What | When |
|---|---|
| Finished runs and their job records | 30 days after they end |
| Step images nothing uses | within minutes of the last job that needed them, and after 14 days without use |
| A dataset copy on the site | when a newer copy needs the room; the newest copy of each dataset stays |
| Checkpoint copies of a step abandoned for 7 days | when the next job of your project starts |

Work folders of failed steps, job output files and the rest are removed only when someone runs a cleanup.

## Run a cleanup

A cleanup is a small form:

| Field | Meaning | Default |
|---|---|---|
| `what` | `work-folders`, `checkpoints`, `dataset-cache`, `images`, `failed-jobs` (work folders, checkpoints and job output files), or `all` | `work-folders` |
| `older-than` | only what nothing has used for this many days (1 to 3650) | `14` |
| `app` | only the finished runs of this app; empty means the whole project | empty |
| `dry-run` | `true` only lists what would be removed, with sizes, and removes nothing | `true` |

Run it once with `dry-run` on and read the answer: how many items would go, how many bytes they hold, and what was kept
and why. Then run it again with `dry-run` off. The answer of a real run says how much was freed. Ask your platform
contact to start it for your project until the console offers the form on your project's HPC page.

A cleanup never removes:

- anything that belongs to a step that is queued or running, or to a run that is not finished (a step that will
  continue from a checkpoint keeps it until the run is over);
- anything that was written to in the last `older-than` days;
- the newest copy of each dataset, a dataset copy a job is using or that is pinned;
- anything outside your project's own storage on the site.

With an `app` chosen, datasets and images are left alone: they belong to no single app.

## Turn on the weekly cleanup

Your project has a weekly cleanup that ships **switched off**. It runs `failed-jobs` with `older-than` 14 and `dry-run`
off, on Sundays at 03:17 UTC. To switch it on, or to change the day, the time or the fields, ask your platform contact.
Do the dry run by hand first.

## If a cleanup does not run

| The answer says | What to do |
|---|---|
| the site could not be read safely | nothing was removed; try again in a few minutes |
| the site did not accept the cleanup | nothing was removed; tell your platform contact |
| `No finished run of the app ... is known` | the app has no finished run on record; clean the whole project instead |
