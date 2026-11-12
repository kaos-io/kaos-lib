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
- **`vN`**, a label such as `v2`, on an uploaded dataset. `kaosctl dataset release dataset-x` gives the newest state of the
  dataset the next number. It refuses when that state already has one: `nothing new to release`.
- **`latest`**, the current state of the dataset: what it holds now. It moves when a pull request is merged into an
  uploaded dataset, and when a run that asks for it makes a version of a produced one. `latest` can be newer than the
  newest `vN`, because nobody has released the change yet.

A reference to a dataset is `dataset-<name>@<version>`, where the version is `vN`, `latest` or an id. Without a
version it means `latest`.

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

## Only the difference is stored

A new version of a dataset shares every file that did not change with the last version, and uploads only the files that
changed. The log says how many: `output 'clean': 1 file(s) to upload, 0 to delete, 2 unchanged since the last version
of dataset-myapp-clean.` Keep each file at the same path from run to run, so that it counts as unchanged. A run that
writes exactly the files of the last version makes no new version.

## When two runs write at once

A dataset has one `latest`. When two runs ask to move it at the same time, the second finds that `latest` has moved,
makes its version again on top of the new one, and then moves `latest`. It tries up to three times. So `latest` is always
the complete version of one run, never a mix of two. If it still cannot, the step fails with
`changed 3 times while this step was promoting it. Another run is writing the same dataset`, and the version it made is
kept. Only one pipeline writes a dataset, so this is rare: it needs two runs of the same pipeline.

Models and artifacts are not shared this way: each run keeps its own folder, `<name>/<experiment>/<run>/`.

## What does not exist

- A version that is edited. A new version is made instead.
- A step that picks a version in code. The form picks it.
- A partial version. A step that fails leaves nothing that a later step or run reads.
