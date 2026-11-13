# What a run reads

## Fixed when the run starts

You choose the version on the run form. Before the first step starts, the platform turns each choice into one version id,
once. Every step of the run reads that id, even if `latest` moves while the run is going. If two steps name the same
setting, they read the same version. A colleague who adds files while your run is going changes nothing for it.

A dataset that a step of this run makes is different: there is no choice to make. The steps that need that step read the
version it made, by its id, whatever `latest` is.

## How a step asks for data

A step declares what it reads, and gets exactly that. Asking for anything else fails with a message that names what is
declared.

| you want to read | declare | in code | the version comes from |
|---|---|---|---|
| a setting: a small value, a text, a number | `reads=["section"]` | `step.start().params["section"]` | the run form's field for that setting |
| a dataset: yours, another app's, or another project's | `inputs=["name"]`, and a top-level value in `config/` that holds the address | `step.input("name")` | the run form's field `name`, fixed to one exact version when the run starts |
| something an earlier step of this run made: a dataset, a model or an artifact | `needs=[step]` | `step.input("name")` with the name in that step's `produces=` | exactly what that step made in this run |
| the small values an earlier step handed on | `needs=[step]` | `step.upstream("step").values` | that step's result |

`step.input("name")` takes the name and nothing else. There is no version in code, so there is no way to read a
different version from the one the run chose. A name is an input, or something a needed step made, never both: the
pipeline is refused when one name would mean two things.

A step may read at most 16 datasets by name, and need at most 10 steps ([the limits](contract.md#the-limits)). The folder
`step.input(...)` returns is read-only; `writable=True` gives a private copy.

## What a run records

Each step's result lists what it read and wrote. This is the result of `hello-world` from page 5, when `prepare` made the
dataset `clean` in the same run:

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

## When a dataset is empty

A new app's first run reads the empty default dataset, and a step that opens it fails with
`input 'dataset': dataset-default holds no files at the version this run read (latest). Push data to it with kaosctl dataset push <folder> dataset-default, or choose another dataset for 'dataset' on the run form.`
Push files and merge the pull request ([page 1](run-it.md#put-a-few-files-in-a-dataset)), or pick another dataset on the run
form.

Next: [What a run writes](data-writes.md).
