# transform

## What it is for

A `transform` step turns data into other data: preprocess, filter, split, convert. It must produce something. Most
transforms produce a dataset.

## The contract

| | |
|---|---|
| **Must** | produce at least one thing: a dataset, a model or an artifact. Write at least one file into each output |
| **May** | read datasets (`inputs=`) and earlier steps (`needs=`); produce any mix of dataset, model and artifact; set `walltime=`, `when=`, `gpu=True`, `resumable=` |
| **Must not** | nothing more than every step must keep to ([the contract](contract.md#what-you-write)) |

## Where it runs

On the platform's own machines or on HPC (Slurm). A transform that produces a dataset runs on the platform's own
machines, whatever you pick: the run form offers it no HPC class. A transform that produces only a model or an artifact
may run on HPC.

## What the platform does

- Checks, when the pipeline is built, that `produces=` is not empty.
- Seals each dataset it produces as one new version when the step calls `step.result()`. A step that writes the files
  the dataset already holds makes no new version, and says so in its log. The name `latest` moves at the end of the run,
  if `promote-<name>` is `true` and every step went well ([what a run writes](data-writes.md)).
- Uploads only the files that differ from the last version.

## A complete minimal example

```python title="pipeline.py"
--8<-- "examples/kinds/transform/pipeline.py:6:8"
```

```python title="steps/filter/app/entry.py"
--8<-- "examples/kinds/transform/steps/filter/app/entry.py"
```

```yaml title="config/filter.yaml"
--8<-- "examples/kinds/transform/config/filter.yaml"
```

```yaml title="config/dataset.yaml"
--8<-- "examples/kinds/transform/config/dataset.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/kinds/transform/config/config.yaml"
```

The step reads the dataset the run form chose for `dataset`, and the files it copies into `filtered` become one version of
the dataset `dataset-<app>-filtered`. The steps after it read that version with `needs=` and `step.input("filtered")`.

## Common mistakes

| the mistake | what you get |
|---|---|
| nothing in `produces=` | `kaosctl lint`: `L-E07`, `Step 'clean': a transform step turns data into something. Add produces=[...] with a dataset, a model or an artifact.` The platform's check says the same with a small `s`: `step 'clean': a transform step turns data ...` |
| the input and the output have the same name | `L-E07`: `Step 'clean': 'clean' is both an input (inputs=) and one of its own outputs (produces=): the step reads and writes by name, so the two must differ.` Rename the setting, for example `previous-clean` |
| a second step produces the same dataset | `L-E07`: `Step 'b': the dataset 'clean' is already produced by step 'a'. A dataset has one writer.` |
| a dataset name of one or two letters | `L-E07`: `Step 'a': the dataset name 'ab' is too short. A dataset name has 3 to 40 characters: it is stored as dataset-<app>-<name>.` |
| the app name and the dataset name together are too long | the platform refuses it when it builds the run: `step 'a': dataset('x') in app 'y' is the repository 'dataset-y-x', and the lake allows 3 to 48 characters after 'dataset-': ...` (`kaosctl lint` does not check it: it does not know the app name) |
| a GPU transform that produces a dataset, hoping for HPC | `L-W07` warns: `Step 'embed' asks for a GPU and produces a dataset. A step that produces a dataset runs on the cluster only: the run form offers it no HPC (Slurm) class.` Split it: [Where it runs](produce-a-dataset.md#where-it-runs) |

## Related

[Step types](step-types.md) · [Produce a dataset](produce-a-dataset.md) · [What a run writes](data-writes.md) ·
[One GPU or four on HPC (Slurm)](one-or-four-gpus.md) · [Your contract with the platform](contract.md)
