# Cheat sheet

The six step types, every keyword of `step(...)` in `pipeline.py` and every call of the step API. Each line links to the page
that explains it.

## Step types

The six values of `kind=`, side by side. [Step types](step-types.md) helps you pick one, and each kind has its own page.

| type | for | `inputs=` | must produce | may produce | must not | runs on | GPU | resumable | what the platform does for this type |
|---|---|---|---|---|---|---|---|---|---|
| [`ingest`](step-type-ingest.md) | bringing data in from outside | yes | a dataset | a model, an artifact | | the platform's own machines | `gpu=True` allowed | allowed | never offers an HPC (Slurm) class |
| [`transform`](step-type-transform.md) | turning data into other data | yes | something: a dataset, a model or an artifact | any of the three | | the platform's own machines or HPC (Slurm); a step that produces a dataset: the platform's own machines | `gpu=True` allowed | allowed | seals a version of each dataset it makes; offers HPC only when it makes no dataset |
| [`train`](step-type-train.md) | training a model | yes | a model | a dataset, an artifact | | the platform's own machines or HPC (Slurm); a step that produces a dataset: the platform's own machines | `gpu=True` allowed | allowed | keeps the model per run; `kaosctl lint` warns when a time limit has no way to continue (`L-W06`) |
| [`evaluate`](step-type-evaluate.md) | measuring a model or a dataset | yes | nothing | an artifact | a dataset, a model | the platform's own machines or HPC (Slurm) | `gpu=True` allowed | allowed | keeps reports per run; its values can decide later steps |
| [`publish`](step-type-publish.md) | delivering a result | yes | nothing | nothing | any `produces=` | the platform's own machines | `gpu=True` allowed | allowed | never offers an HPC (Slurm) class |
| [`control`](step-type-control.md) | steering the run | no | nothing | nothing | `inputs=`, any `produces=` | the platform's own machines | `gpu=True` allowed | allowed | never offers an HPC (Slurm) class; a failure stops the steps that need it |

## `step(name, ...)` in `pipeline.py`

`from kubecore.authoring import artifact, dataset, model, pipeline, step`. Everything after `name` is a keyword.

| keyword | one line | page |
|---|---|---|
| `name` | the step's name and its folder `steps/<name>`: lowercase letters, digits, hyphens, at most 40 | [Must and can](contract.md#what-you-write) |
| `kind=` | required: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control`; each has a contract | [Step types](step-types.md) |
| `reads=` | the `config/` sections the step gets in `step.start().params` | [Settings](settings.md) |
| `inputs=` | top-level `config/` values that hold a dataset reference; read with `step.input` | [Read data](read-data.md) |
| `needs=` | the steps that run before this one: their results and what they made | [Pass things on](pass-things-on.md) |
| `produces=` | what the step makes: `dataset("n")`, `model("n")`, `artifact("n")` | [Reference](data-writes.md#what-a-step-writes) |
| `gpu=` | `True` offers the step the GPU classes; how many GPUs it gets on HPC is in [GPUs on HPC (Slurm)](gpus-on-hpc.md) | [Bigger machines](bigger-machines.md) |
| `when=` | a run-form field or a value of a needed step, compared with a text: `"extra-mode != off"`, `"evaluate.passed == true"`; the step is skipped when it is false | [Conditions and skipping](conditions-and-skipping.md) |
| `walltime=` | the longest the step may run, anywhere: `"90m"`, `"12h"`; the default of the run-form field `<step>-walltime` | [Long jobs](long-jobs.md#the-time-limit) |
| `resumable=` | how long before the limit the step is told to save: `True`, `"20m"`, `False` | [HPC (Slurm)](hpc.md#when-the-limit-is-reached) |
| `checkpoint_every=` | how often the platform copies the checkpoint your step saved: `"20m"`, `False`; the default of the run-form field `<step>-checkpoint-every` | [Long jobs](long-jobs.md) |
| `idle_timeout=` | minutes without GPU use before a GPU step ends as idle; `0` for never | [Reference](reference.md#pipelinepy) |
| `matrix=` | values to try, `{"lr": [0.01, 0.001]}`: the step runs once for each combination and reads `params["lr"]`; the next step gets a list | [Sweeps](sweeps.md) |
| `matrix_allow_failed=` | `True` on a step with `matrix=`: the step after it runs when some runs failed and sees which; by default one failed run fails the step | [Sweeps](sweeps.md#pick-the-best) |

The exact refusals of each keyword are in the [Reference](reference.md#pipelinepy).

## The step API: `from kaos_lib import step`

| call | one line | page |
|---|---|---|
| `step.start()` | first call: the run, the step, the experiment and `params` | [Your first step](first-step.md) |
| `step.input(name, optional=False, writable=False, item=None)` | the folder of a dataset input, or of what a needed step made; `writable=True` is a private copy; `item=N` is the output of item N of a step with `matrix=` | [Read data](read-data.md) |
| `step.skip(reason)` | ends the step as skipped (exit code 0, nothing saved); `step.skipped(name)` is the reason an earlier step gave | [Conditions and skipping](conditions-and-skipping.md) |
| `step.output(name)` | the empty folder for an output you declared; saved by `step.result()` | [Pass things on](pass-things-on.md#hand-on-a-file) |
| `step.upstream(step, optional=False)` | the result of a needed step: `.values`, `.reads`, `.writes`; after a step with `matrix=`, a list with one entry for each item | [Values to the next step](flow-between-steps.md#values-to-the-next-step) |
| `step.check(name, layout=None, min_files=1)` | a condition on an output, checked before anything is saved | [Reference](reference.md#step-api-kaos_libstep) |
| `step.workdir()` | a scratch folder, emptied for each attempt, never saved | [Reference](reference.md#step-api-kaos_libstep) |
| `step.result(**values)` | last call: saves the outputs and hands the values on | [Your first step](first-step.md) |

## Around a step

| call | one line | page |
|---|---|---|
| `testing.running(tmp_path, *, kind="train", name="step", app="app", experiment="test", params=None, inputs=None, upstream=None, upstream_writes=None, upstream_reads=None, upstream_skipped=None, upstream_matrix=None, matrix=None, matrix_index=0, matrix_of=None, produces=())` | call a step's `main()` in a test | [Test your steps](test-your-steps.md) |
| `checkpoint.load(name="state", default=None)`, `save(obj, name="state")`, `stop_requested()`, `exit_for_restart()` | keep your place and continue after a stop | [Long jobs](long-jobs.md) |
| `progress.report(done, total=None, unit="step")` | one progress line on the run page | [Reference](reference.md#run-tools) |
| `mlflow.mlflow(tracking_uri=None, token=None)` | sign the step in to the project's MLflow | [Reference](reference.md#run-tools) |
| `kaosctl lint`, `kaosctl step run` | check the pipeline, run a step on your laptop | [Lint checks](lint.md), [Test your steps](test-your-steps.md) |
