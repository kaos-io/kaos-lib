# Data flow: datasets

Scenarios for reading and making datasets. The first two are about what a run reads, the next three about what it
makes.

## Read a version chosen on the form

**You want** a step to read a dataset, and whoever starts the run to pick the version.

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:19:20"
```

```yaml title="config/dataset.yaml"
--8<-- "examples/first-pipeline/template/config/dataset.yaml"
```

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:10:10"
```

**The run records** a read named `dataset`: the repository, the version that was asked for (`v2`, `latest`, ...) and
the exact version that was read ([the result](datasets-versions-hashes.md#what-a-run-records)). The step may open the
folder or not: a declared input is recorded either way.

## A step with two inputs

**You want** one step to read two datasets, or two versions of one dataset. Name both in `inputs=`. Each name is a
setting, so each is a field on the run form with its own version.

```python title="pipeline.py"
--8<-- "examples/flows/two-inputs/pipeline.py"
```

```yaml title="config/before.yaml"
--8<-- "examples/flows/two-inputs/config/before.yaml"
```

```yaml title="config/after.yaml"
--8<-- "examples/flows/two-inputs/config/after.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/two-inputs/config/config.yaml"
```

```python title="steps/compare/app/entry.py"
--8<-- "examples/flows/two-inputs/steps/compare/app/entry.py"
```

**The run records** two reads, `before` and `after`, in the order of `inputs=`, each with its own exact version. A
step may read at most 16 datasets by name ([limits](must-and-can.md#the-limits)).

## Make a dataset and read it in the same run

**You want** a step to make a dataset, and the steps after it to read exactly what it made.

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:19:20"
```

```python title="steps/prepare/app/entry.py (writes)"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:10:10"
```

```python title="steps/hello_world/app/entry.py (reads)"
--8<-- "examples/first-pipeline/template/steps/hello_world/app/entry.py:7:7"
```

`needs=[prepare]` is what lets `hello-world` read `clean`. When `prepare` calls `step.result()`, the folder becomes one
version of the dataset `dataset-<app>-clean`, and `hello-world` reads that version, not whatever `latest` points to.

**The run records** a write of type `dataset` in the result of `prepare`, and a read of it in the result of
`hello-world`. A step that makes a dataset runs on the platform's own machines, not on HPC (Slurm) ([HPC](hpc.md#what-differs-on-hpc-slurm)).

## A second pipeline reads the dataset

**You want** a different pipeline of your project to use a dataset that the first one makes. It reads it like any
dataset. The name of the repository is `dataset-<app>-<name>`: the first app's name in the middle.

```yaml title="config/config.yaml"
--8<-- "examples/second-pipeline/config/config.yaml"
```

```yaml title="config/clean.yaml"
--8<-- "examples/second-pipeline/config/clean.yaml"
```

```python title="pipeline.py"
--8<-- "examples/second-pipeline/pipeline.py"
```

```python title="steps/evaluate/app/entry.py"
--8<-- "examples/second-pipeline/steps/evaluate/app/entry.py"
```

On the run form of the second pipeline the field `clean` offers the datasets of your project and their versions.
`latest` is the version that a run of the first pipeline moved it to last ([Move `latest`](#move-latest)). Only the
first pipeline writes it. The second only reads.

**The run records** a read named `clean` with the exact version, the same as for a dataset you uploaded.

## Move `latest`

**You want** `latest` to point to the version a run made. A run that does not ask still makes its version,
and leaves `latest` where it was, so an experiment never changes what other pipelines read.

The advanced config of the run holds the request, with the name from `produces=`:

```yaml title="advanced config of the run"
--8<-- "examples/first-pipeline/produce/runs/promote.yaml"
```

| the run | the version it made | `latest` |
|---|---|---|
| asks to promote | new | moves to it |
| does not ask | new | stays |
| writes the same files as `latest` already holds | none: the existing version is reused | unchanged |

A run uploads only what differs from `latest` and from the newest version an earlier run sealed: a run that does not
promote does not upload the same files again on every run (it still makes its own version).

**The run records** the version of the write. With a promotion that is the version `latest` now points to; without
it, the version that was made. Later steps read that version either way.

### When two runs ask at once {#when-two-runs-write-at-once}

A dataset has one `latest`. When two runs ask to move it at the same time, the second finds that `latest` has moved,
makes its version again on top of the new one, and then moves `latest`. It tries up to three times. So `latest` is always
the complete version of one run, never a mix of two. If it still cannot, the step fails with
`changed 3 times while this step was promoting it. Another run is writing the same dataset`, and the version it made is
kept, but `latest` does not point to it. Only one pipeline writes a dataset, so this is rare: it needs two runs of the
same pipeline.

Next: [Datasets, versions and hashes](datasets-versions-hashes.md).
