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

**You want** `latest` to point to the version a run made. A step only makes its version. `latest` moves once, at the
end of the run, and only when the whole run went well. A run that does not ask still makes its version, and leaves
`latest` where it was, so an experiment never changes what other pipelines read.

The run form has a choice for each dataset the pipeline makes: `promote-<name>`, with the name from `produces=`
(`promote-clean` for `dataset("clean")`). It offers `false` and `true`, and the default is `false`. Set it to `true` for
the run that should move `latest`.

| the run | the version it made | `latest` |
|---|---|---|
| has `promote-clean` set to `true`, and every step ended well | new | moves to it, at the end of the run |
| has `promote-clean` set to `true`, and a step failed | new, kept | stays |
| leaves `promote-clean` at `false` | new, kept | stays |
| writes the same files as `latest` already holds | none: the existing version is reused | unchanged |
| has a step that was skipped, and the skipped step makes the dataset | none | unchanged |

A run uploads only what differs from `latest` and from the newest version an earlier run sealed: a run that does not
promote does not upload the same files again on every run (it still makes its own version).

**All or nothing.** When a pipeline makes two datasets and both are ticked, the run moves both `latest` names, or
neither. At the end of the run the platform first checks every ticked dataset: its `latest` must still be the version
the step started from. If one has moved, the run moves none and fails, naming the dataset that moved. Every version the
run made is kept. Then it moves them all. Steps skipped with a condition or with `step.skip()` make nothing, so their
datasets are not moved, and the log of the run says so.

**The run records** the version the step made, in the step's result. Later steps of the run read that version, whether or
not `latest` moves.

### When two runs ask at once {#when-two-runs-write-at-once}

A dataset has one `latest`. When two runs of the same pipeline overlap and both ask to move it, the first to finish moves
it. **The second is refused whole, at the end.** It finds that `latest` has moved while it was running, and it fails with
a message that says which datasets it promoted (there can be some, when it was overtaken between two of them), which one
was moved by the other run, and which were not tried. A dataset the other run moved is not moved by this one. Every
version this run made stays kept, and you can read it by its exact version. Start a new run to promote the datasets it
names: the new run starts from the new `latest`. Only one pipeline writes a dataset, so this needs two runs of the same
pipeline at the same time.

### If the end of the run is cut short {#if-the-end-of-the-run-is-cut-short}

Moving two or more `latest` names is two or more actions, and one of them can fail after another succeeded (the data
store is not reachable, or another run moved a dataset in the instant between the check and the move). Then the datasets
that were already moved stay moved, and the others do not. The run fails and the message names both lists, and says
whether trying again can help. Nothing is lost: every version the run made is kept. After an outage the platform tries the
last task again by itself, and a dataset that this run already moved is recognised (even when another run has moved it
again since) and left alone. When another run moved a dataset, trying again cannot finish it: start a new run to promote
the datasets the message names.

Next: [Datasets, versions and hashes](datasets-versions-hashes.md).
