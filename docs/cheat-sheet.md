# Cheat sheet

Every keyword of `step(...)` in `pipeline.py` and every call of the step API, one line each. Each line links to the page
that explains it.

## `step(name, ...)` in `pipeline.py`

`from kubecore.authoring import artifact, dataset, model, pipeline, step`. Everything after `name` is a keyword.

| keyword | one line | page |
|---|---|---|
| `name` | the step's name and its folder `steps/<name>`: lowercase letters, digits, hyphens, at most 40 | [Must and can](must-and-can.md#you-must) |
| `kind=` | required: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control`; each has a contract | [Step kinds](step-kinds.md) |
| `reads=` | the `config/` sections the step gets in `step.start().params` | [Settings](settings.md) |
| `inputs=` | top-level `config/` values that hold a dataset reference; read with `step.input` | [Read data](read-data.md) |
| `needs=` | the steps that run before this one: their results and what they made | [Pass things on](pass-things-on.md) |
| `produces=` | what the step makes: `dataset("n")`, `model("n")`, `artifact("n")` | [Reference](reference.md#what-produces-makes) |
| `gpu=` | `True` asks for one GPU | [Bigger machines](bigger-machines.md) |
| `when=` | a run-form field or a value of a needed step, compared with a text: `"extra-mode != off"`, `"evaluate.passed == true"`; the step is skipped when it is false | [Conditions and skipping](conditions-and-skipping.md) |
| `walltime=` | the longest the step may run, anywhere: `"90m"`, `"12h"`; the default of the run-form field `<step>-walltime` | [Long jobs](long-jobs.md#the-time-limit) |
| `resumable=` | how long before the limit the step is told to save: `True`, `"20m"`, `False` | [HPC (Slurm)](hpc.md#when-the-limit-is-reached) |
| `checkpoint_every=` | how often the platform copies the checkpoint folder: `"20m"`, `False` | [Long jobs](long-jobs.md) |
| `idle_timeout=` | minutes without GPU use before a GPU step ends as idle; `0` for never | [Reference](reference.md#pipelinepy) |

The exact refusals of each keyword are in the [Reference](reference.md#pipelinepy).

## The step API: `from kaos_lib import step`

| call | one line | page |
|---|---|---|
| `step.start()` | first call: the run, the step, the experiment and `params` | [Your first step](first-step.md) |
| `step.input(name, optional=False, writable=False)` | the folder of a dataset input, or of what a needed step made; `writable=True` is a private copy | [Read data](read-data.md) |
| `step.skip(reason)` | ends the step as skipped (exit code 0, nothing saved); `step.skipped(name)` is the reason an earlier step gave | [Conditions and skipping](conditions-and-skipping.md) |
| `step.output(name)` | the empty folder for an output you declared; saved by `step.result()` | [Pass things on](pass-things-on.md#hand-on-a-file) |
| `step.upstream(step, optional=False)` | the result of a needed step: `.values`, `.reads`, `.writes` | [Values to the next step](flow-between-steps.md#values-to-the-next-step) |
| `step.check(name, layout=None, min_files=1)` | a condition on an output, checked before anything is saved | [Reference](reference.md#step-api-kaos_libstep) |
| `step.workdir()` | a scratch folder, emptied for each attempt, never saved | [Reference](reference.md#step-api-kaos_libstep) |
| `step.result(**values)` | last call: saves the outputs and hands the values on | [Your first step](first-step.md) |

## Around a step

| call | one line | page |
|---|---|---|
| `testing.running(tmp_path, *, kind="train", name="step", app="app", experiment="test", params=None, inputs=None, upstream=None, upstream_writes=None, upstream_reads=None, produces=())` | call a step's `main()` in a test | [Test your steps](test-your-steps.md) |
| `checkpoint.load(name="state", default=None)`, `save(obj, name="state")`, `stop_requested()`, `exit_for_restart()` | keep your place and continue after a stop | [Long jobs](long-jobs.md) |
| `progress.report(done, total=None, unit="step")` | one progress line on the run page | [Reference](reference.md#run-tools) |
| `mlflow.mlflow(tracking_uri=None, token=None)` | sign the step in to the project's MLflow | [Reference](reference.md#run-tools) |
| `kaosctl lint`, `kaosctl step run` | check the pipeline, run a step on your laptop | [Lint checks](lint.md), [Test your steps](test-your-steps.md) |
