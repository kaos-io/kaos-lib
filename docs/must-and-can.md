# What you must and what you can

Three tables: what every step must do, what you can add when you need it, and what you cannot do. The numbers are in
[The limits](#the-limits) at the end. Every row is checked by `kaosctl lint`, by the platform when it builds the
pipeline, or by the library when the step runs.

## You must

| rule | what happens if you break it |
|---|---|
| Give every step a `kind=`: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control` ([the six kinds](first-step.md#the-six-kinds)) | the pipeline is refused: `has no kind=, which every step declares` |
| Call `step.start()` first and `step.result()` last, once | `call step.start() first.`; a step without `step.result()` fails with `ended without step.result()` |
| Name steps, inputs and outputs with lowercase letters, digits and hyphens, none starting with `kaos-` ([names that are kept](#the-limits)) | the pipeline is refused |
| Read only what you declared: `inputs=` for datasets, `needs=` for earlier steps | `'x' is not an input of step 'y'. Its inputs are: ...` |
| Do not write into the folder of an input: copy what you change into an output, or ask for `writable=True` | what you write into the input folder is not saved |
| Write every output you declared in `produces=`, and put at least one file in it | `output 'x' was not written` or `output 'x' is empty`, and nothing is saved ([what is saved](principles.md#what-is-saved)) |
| Give an input and an output of one step different names | the step fails in `step.start()` |
| Give two steps that one step needs outputs of different names | the pipeline is refused |
| Define a step above the steps that need it | the pipeline is refused (`L-E05`) |
| Name in `reads=` only sections that exist in `config/`, and in `inputs=` only top-level text values of `config/` that hold a dataset reference | the pipeline is refused (`L-E05`, `L-E07`) |
| Let one step produce a dataset. A dataset has one writer | the pipeline is refused (`L-E07`) |
| Give a `control` step no `inputs=` and no `produces=`: it steers the run and handles no data | the pipeline is refused (`L-E07`) |
| Hand on only text, numbers, booleans, lists and objects with `step.result(...)`, under names that do not start with `kaos-` | `result value 'x' is a ...` |
| Keep a dataset output free of files under `.kaos/` | `output 'x' holds a file in .kaos/` |
| Keep `walltime=` off `ingest`, `publish` and `control` steps | the pipeline is refused |
| Leave out `outputs=`, `hpc_time_limit=` and `disk=`. Use `produces=` with `step.result()`, `walltime=`, and a bigger class | the pipeline is refused (`L-E06`) |

## You can

| what | how | page |
|---|---|---|
| Read a dataset at the version chosen on the form | `inputs=["dataset"]`, `step.input("dataset")` | [Read data](read-data.md) |
| Read several datasets in one step | several names in `inputs=` | [A step with two inputs](flow-datasets.md#a-step-with-two-inputs) |
| Read a dataset that another pipeline of the project makes | a setting that holds `dataset-<app>-<name>@latest` | [A second pipeline reads it](flow-datasets.md#a-second-pipeline-reads-the-dataset) |
| Read a dataset that another project shares with yours | `<owner>/dataset-<name>@<version>` in the same setting | [Share a dataset](share-a-dataset.md) |
| Hand small values to the next step | `step.result(**values)`, `step.upstream("x").values` | [Values and files](flow-between-steps.md) |
| Hand files to the next step | `artifact("name")` in `produces=` | [Values and files](flow-between-steps.md#files-to-the-next-step) |
| Make a dataset, a model or an artifact | `dataset("n")`, `model("n")`, `artifact("n")` in `produces=` | [Pass things on](pass-things-on.md) |
| Skip a step by a choice on the form | `when=` | [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| Cope with a skipped step | `step.upstream("x", optional=True)`, `step.input("x", optional=True)` | [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| Need several steps at once | `needs=[a, b]` | [Fan-in](flow-between-steps.md#one-step-needs-several-steps) |
| Check an output before it is saved | `step.check("name", min_files=10)`, or `layout=` | [Produce a dataset](produce-a-dataset.md) |
| Edit files of an input | `step.input("x", writable=True)`, a private copy that costs the dataset's size in disk and time | [Reference](reference.md#step-api-kaos_libstep) |
| Use a scratch folder that is never saved | `step.workdir()` | [Cheat sheet](cheat-sheet.md) |
| Ask for a GPU | `gpu=True` | [Bigger machines](bigger-machines.md) |
| Limit a run on HPC (Slurm) | `walltime="12h"` | [HPC (Slurm)](hpc.md) |
| Continue after an interruption | `checkpoint.load/save`, `resumable=`, `checkpoint_every=` | [Long jobs](long-jobs.md) |
| End a GPU step that sits idle sooner or later | `idle_timeout=` | [Reference](reference.md#pipelinepy) |
| Move `latest` of a dataset you make | a request in the run's advanced config | [Move `latest`](flow-datasets.md#move-latest) |
| Bring data in from outside | a step of kind `ingest` | [Bring data in](bring-data-in.md) |
| Add Python packages to a step | `RUN pip install` in the step's `Dockerfile` | [Add packages](add-packages.md) |
| Test a step on your laptop | `kaos_lib.testing.running`, `kaosctl step run` | [Test your steps](test-your-steps.md) |

## You cannot

| what | why |
|---|---|
| Write a dataset that another app declares | only the app that declares a dataset writes it |
| Run a step that makes a dataset on HPC (Slurm) | [it runs on the platform's own machines](hpc.md#what-differs-on-hpc-slurm) |
| Choose the version of a dataset in code | the run form chooses it |
| Move `latest` from a field of the run form | the advanced config of the run holds the request |
| Make a dataset as a variant of another one (`dataset("x", of=...)`) | refused |
| Put a pipeline on a schedule | a pipeline cannot declare one (`L-I03`) |
| Compose your settings from `config/` on your laptop without a `params.yaml` | `kaosctl step run` needs `--params-file` ([Try it locally](try-it-locally.md#run-steps-the-way-the-platform-does)) |

## The limits

Every number of the guide is in this table.

| what | limit |
|---|---|
| a step, input or output name | 40 characters of `a-z`, `0-9`, `-`; no `kaos-` at the start |
| step names that are kept | `main` and `hpc-follower`; a name that ends in `-hpc`; the refusal lists the others |
| the name of a dataset a step makes | 3 to 40 characters |
| the app name and the dataset name together | the dataset is `dataset-<app>-<name>`, and `<app>-<name>` has at most 48 characters, so a long app name leaves a short dataset name |
| an app name | 55 characters |
| steps in `needs=` | 10 |
| datasets one step reads | 16 (its inputs and what its needed steps produce) |
| the result of a step | 8 KiB |
| what a step receives (settings and results of needed steps) | 96 KiB |
| the advanced config of a run | 16 KiB |
| a dataset version in a reference | 255 characters |
| the limit of an HPC (Slurm) step that sets no `walltime=` | 4 hours. `walltime=` sets it, and it is read on a Slurm class only |
| the longest run on HPC (Slurm) | set by the site; `kaosctl lint` assumes 2 days when it has no project facts |
| continuations of a resumable step on HPC (Slurm) | 5 |
| a step without a checkpoint whose machine was lost | runs again from the start at most twice |
| a GPU step with no GPU use and no new log line | ends as idle after 20 minutes (`idle_timeout=` changes it, `0` turns it off) |

Next: [Datasets, versions and hashes](datasets-versions-hashes.md).
