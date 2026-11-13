# Clean up

This page is about what a run leaves on the platform and on the HPC (Slurm) site. The data a pipeline makes (run branches and
kept versions of its datasets) is on [What is kept, and for how long](data-retention.md).

**You want** to know what your runs leave behind, what the platform removes for you and when, and what is left.

You do not have to do anything: the cleanup of failed jobs runs by itself every week.

## What grows

| What | Where it is | Why it is kept |
|---|---|---|
| Finished runs and their records | the run page of your project | to look at a run again |
| The pods of a finished run, and with them the logs of its steps | the run page | to read what a step printed |
| Work folders of steps that **failed, were cancelled or stopped as idle** | on the HPC (Slurm) site, in your project's storage | so you can see what the step left |
| Checkpoint copies of steps that are not finished | on the HPC (Slurm) site | so a step can continue where it stopped |
| Job output files | on the HPC (Slurm) site | what the job printed |
| Datasets copied to the site | on the HPC (Slurm) site | the next step reads them without copying again |
| Step images on the site | on the HPC (Slurm) site | the next step starts without a download |

Work folders, checkpoint copies and datasets on the site count against your project's storage there. A step that
**succeeds** removes its own work folder and checkpoint copies when it ends.

## What is removed, and when

| What | When |
|---|---|
| The record of a finished run | 35 days after it ends |
| The pods of a finished run, succeeded or failed, and with them the logs of its steps | 7 days after it ends. Read the log of a step within a week |
| Work folders of failed, cancelled and idle steps; their checkpoint copies; their job output files | kept 14 days so you can look at them, then removed at the next weekly cleanup (**every Sunday at 03:17 UTC**) |
| Checkpoint copies of a step that has been abandoned for 7 days | when the next job of your project starts on the site. On the platform's own machines, copies of a run that never finished are removed after 7 days |
| A step image replaced by a newer build | within the hour. An image nothing has used for 14 days is removed too |
| A dataset copy on the site | when a newer copy needs the room, or when nothing has used it for 14 days (checked when the next job of your project starts). The weekly cleanup does not remove datasets or images |

## What the weekly cleanup never removes

- anything that belongs to a step that is queued or running, or to a run that is not finished (a step that will continue
  from a checkpoint keeps it until the run is over);
- anything that was written to in the last 14 days;
- anything outside your project's own storage on the site;
- datasets, and the images the next step will use.

If the cleanup cannot read the site's queue or your project's runs, it removes nothing and tries again the next week.

## Run a cleanup yourself

You cannot start a cleanup yourself yet. When you need space on the site before Sunday, ask your platform contact: a
cleanup can be run by hand for one app or for the whole project, with a dry run first that lists what would be removed and
how much space it holds.
