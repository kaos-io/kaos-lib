# ingest

## What it is for

An `ingest` step brings data in from outside the platform: a download, a copy from a source you own. It writes the new
files into a dataset, so it must produce one.

## The contract

| | |
|---|---|
| **Must** | produce at least one dataset: `produces=[dataset("name")]`. Write at least one file into each output before `step.result()` |
| **May** | read datasets (`inputs=`) and earlier steps (`needs=`); also produce a model or an artifact; set `walltime=` (the default of the run form's time limit), `when=`, `gpu=True`, `resumable=` |
| **Must not** | nothing more than every step must keep to ([the contract](contract.md#what-you-write)) |

## Where it runs

On the platform's own machines, always. The run form offers an `ingest` step no HPC (Slurm) class.

## What the platform does

- Checks, when the pipeline is built, that `produces=` holds a dataset.
- Runs the step on the platform's own machines, and never makes an HPC (Slurm) variant of it.
- Seals the dataset as one new version when the step calls `step.result()`. The name `latest` moves to it at the end of
  the run, only if the run form's `promote-<name>` is `true` and every step went well
  ([what a run writes](data-writes.md)).
- Hands the next steps the exact version the step made, whatever `latest` is.

The platform does nothing else for `ingest`: a download that fails, or a source that changes, is your code's to handle.

## A complete minimal example

```python title="pipeline.py"
--8<-- "examples/flows/ingest/pipeline.py:6:7"
```

```python title="steps/fetch/app/entry.py"
--8<-- "examples/flows/ingest/steps/fetch/app/entry.py"
```

```yaml title="config/source.yaml"
--8<-- "examples/flows/ingest/config/source.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/ingest/config/config.yaml"
```

`step.check("raw", min_files=1)` makes the step fail, and save nothing, when the source gave no file. The address of the
source is a setting, so it is a field on the run form. The steps after `fetch` read the dataset with `needs=[fetch]` and
`step.input("raw")` ([Bring data in](bring-data-in.md)).

## Common mistakes

| the mistake | what you get |
|---|---|
| no dataset in `produces=` | `kaosctl lint`: `L-E07`, `Step 'fetch': an ingest step brings data in, so it produces a dataset. Add produces=[dataset("name")].` The platform's check says the same: `step 'fetch': an ingest step brings data in, so it produces a dataset. Add produces=[dataset("name")].` |
| the step wrote no file | `output 'raw' is empty: the step wrote no files into ...` and nothing is saved |
| the step never asked for the output folder | `output 'raw' was not written: step 'fetch' declares it in produces= and never called step.output('raw').` |
| an HPC (Slurm) class chosen on the run form | `step 'fetch' cannot run on class '...': an ingest step never runs on HPC (Slurm). Choose one of: ...` The run is refused before it starts |

## Related

[Step types](step-types.md) · [Bring data in](bring-data-in.md) · [What a run writes](data-writes.md) ·
[Your contract with the platform](contract.md)
