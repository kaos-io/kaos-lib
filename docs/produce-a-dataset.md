# 6. Produce a dataset

You have a step that produces a dataset. `prepare` declares it, and writes the files into its folder:

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:19:20"
```

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:10:10"
```

`step.output("clean")` is an empty folder. What it holds when `step.result()` is called becomes the dataset.

`dataset("clean")` in the app `myapp` is the dataset `dataset-myapp-clean`, with the app's name in the middle
([how datasets are named](data-contract.md#what-a-dataset-is)). Code uses the short name, `clean`, everywhere.

## What a run does with it

- **It seals a version.** When `step.result()` runs, the files of the folder become one version of the dataset. A
  version never changes afterwards, and the steps after `prepare` in the same run read exactly that version.
- **Only the difference is uploaded.** A run uploads only the files that differ from what the dataset holds and from
  what the last run sealed. A run that writes the same content as `latest` makes no new version; every other run makes
  its own version ([how](data-writes.md#only-the-difference-is-uploaded)).
- **A step that fails.** [What is saved](data-writes.md#what-is-saved-and-when) says what a failed step can leave behind.
- **Only the app that declares the dataset in `produces=` writes it.** People and other pipelines read it.

To make the step fail when the folder holds too few files, call `step.check("clean", min_files=10)` before
`step.result()` ([Reference](reference.md#step-api-kaos_libstep)).

## Where it runs

A step that produces a dataset runs on the cluster. The run form offers it no HPC (Slurm) class, and `gpu=True` does not
change that. To use HPC for the heavy work, make that step produce an `artifact` and let a cheap second step copy it into
the dataset ([HPC (Slurm)](hpc.md)). The check `L-W07` warns about a GPU step that produces a dataset.

## Move `latest`

The step only seals its version. The name `latest` moves to it when the run ends, if every step succeeded or was skipped
and the person who started the run set the field `promote-<name>` to `true` (this is called promoting). You write nothing
for that field: the platform adds one for every `dataset("<name>")` in `produces=`, with the default `false`. A run left at
`false` still seals its version, and `latest` stays where it is, so an experiment does not change what other pipelines
read. [Move `latest`](flow-datasets.md#move-latest) shows the field, and [when `latest` moves](data-writes.md#when-latest-moves)
says what happens when a pipeline makes more than one dataset.

## Read it from another pipeline

A second pipeline reads the dataset like any dataset: a setting holds the repository name, and the step declares it.

```yaml title="config/config.yaml"
--8<-- "examples/second-pipeline/config/config.yaml"
```

```yaml title="config/clean.yaml"
--8<-- "examples/second-pipeline/config/clean.yaml"
```

```python title="pipeline.py" hl_lines="7"
--8<-- "examples/second-pipeline/pipeline.py"
```

```python title="steps/evaluate/app/entry.py" hl_lines="7"
--8<-- "examples/second-pipeline/steps/evaluate/app/entry.py"
```

On the run form of the second pipeline the field `clean` offers your project's datasets and their versions,
`dataset-myapp-clean` among them. `latest` is the version a run of `myapp` promoted last ([what `latest` is](data-contract.md#what-a-version-is)).

Names, the one-writer rule and the other rules for datasets are in
[Your contract with the platform](contract.md).

Next: [Bigger machines](bigger-machines.md). The rules behind it are in [The data contract](data-contract.md).
