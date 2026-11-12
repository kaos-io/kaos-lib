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
the exact version that was read ([the result](data-reads.md#what-a-run-records)). The step may open the
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
step may read at most 16 datasets by name ([limits](contract.md#the-limits)).

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

**You want** `latest` to point to the version a run made. A step only makes its version. `latest` moves once, at the end of
the run, and only when the whole run went well.

The run form has a choice for each dataset the pipeline makes: `promote-<name>`, with the name from `produces=`
(`promote-clean` for `dataset("clean")`). It offers `false` and `true`, and the default is `false`. Set it to `true` for the
run that should move `latest`. A run that leaves it at `false` still makes its version, and leaves `latest` where it was, so
an experiment never changes what other pipelines read.

**The run records** the version the step made, in the step's result. Later steps of the run read that version, whether or
not `latest` moves.

What happens in each case is in [When `latest` moves](data-writes.md#when-latest-moves): when two datasets are ticked, when
two runs ask at once, and when the end of a run is cut short.

Next: [The data contract](data-contract.md).
