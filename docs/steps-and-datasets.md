# How steps use datasets

A run reads one dataset. Every step of the run reads the same data, even when the run takes hours and the dataset
changes while it runs. This page explains how, and what to do in a step.

## What a step does

Almost nothing:

```python
from kaos_lib import datasets

ref = datasets.DatasetRef.parse(cfg["dataset"])      # cfg is the composed config: see "How a step works"
data = datasets.materialize(ref)                      # the files of the run's commit
commit = datasets.resolve(ref)                        # the commit, to put in your results
```

The setting is `dataset: "<dataset>@<version>"`, for example `dataset-toy@v1` or `dataset-toy@latest`. A dataset that
another project shares with yours is `<owner-project>/dataset-toy@v1`. The code is the same for both.

No step chooses or pins a version. The platform did that before the first step started.

## The pin

Before any step runs, the platform reads the setting `dataset` and turns it into one exact commit. That commit is the
**pin**. It gives the pin to every step. When a step calls `materialize` or `resolve` for the run's dataset, kaos-lib
answers with the pinned commit, and does not ask what `latest` is now.

What the pin guarantees:

| the pin guarantees | the pin does not do |
| --- | --- |
| every step of the run reads the same commit | make `latest` stop moving: the next run pins the newer commit |
| new data merged while the run is going does not change what the run reads | pin data that a step reads without kaos-lib |
| a wrong dataset name or version stops the run before any step uses time | pin a second dataset. The platform pins only the setting named exactly `dataset`, and only when a step lists `dataset` in `reads=` (see [common mistakes](#common-mistakes)) |
| it works the same for your own and for shared datasets | pin your results repository: it holds what the run writes |

A run's pin is the platform's job. If a step itself calls `ref.with_commit(commit)` with the commit that `resolve` just
returned, nothing changes: it only saves a second look-up.

### A run of six hours

You start a run on `dataset-toy@latest`. Your colleague merges new rows while it runs.

| time | what happens | the data the step reads |
| --- | --- | --- |
| 09:00 | you start the run. The platform turns `latest` into commit `c1` | |
| 09:05 | `data-check` starts | `c1` |
| 09:20 | `train` starts (it takes five hours) | `c1` |
| 11:30 | a colleague merges new rows. `latest` is now commit `c2` | |
| 14:25 | `evaluate` starts | `c1` (`resolve` says `c1`, `materialize` gives the files of `c1`) |
| 15:00 | the run ends. Its results say `c1` | |
| 15:10 | you start the next run. The platform turns `latest` into `c2` | `c2` |

Every step read the data as it was at 09:00. To read the same data in every run, not only in
every step of one run, use a version: `dataset-toy@v1`.

## Your own and shared datasets

| | your own dataset | a dataset shared with your project |
| --- | --- | --- |
| setting | `dataset-toy@v1` | `team-a/dataset-toy@v1` |
| code | `DatasetRef.parse(cfg["dataset"])`, `materialize` | the same |
| pinned | yes | yes, and the lock records the owner |
| written to | by people, through a pull request | never: it is read-only |
| kept apart in the cache | `<cache>/<repo>/<commit>` | `<cache>/<owner>/<repo>/<commit>` |
| on HPC (Slurm) | yes | not yet: a step that would read it there is refused before it starts |

Reading a shared dataset in a step needs `kaos-lib[zitadel]` in the image. See [Datasets shared with your project](shared-datasets.md).

## All of a dataset or part of it

| you want | write | notes |
| --- | --- | --- |
| everything the layout names | `datasets.materialize(ref)` | the files of a `raw` dataset; for `yolo` the path of `data.yaml`, with its `images` and `labels` |
| one folder of a `raw` dataset | `datasets.materialize(ref, prefix="train")` | the returned folder holds that folder's files, with the prefix removed |
| a folder of your choice | `datasets.materialize(ref, dest="./data")` | the files are put there |
| a layout that downloads only what it needs | name it in the layout | `yolo` downloads `data.yaml`, `images/**` and `labels/**` |

`prefix=` works only for layouts that download the whole tree, such as `raw`. For `yolo` it is refused with a message
that says so. A dataset with no files raises `EmptyDataset`.

```python
train_dir = datasets.materialize(ref, prefix="train")      # only the files under train/
```

`materialize` keeps what it downloaded by (repository, commit), so a second call for the same commit and folder costs
nothing. Never write into the folder it returns: on HPC (Slurm) it is read-only, and elsewhere it is a cache that is
checked later.

`datasets.resolve(ref)` alone returns the commit and records the read, without downloading anything.

## Where the data lands

| | the platform's machines | HPC (Slurm) |
| --- | --- | --- |
| who downloads | the step, when it calls `materialize` | the platform, before the job starts: it copies the pinned commit next to the job |
| where | the step's own disk, under `$KUBECORE_CACHE_DIR` (default `~/.cache/kubecore/datasets`) | a folder next to the job, mounted read-only. kaos-lib uses it as it is |
| a second step | downloads its own copy: a step's disk is its own | gets the same staged copy |
| large datasets | ask for room with `disk="50Gi"` on the `step(...)` line | the job's GPU time is not spent on the download |
| the call | `materialize(ref)` | `materialize(ref)`, the same |

If the staged copy of an HPC (Slurm) job is not ready, the job downloads the same commit itself, and the step runs
unchanged.

## What is recorded

kaos-lib remembers every dataset commit a step reads, as `(owner, repository, ref) -> commit`. In a pipeline step, the
platform writes it to the step's MLflow run when that run ends: at `mlflow.end_run()`, when the step leaves
`with mlflow.start_run()`, or when a framework's own MLflow logging ends its run. A run that failed gets it too, and a
problem while writing never fails the step. So you can always say which data a result came from, and your code calls
nothing.

| recorded on the MLflow run | holds |
| --- | --- |
| tag `kaos_lib.data.<repo>.commit` | the commit or commits the run read, comma-separated |
| tag `kaos_lib.data.<repo>.owner` | the owning project, for a shared dataset |
| artifact `data.lock.json` | every read: repository, owner, ref and commit |

Several steps that write to one run add up: `data.lock.json` merges. In the MLflow UI, filter on the tag to find every run
that read a commit. A step that logs to no MLflow run records nothing. `kaos_lib.lock.write()` is still there for your own
machine, and for writing the lock to another run ([Data lock](data-lock.md)). A step that saves a result in your outputs
repository can also put the commit in the commit's metadata: `r.finish({"dataset_commit": commit})`.

## Reproduce an old run

The lock of a run is enough to read the same data again. Run any command with the lock of an MLflow run:

```bash
kaosctl run --lock <mlflow-run-id> -- python explore.py
```

`kaosctl run` prints the reads it replays, then starts your command. In that command, `materialize` and `resolve` of the
same dataset return the locked commit, whatever `latest` or the version says today. Your command needs your sign-in
(`kaosctl login`).

To run a step with it, start it from its folder and give it the settings:

```bash
cd steps/data_check
kaosctl run --lock <mlflow-run-id> -- python -m app.entry --params "$(cat ../../.kaos/local/params.yaml)"
```

`--params` takes the YAML text, so the file is read with `cat`. [Run a step locally](step-run.md) writes
`.kaos/local/params.yaml`. A step that needs the platform's own services, such as MLflow or your outputs repository,
needs them here too. The same lock works in code: `lock.DataLock.replay(lock.load(run_id))`.

Replay matches on (owner, repository, ref), and then on (owner, repository) when the lock holds one commit for that
repository. So while a lock is replayed, asking for another version of the same dataset returns the locked commit.
Start a fresh command without `--lock` to read another version.

## Common mistakes

| mistake | what happens | do |
| --- | --- | --- |
| no step lists `dataset` in `reads=` | the platform pins nothing. The steps resolve the version themselves, each at its own time | add `"dataset"` to the `reads=` of every step that reads it |
| the setting that names the dataset is not called `dataset` | the platform does not pin it. It pins only the setting named exactly `dataset`, and only when a step lists `dataset` in `reads=` | name it `dataset`. For a second dataset, resolve it in the first step that needs it, and pass `commit` on in the step's output; later steps call `ref.with_commit(commit)` |
| a step picks a version itself: `latest`, `versions(...)[-1]`, a literal `@v3` in code | different steps can read different data. The run form's choice is ignored | read `cfg["dataset"]` |
| the dataset is read with another client (a plain S3 or HTTP call) | the read is neither pinned nor recorded | use `materialize`, or `lock.record(...)` ([Data lock](data-lock.md)) |
| `@latest` to compare two runs | each run pins a different commit | release a version and use `@v1` |
| the step logs to no MLflow run | nothing is recorded: the lock is written to a run when the run ends | log the step's work to an MLflow run ([MLflow](mlflow.md)) |
| the step writes into the folder `materialize` returned | the write fails on HPC (Slurm), or is lost | copy the files, then change the copy |
| the `dataset` setting names something that is not a dataset (its name does not start with `dataset-`) | the run stops in its first step, before any other step starts, and names the field | pick a dataset: `dataset-<name>@<version>` |
| a step that reads a shared dataset is placed on HPC (Slurm) | the step is refused before a job is submitted | run that step on the platform's machines, or ask the owner for a copy in your project |
| the dataset has no files yet | `EmptyDataset` | push files and release a version ([Datasets](datasets.md)) |
| the dataset is read from `context().dataset_ref` | it can be `None`: the platform does not fill it in every step | read `cfg["dataset"]` |

Back to [How a step works](steps.md), or look at the [step examples](step-examples.md).
