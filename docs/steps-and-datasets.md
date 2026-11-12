# How steps use datasets

A step declares the datasets it reads and names them in code. It never names a version. Every step of a run
reads the same data, even when the run takes hours and a dataset changes while it runs. This page explains how.

## What a step does

In `config/`, a setting holds the dataset and its version:

```yaml
dataset: "dataset-toy@latest"       # or dataset-toy@v1, or <owner-project>/dataset-toy@v1 for a shared one
```

In `pipeline.py`, the step names that setting:

```python
train = step("train", kind="train", inputs=["dataset"], gpu=True)
```

In the step, the name gives the files:

```python
from kaos_lib import step

step.start()
data = step.input("dataset")        # a folder
```

A step can read several datasets: name several settings in `inputs=` (`inputs=["images", "labels"]`) and call
`step.input()` for each.

## Where the version is chosen

Once, when the run is submitted:

| where | how |
| --- | --- |
| the run form | the dataset field offers the dataset's versions; `latest` is the default |
| `config/` | the default the form shows, for example `dataset-toy@v3` |

It can be `latest`, a named version such as `v3`, or a commit. `latest` is not a version: it means "the newest
when the run starts".

## The pin

Before any step runs, the platform turns every setting named in an `inputs=` into one exact commit. That commit
is the **pin**. `step.input()` reads the pin and never asks what `latest` is now.

| the pin guarantees | the pin does not do |
| --- | --- |
| every step of the run reads the same commit | make `latest` stop moving: the next run pins the newer commit |
| new data merged while the run is going does not change what the run reads | pin data that a step reads without kaos-lib |
| a wrong dataset name or version stops the run before any step uses time | let a step read a dataset it did not declare: that is refused |
| it works the same for your own and for shared datasets | |

### A run of six hours

You start a run on `dataset-toy@latest`. Your colleague merges new rows while it runs.

| time | what happens | the data the step reads |
| --- | --- | --- |
| 09:00 | you start the run. The platform turns `latest` into commit `c1` | |
| 09:05 | `data-check` starts | `c1` |
| 09:20 | `train` starts (it takes five hours) | `c1` |
| 11:30 | a colleague merges new rows. `latest` is now commit `c2` | |
| 14:25 | `evaluate` starts | `c1` |
| 15:00 | the run ends. Its results say `c1` | |
| 15:10 | you start the next run. The platform turns `latest` into `c2` | `c2` |

Every step read the data as it was at 09:00. To read the same data in every run, not only in every step of one
run, choose a version: `dataset-toy@v1`.

## Your own and shared datasets

| | your own dataset | a dataset shared with your project |
| --- | --- | --- |
| the setting | `dataset-toy@v1` | `<owner-project>/dataset-toy@v1` |
| the code | `step.input("dataset")` | the same |
| who can change it | your project | only the owner project |

[Datasets shared with your project](shared-datasets.md) explains sharing.

## A dataset a step produces

A step can write a dataset, and the steps after it read it by name:

```python
prepare = step("prepare", kind="transform", inputs=["raw"], produces=[dataset("clean")])
train = step("train", kind="train", needs=[prepare], gpu=True, produces=[model("model")])
```

```python
# steps/prepare/app/entry.py
raw = step.input("raw")
clean = step.output("clean")
...                                  # write the cleaned files into `clean`
step.result(rows=rows)
```

```python
# steps/train/app/entry.py
data = step.input("clean")           # exactly what "prepare" wrote in this run
```

In code the dataset is just `"clean"`. Its repository carries your app's name, `dataset-<app>-clean` (for the app
`hera1`, `dataset-hera1-clean`), so two apps made from one template never share a dataset. A later run, or another
pipeline, reads it as an ordinary input: a setting `clean: dataset-hera1-clean@latest` named in `inputs=`.

What `step.result()` does with the folder:

| | |
| --- | --- |
| the version | The dataset (`dataset-<app>-clean`) gets one new version that holds exactly the files of the folder: files you did not write are not in it. |
| only what changed is stored | The folder is compared with the dataset's last version. Unchanged files are not uploaded and take no new space, so a run that changes one file uploads one file, and the difference between two versions is the real change. Keep each file at the same path in every run. |
| the same content | A run that writes exactly the last version makes no new version. |
| every run keeps its version | The steps after it in the same run read exactly that version, and it stays readable by its commit. |
| `latest` | It moves to the run's version only when the run asks for it. Until the run form has a field for it, put `plan: {promote: {clean: true}}` in the run's advanced config (the name is the one in `produces=`). An experiment therefore never changes what other pipelines read. |
| two runs at once | When two runs both ask to move `latest`, the second one notices that the dataset changed, writes its version again on top of the new one, and then moves `latest`. `latest` is always one run's complete version, never a mix of two. |
| a step that is stopped half-way | It leaves no version. The next attempt writes it once. |
| who may write | Only the app whose pipeline declares the dataset in `produces=`. People read it and can name its versions. |

Check the folder before it is saved with `step.check("clean", layout="yolo", min_files=10)`
([The step API](step.md#stepcheckname-layoutnone-min_files1)).

## Where the data lands

| where the step runs | what `step.input()` returns |
| --- | --- |
| the platform's machines | a copy downloaded once for that commit; a second step, or a retry, finds it there |
| HPC (Slurm) | the copy the platform put next to the job before it started; nothing is downloaded on the job's time |
| your machine, with `kaosctl step run` | the folder or the sample you gave with `--input` |

Never write into that folder. It is shared and read-only on HPC (Slurm), and a cache elsewhere.

For a dataset with the `yolo` layout, the folder holds a `data.yaml` whose `path:` points at the files:
`step.input("dataset") / "data.yaml"`.

## What is recorded

`step.result()` records every dataset version the step opened, with its name, its repository, the version that
was asked for and the exact commit. [Results](results.md) shows the record and where it is kept. You write
nothing for it.

## Reproduce an old run

```bash
kaosctl run --lock <mlflow-run-id> -- python my_evaluation.py
```

runs a command on exactly the data that run read ([Data lock](data-lock.md)).

## Common mistakes

| what you see | why | what to do |
| --- | --- | --- |
| `'images' is not an input of step 'train'` | the name is not in the step's `inputs=` | add it: `inputs=["images"]` |
| `dataset-x is not an input of step 'train'` | the code asked kaos-lib for a dataset the run did not pin | name the setting that holds it in `inputs=` and use `step.input()` |
| the step fails with `holds no files` | the pinned version is empty | push data with `kaosctl dataset push`, then run again |
| a step reads a dataset with another client (a plain HTTP or S3 call) | that read is neither pinned nor recorded | use `step.input()` |
| two runs on `@latest` gave different results | they pinned different commits | choose a version, or compare the commits in the two results |
