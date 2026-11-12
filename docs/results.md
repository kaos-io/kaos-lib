# Results: what a step hands on

A step hands on one result. It holds the values the step chose, the dataset versions it read, and what it wrote.
`step.result()` writes it; you never build it by hand.

```python
step.result(rows=1200, dropped=14)
```

```json
{"version": 1, "status": "ok",
 "values": {"rows": 1200, "dropped": 14},
 "reads":  [{"name": "raw", "repo": "dataset-raw-images", "owner": null, "ref": "latest", "commit": "1111..."}],
 "writes": [{"name": "embeddings", "type": "dataset", "repo": "dataset-embeddings", "commit": "3333..."}]}
```

| part | what it is | who fills it |
| --- | --- | --- |
| `values` | small values for the steps that need this one, and for the run page | you, with `step.result(...)` |
| `reads` | every dataset the step declared in `inputs=`, opened or not, and every dataset of an earlier step that it read: its name in the pipeline, its repository, the version that was asked for and the exact commit | kaos-lib |
| `writes` | every model, artifact and dataset version the step saved, with the commit that holds it | kaos-lib |

## Reading a result in a later step

```python
prev = step.upstream("prepare")
prev.values["rows"]                     # 1200
data = step.input("embeddings")         # the dataset version "prepare" wrote in this run
```

`step.input("<name>")` works for everything a needed step produced: a dataset, a model or an artifact. You do
not pass paths, commits or run names between steps.

A step that did not run has no result. `step.upstream("x")` then raises and names `x`; it never returns an empty
result. Use `step.upstream("x", optional=True)` in a step that can work without it.

## Where the outputs are

| declared as | stored in | under | a later run reads it |
| --- | --- | --- | --- |
| `model("name")` | your app's outputs repository, `outputs-<app>` | `<name>/<experiment>/<run>/` | from that path, or from the MLflow model registry when a step registers it |
| `artifact("name")` | `outputs-<app>` | `<name>/<experiment>/<run>/` | from that path |
| `dataset("name")` | the dataset `dataset-<name>`, a repository of its own | the dataset's root | as an input: a setting such as `clean: dataset-clean@latest` named in `inputs=` |

Each step makes exactly one commit per output per run. [Outputs](outputs.md) describes the outputs repository
and how to browse it. [A dataset a step produces](steps-and-datasets.md#a-dataset-a-step-produces) explains
dataset versions: what a run stores, and when the dataset's `latest` moves.

## Keep values small

A result is limited to 8 KiB. It travels with the run from step to step, so it is for a handful of numbers and
names, not for data.

| you have | do this |
| --- | --- |
| metrics, curves, parameters | log them to MLflow ([MLflow](mlflow.md)) |
| a table, a report, plots | write them into an `artifact(...)` and let the next step read it with `step.input()` |
| a path or a commit of something the step saved | nothing: it is already in `writes` |

## The ledger: what a run read and wrote

The reads and writes of all the steps of a run together are the run's ledger: the exact version of every dataset
the run read and of everything it wrote. The platform starts it when the run starts, with the version it pinned
for every input, and each step's result adds to it. Nothing in it can be changed afterwards.

It is what makes a run repeatable: the same pipeline version with the same ledger reads the same bytes.

On the step's MLflow run the same information is kept automatically:

| where | what |
| --- | --- |
| the artifact `ledger/<step>.json` | that step's reads and writes |
| the tag `kaos_lib.data.<repository>.commit` | the commit(s) of that dataset the step read |
| the tag `kaos_lib.data.<repository>.owner` | the project that shares the dataset, for a [shared dataset](shared-datasets.md) |

To run a command on exactly the data a past run read, see [Data lock](data-lock.md).
