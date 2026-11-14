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

## A dataset a step made, read on HPC (Slurm)

A step on HPC (Slurm) runs in your project's storage on the site, so the datasets it reads are copied there first. This
holds for a dataset an earlier step made in the same run, such as `clean` made by `prepare`.

| question | answer |
|---|---|
| what is copied | every dataset the step reads, and every dataset made by a step in its `needs=`, even if the step never opens it. The whole version, every file |
| which version | the exact version the earlier step sealed in this run, never `latest` |
| when | before the job is sent to the Slurm queue. The copy is not part of the step's time limit. The step waits, and its status says how far a long copy is, every 10 minutes |
| what the step gets | `step.input("clean")` returns the copy on the site. The step code is the same as on the platform's own machines |
| the next HPC run | reuses the copy if the site holds that version. Otherwise it fetches only the files that differ from a version of the same dataset that the site already holds |

The step's log says what happened, one line for each dataset:

```text
HPC: dataset dataset-myapp-clean@b2e7b6573672 staged (first copy), 1.4 GB, 95s
HPC: dataset dataset-myapp-clean@91c0e0aa1f3d staged (delta), 12.0 MB, 4s
HPC: dataset dataset-myapp-clean@91c0e0aa1f3d staged (already cached)
```

- `first copy`: the site held no version of the dataset, and every file was copied.
- `delta`: only the files that differ from a version the site held were copied.
- `already cached`: the site held this version whole, and nothing was copied.

A run that makes the same files as the last version makes no new version
([unchanged content](data-writes.md#unchanged-content-makes-no-new-version)), so the next HPC run finds the same version
and copies nothing. A run that changes some files makes a new version, and its copy is a delta.

If the copy cannot be made, a dataset of up to 50 GB is downloaded by the step itself, when the job has started and counts
against its time. A larger one stops the run before the job is sent: the reason is `DatasetNotStaged`. Run the step
again: the copy goes on from the files that are already on the site ([the reasons](when-something-goes-wrong.md#why-an-hpc-slurm-step-waits-or-is-refused)).
A file whose name ends in `.kaos-part`, or a path that could leave the dataset's folder (a `..` part, a leading `/`), also stops the run before the job is sent: rename or remove the file and make a new version. How long the copies stay on the site is on [Clean up](clean-up.md).

## When a dataset is empty

A new app's first run reads the empty default dataset, and a step that opens it fails with
`input 'dataset': dataset-default holds no files at the version this run read (latest). Push data to it with kaosctl dataset push <folder> dataset-default, or choose another dataset for 'dataset' on the run form.`
Push files and merge the pull request ([page 1](run-it.md#put-a-few-files-in-a-dataset)), or pick another dataset on the run
form.

Next: [What a run writes](data-writes.md).
