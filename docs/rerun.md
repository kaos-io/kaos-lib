# Re-running

## What a re-run does today

Run the pipeline again and you start a new run. **Every step runs again, from the first.** There is no way to start in
the middle.

What stays the same and what changes:

| | in the new run |
|---|---|
| the settings | the run form's values at that time. Change them, or keep them |
| a dataset you read | the version named in the settings. `latest` is the version it points to when the run starts. A named version (`@v3`) is the same data every time |
| a dataset the pipeline makes | a new version for the files that changed. A step that writes the same files as before makes no new version, and uploads only the files that differ |
| a model or an artifact | a new folder for the new run, `<name>/<experiment>/<run>/`. Earlier runs keep theirs |
| `latest` of a dataset the pipeline makes | moves only if the run asks, and only if every step went well ([Move `latest`](flow-datasets.md#move-latest)) |

So a failed run costs you its time, and nothing else. It changes no `latest` and it overwrites no earlier result.

## A step that was cut short is not a re-run

A step that loses its machine or reaches its time limit is run again by the platform, inside the same run. A step that
saves checkpoints continues from the last one ([Long jobs](long-jobs.md)). You do nothing.

## Read the same data again

To make two runs comparable, pin the version of every dataset they read:

```yaml title="config/dataset.yaml"
--8<-- "examples/flows/rerun/config/dataset.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/rerun/config/config.yaml"
```

The run records the exact version each step read ([What a run reads](data-reads.md#what-a-run-records)).

## What is not available

**Starting from a step in the middle** is not available yet. If step 5 of 7 fails after 20 hours, the next run starts at
step 1. To lose less, make the long step resumable ([Long jobs](long-jobs.md)), and split a pipeline so that a step you
may want to skip writes a dataset of its own: the next run reads it, with a version pinned, instead of making it again.

**Reusing the result of an earlier run** (a cache that skips a step when nothing changed) is not available yet either.

Next: [When something goes wrong](when-something-goes-wrong.md).
