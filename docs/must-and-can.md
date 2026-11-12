# What you must and what you can

Three tables: what every step must do, what you can add when you need it, and what you cannot do yet. The numbers
are in [The limits](#the-limits) at the end. Every row is checked by `kaosctl lint`, by the platform when it builds the
pipeline, or by the library when the step runs.

## You must

| rule | what happens if you break it |
|---|---|
| Give every step a `kind=`: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control` | the pipeline is refused: `has no kind=, which every step declares` |
| Call `step.start()` first and `step.result()` last, once | `call step.start() first.`; a step without `step.result()` fails with `ended without step.result()` |
| Name steps, inputs and outputs with lowercase letters, digits and hyphens, none starting with `kaos-` | the pipeline is refused. A step is not named `main` or `hpc-follower`, and its name does not end in `-hpc`; the message lists the other names the platform keeps |
| Read only what you declared: `inputs=` for datasets, `needs=` for earlier steps | `'x' is not an input of step 'y'. Its inputs are: ...` |
| Write every output you declared in `produces=`, and put at least one file in it | `output 'x' was not written` or `output 'x' is empty`, and nothing is saved |
| Give an input and an output of one step different names | the step fails in `step.start()` |
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
| Read a dataset that another project shares with yours | `<owner>/dataset-<name>@<version>` in the same setting | [Reference](reference.md#dataset-references) |
| Hand small values to the next step | `step.result(**values)`, `step.upstream("x").values` | [Values and files](flow-between-steps.md) |
| Hand files to the next step | `artifact("name")` in `produces=` | [Values and files](flow-between-steps.md#files-to-the-next-step) |
| Make a dataset, a model or an artifact | `dataset("n")`, `model("n")`, `artifact("n")` in `produces=` | [Pass things on](pass-things-on.md) |
| Skip a step by a choice on the form | `when="{{workflow.parameters.<field>}} != off"` | [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| Cope with a skipped step | `step.upstream("x", optional=True)`, `step.input("x", optional=True)` | [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| Need several steps at once | `needs=[a, b]` | [Fan-in](flow-between-steps.md#one-step-needs-several-steps) |
| Check an output before it is saved | `step.check("name", min_files=10)`, or `layout=` | [Produce a dataset](produce-a-dataset.md) |
| Edit files of an input | `step.input("x", writable=True)`, a private copy | [Read data](read-data.md#rules) |
| Use a scratch folder that is never saved | `step.workdir()` | [Cheat sheet](cheat-sheet.md) |
| Ask for a GPU | `gpu=True` | [Bigger machines](bigger-machines.md) |
| Limit a run on HPC (Slurm) | `walltime="12h"` | [HPC (Slurm)](hpc.md) |
| Continue after an interruption | `checkpoint.load/save`, `resumable=`, `checkpoint_every=` | [Long jobs](long-jobs.md) |
| End a GPU step that sits idle sooner or later | `idle_timeout=` | [Bigger machines](bigger-machines.md#rules) |
| Move `latest` of a dataset you make | `plan: {promote: {<name>: true}}` in the run's advanced config | [Move `latest`](flow-datasets.md#move-latest) |
| Test a step on your laptop | `kaos_lib.testing.running`, `kaosctl step run` | [Test your steps](test-your-steps.md) |

## You cannot, for now

| what | why |
|---|---|
| Write a dataset that another app declares | only the app that declares a dataset writes it |
| Run a step that makes a dataset on HPC (Slurm) | it runs on the platform's own machines for now; its neighbours may run on HPC |
| Choose the version of a dataset in code | the run form chooses it |
| Move `latest` from a field of the run form | the advanced config of the run holds the request until the form has a field |
| Make a dataset as a variant of another one (`dataset("x", of=...)`) | refused: not available yet |
| Put a pipeline on a schedule | a pipeline cannot declare one yet (`L-I03`) |
| Compose your settings from `config/` on your laptop without a `params.yaml` | `kaosctl step run` needs `--params-file` ([Test your steps](test-your-steps.md#run-the-steps-one-after-the-other)) |

## The limits

| what | limit |
|---|---|
| a step, input or output name | 40 characters of `a-z`, `0-9`, `-`; no `kaos-` at the start |
| the name of a dataset a step makes | at least 3 characters; the whole `dataset-<app>-<name>` is `dataset-` and 3 to 48 characters |
| an app name | 55 characters |
| steps in `needs=` | 10 |
| datasets one step reads | 16 (its inputs and what its needed steps produce) |
| the result of a step | 8 KiB |
| what a step receives (settings and results of needed steps) | 96 KiB |
| the advanced config of a run | 16 KiB |
| a dataset version in a reference | 255 characters |
| continuations of a resumable step on HPC (Slurm) | 5 |
| the longest run on HPC (Slurm) | set by the site; the linter assumes 2 days when it has no project facts |
