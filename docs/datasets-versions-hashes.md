# Datasets, versions and hashes

What a dataset is, what a version is, what the long hex string is, when `latest` moves, and how a run records what it
read and wrote. Read [Principles](principles.md) first.

## What a dataset is

A dataset is a named set of files in your project: `dataset-<name>`. There are two kinds.

| | uploaded | produced |
|---|---|---|
| name | `dataset-<name>` | `dataset-<app>-<name>`, from `dataset("<name>")` in the app `<app>` |
| made by | you, with `kaosctl dataset push`; it changes only through a merged pull request | one step of one pipeline, when it calls `step.result()` |
| versions | `v1`, `v2`, ... that you make with `kaosctl dataset release`; and `latest` | one for each run that changes its files; and `latest` |
| who writes | people of the project | only the app that declares it |

In code you use the short name: `dataset("clean")`, `step.output("clean")`, `step.input("clean")`.

## What a version is

A version is a snapshot of all the files of a dataset at one moment. It never changes after it is made. It has up to
three names:

- **the version id**, a long hex string of 64 characters, for example
  `37592accd6a211f20307af0db7fceebf98c50367442b65eb1391ac0e6d6d3e96`. It is the exact name: one id is one set of files.
  Logs show the first 12 characters, `37592accd6a2`.
- **`vN`**, a label such as `v2`, on an uploaded dataset. `kaosctl dataset release dataset-x` gives the version `latest`
  points to the next number. It refuses when that state already has one: `nothing new to release`.
- **`latest`**, the name that points to the dataset's current version. It moves when a pull request is merged into an
  uploaded dataset, and when a run that has its `promote-<name>` field set to `true` makes a version of a produced one ([how to ask](flow-datasets.md#move-latest)).
  `latest` can be newer than the newest `vN`, because nobody has released the change yet. A version that a run sealed
  without asking is newer than `latest` in time, but it is not `latest`: nothing reads it unless you name its id.

The forms of a reference to a dataset, such as `dataset-<name>@<version>`, are in the
[Reference](reference.md#dataset-references).

## Fixed when the run starts

You choose the version on the run form. Before the first step starts, the platform turns each choice into one version
id, once. Every step of the run reads that id, even if `latest` moves while the run is going. If two steps name the
same setting, they read the same version.

A dataset that a step of this run makes is different: there is no choice to make. The later steps read the version that
step made, by its id.

## Where you see an id

| where | what you see |
|---|---|
| the log of a step that makes a dataset | `output 'clean': dataset-myapp-clean is now at b2e7b6573672 (latest).` |
| | `output 'clean': sealed dataset-myapp-clean at b2e7b6573672 (kept as ...); latest was not moved.` |
| | `output 'clean': the same content as the last version of dataset-myapp-clean (b2e7b6573672); no new version.` |
| the result of a step | the full id, 64 characters, in `reads` and `writes` ([below](#what-a-run-records)) |
| `kaosctl step run` on your laptop | `read    clean: dataset-myapp-clean at b2e7b6573672` |
| the MLflow run of a step that uses MLflow | the file `ledger/<step>.json` and the tags `kaos_lib.data.<dataset>.commit` |

On your laptop an id is a fingerprint of the files: the same files give the same id. On the platform it is the id the
data store gives the version.

## Which id a run records for what it made

| the step | the id of the write |
|---|---|
| made new files and the run asked to move `latest` | the version `latest` now points to |
| made new files and the run did not ask | the version that was made. `latest` did not move |
| made the same files as the last version | the last version: no new version exists |

## What a run records

Each step's result lists what it read and wrote. This is the result of `hello-world` from page 5, when `prepare` made
the dataset `clean` in the same run:

```json title="result of hello-world"
--8<-- "examples/ledger/hello-world-result.json"
```

- `reads` has one entry for every input the step declares in `inputs=`, opened or not, and one for every dataset made by
  an earlier step that this step read. `ref` is the version that was asked for; for a dataset made in this run it is the
  id. `commit` is the exact id.
- `writes` has one entry for every output: dataset, model or artifact.
- The ids here are the fingerprints of a local run.

### Which data made this model?

Open the MLflow run of the step that trained the model and read `ledger/<step>.json`: it names the id of every dataset
the step read. To run a command on exactly those versions again:

```bash
kaosctl run --lock <mlflow run id> -- python my_script.py
```

A step has a ledger on its MLflow run only if it uses MLflow (`from kaos_lib.mlflow import mlflow`).

## Only the difference is uploaded

A new version of a dataset shares every file that did not change with the last version (`latest`), and a run uploads
only the files that changed. A run that does not move `latest` also does not upload what the last run sealed: a file
with the same path, size and content as in the newest version an earlier run sealed is copied inside the data store,
not uploaded. Every run still gets its own version.

The log says how many files were uploaded, how many were unchanged and how many were reused:
`output 'clean': 1 file(s) to upload, 0 to delete, 2 unchanged since the last version of dataset-myapp-clean.` or, after
an earlier run that did not move `latest`, `output 'clean': 0 file(s) to upload, 0 to delete, 0 unchanged since the last
version of dataset-myapp-clean, 201 reused from an earlier run (copied, not uploaded).` If a file cannot be copied, the
step uploads it and says so: `output 'clean': 1 of the 201 file(s) could not be copied and were uploaded.`

Keep each file at the same path from run to run, so that it counts as unchanged. An output of less than 1 MiB to upload is simply uploaded. A run that writes exactly the files of
the last version makes no new version.

## When a step is run again

The platform runs a step again when its machine was lost or its time limit was reached ([Long jobs](long-jobs.md)). Each
attempt starts with empty output folders, and only the attempt that ends with `step.result()` makes the result. What a
retry does with what it writes:

| output | what the retry does |
|---|---|
| a dataset | seals its version again. If the files are exactly the ones an earlier attempt of this step already sealed, that version is used: no second version. The version is kept under the name `k-<time>-<run>-<step>-<12 characters of the id>`, where the time is when the step sealed it, such as `20261112T093015Z`, which the log shows as `kept as ...` |
| a model or an artifact | replaces the folder `<name>/<experiment>/<run>/` with exactly what the retry wrote; a file of the earlier attempt that the retry did not write is gone |

So a retry writes each output once. If `latest` moved while the step was away (another run asked to move it), the retry
seals on the new `latest` and does not reuse the older seal. When two runs ask to move `latest` at the same time, see
[Move `latest`](flow-datasets.md#move-latest). Models and artifacts are not shared that way: each run keeps its own
folder, `<name>/<experiment>/<run>/`.

## What does not exist

- A version that is edited. A new version is made instead.
- A step that picks a version in code. The form picks it.
- A partial version. What a failed step can leave behind is in [Principles](principles.md#what-is-saved).

Next: [Glossary](glossary.md).
