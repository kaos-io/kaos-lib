# Cheat sheet

Every keyword of `step(...)` in `pipeline.py` and every call of the step API, one line each. Each line links to the page
that explains it.

## `step(name, ...)` in `pipeline.py`

`from kubecore.authoring import artifact, dataset, model, pipeline, step`. Everything after `name` is a keyword.

| keyword | one line | page |
|---|---|---|
| `name` | the step's name and its folder `steps/<name>`: lowercase letters, digits, hyphens, at most 40 | [Must and can](must-and-can.md#you-must) |
| `kind=` | required: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control` | [Must and can](must-and-can.md#you-must) |
| `reads=` | the `config/` sections the step gets in `step.start().params` | [Settings](settings.md) |
| `inputs=` | top-level `config/` values that hold a dataset reference; read with `step.input` | [Read data](read-data.md) |
| `needs=` | the steps that run before this one: their results and what they made | [Pass things on](pass-things-on.md) |
| `produces=` | what the step makes: `dataset("n")`, `model("n")`, `artifact("n")` | [Pass things on](pass-things-on.md#what-each-output-is) |
| `gpu=` | `True` asks for one GPU | [Bigger machines](bigger-machines.md) |
| `when=` | a condition on a field of the run form; the step is skipped when it is false | [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) |
| `walltime=` | the longest run on an HPC (Slurm) class: `"90m"`, `"12h"` | [HPC (Slurm)](hpc.md#set-the-longest-run) |
| `resumable=` | how long before the limit the step is told to save: `True`, `"20m"`, `False` | [HPC (Slurm)](hpc.md#when-the-limit-is-reached) |
| `checkpoint_every=` | how often the platform copies the checkpoint folder: `"20m"`, `False` | [Long jobs](long-jobs.md) |
| `idle_timeout=` | minutes without GPU use before a GPU step ends as idle; `0` for never | [Bigger machines](bigger-machines.md#rules) |

The exact refusals of each keyword are in the [Reference](reference.md#pipelinepy).

## The step API: `from kaos_lib import step`

| call | one line | page |
|---|---|---|
| `step.start()` | first call: the run, the step, the experiment and `params` | [Your first step](first-step.md) |
| `step.input(name)` | the read-only folder of a dataset input, or of what a needed step made; `optional=True`, `writable=True` | [Read data](read-data.md) |
| `step.output(name)` | the empty folder for an output you declared; saved by `step.result()` | [Pass things on](pass-things-on.md#hand-on-a-file) |
| `step.upstream(step)` | the result of a needed step: `.values`, `.reads`, `.writes`; `optional=True` | [Values to the next step](flow-between-steps.md#values-to-the-next-step) |
| `step.check(name, min_files=1, layout=None)` | a condition on an output, checked before anything is saved | [Produce a dataset](produce-a-dataset.md) |
| `step.workdir()` | a scratch folder, emptied for each attempt, never saved | [Reference](reference.md#step-api-kaos_libstep) |
| `step.result(**values)` | last call: saves the outputs and hands the values on | [Your first step](first-step.md) |

## Around a step

| call | one line | page |
|---|---|---|
| `testing.running(tmp_path, ...)` | call a step's `main()` in a test | [Test your steps](test-your-steps.md) |
| `checkpoint.load`, `save`, `stop_requested`, `exit_for_restart` | keep your place and continue after a stop | [Long jobs](long-jobs.md) |
| `progress.report(done, total)` | one progress line on the run page | [Reference](reference.md#run-tools) |
| `mlflow.mlflow()` | sign the step in to the project's MLflow | [Reference](reference.md#run-tools) |
| `kaosctl lint`, `kaosctl step run` | check the pipeline, run a step on your laptop | [Lint checks](lint.md), [Test your steps](test-your-steps.md) |
