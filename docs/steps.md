# How a step works

A pipeline is a list of steps. Each step is a small program that you write. The platform starts it, gives it its
inputs, collects its result and decides where it runs. This page is the whole contract between a step and the
platform. [The step API](step.md) describes every call, [Step examples](step-examples.md) shows complete steps,
and [How steps use datasets](steps-and-datasets.md) explains how a run reads and writes its data.

Coming from kaos-lib 0.4? [Move to kaos-lib 0.5](migrate-to-0.5.md) lists every change.

## What your app holds

| you write | what it is |
| --- | --- |
| `pipeline.py` | the steps, their order, what each reads and what each writes |
| `config/` | every setting of a run, with its default |
| `steps/<name>/app/entry.py` | the code of one step, and anything else it imports from `steps/<name>/app/` |
| `steps/<name>/Dockerfile` | the step's image: Python, kaos-lib and your libraries |

The platform owns everything else: how a run is started, how steps are connected, where they run, and how their
settings and data reach them. You never copy platform files into your app.

A step's name is its folder name with `-` instead of `_`: the step `data-check` lives in `steps/data_check/`.

## What you declare

You declare a step with one line in `pipeline.py`:

```python
from kubecore.authoring import artifact, dataset, model, pipeline, step

with pipeline("ml-pipeline") as p:
    prepare = step("prepare", kind="transform", reads=["prepare"], inputs=["dataset"],
                   produces=[dataset("clean")])
    train = step("train", kind="train", gpu=True, needs=[prepare], reads=["experiment", "train"],
                 produces=[model("model")])
    report = step("report", kind="evaluate", needs=[train], produces=[artifact("report")])
```

| option | meaning |
| --- | --- |
| `name` | lowercase letters, digits and `-`, no `-` at the start or end. Unique in the pipeline. |
| `kind=` | **Required.** What the step is: `ingest`, `transform`, `train`, `evaluate`, `publish` or `control`. |
| `reads=[...]` | the top-level sections of `config/` that the step uses. A name that is not in `config/` fails the check. |
| `inputs=[...]` | the names of the settings that hold a dataset reference, for example `"dataset"` for `dataset: dataset-my-data@latest`. The platform pins each to one exact version when the run starts; the step reads it with `step.input("dataset")`. |
| `needs=[...]` | steps that must finish first. Define a step above the steps that need it. Their results reach this step with `step.upstream(...)`, and what they produced with `step.input(...)`. |
| `produces=[...]` | what the step writes: `model("name")`, `artifact("name")` or `dataset("name")`. The step writes each into the folder `step.output("name")` gives it. |
| `gpu=True` | the step gets one GPU. |
| `when="..."` | a condition on a run-form value. When it is false the step is skipped. See [a conditional step](step-examples.md#5-a-conditional-step). |
| `disk="20Gi"` | more scratch disk than the default, as a size: digits and an optional unit (`Ki`, `Mi`, `Gi`, `Ti`, `K`, `M`, `G`, `T`). Use it for big datasets or big temporary files. |
| `walltime="12h"` | the longest this step may run when it runs on an HPC (Slurm) class: minutes or hours, such as `"90m"`, `"12h"` or `"720"`. |
| `resumable=` | GPU steps only. `True`, or a lead time such as `"20m"`: how long before the time limit the step is told to save. `False` turns continuing off. See [Long runs](checkpoint.md). |
| `checkpoint_every=` | how often the platform copies the step's checkpoint folder: `"20m"`, `"1h"`, `20` (minutes), or `False` for never. |
| `idle_timeout=` | how long a step may show no GPU use and no new log line before it is ended: `"40m"`, `"1h"`, `40`, or `0` for never. |

Names are read by name, so within one step an input and something a needed step produces cannot share a name,
and two needed steps cannot produce the same name.

[Check your pipeline](lint.md) (`kaosctl lint`) reads `pipeline.py` and tells you about mistakes before you push.

## What a step receives

The platform starts every step the same way, with no arguments:

```text
python -m app.entry
```

Everything the step needs comes from `kaos_lib.step`:

```python
from kaos_lib import step

ctx = step.start()                 # call it first
cfg = ctx.params                   # the config sections in reads=, with the values from the run form
data = step.input("dataset")       # a folder: the dataset version this run pinned for the input "dataset"
prev = step.upstream("prepare")    # the result of an earlier step: prev.values
```

| what | where it shows |
| --- | --- |
| the composed config: the sections the step names in `reads=` | `ctx.params`, a dictionary |
| the run, the app, the project, the step, its kind, the experiment | `ctx.run`, `ctx.app`, `ctx.project`, `ctx.step`, `ctx.kind`, `ctx.experiment` |
| a dataset the step declared in `inputs=` | `step.input("<name>")` |
| a dataset, model or artifact a step in `needs=` produced | `step.input("<name>")` |
| the values a step in `needs=` handed on | `step.upstream("<step>").values` |
| the lakeFS and MLflow addresses and your app's access to them | used by kaos-lib for you ([MLflow](mlflow.md)) |
| the folder for checkpoints | `kaos_lib.checkpoint.dir()` ([Long runs](checkpoint.md)) |

A step never reads an environment variable of the platform, and never parses a dataset reference.

## Your settings

Every setting in `config/` is a field of the run form. A section is a top-level key. A step lists in `reads=` the
sections it uses. Before the first step starts, the platform composes the config with the values from the form and
checks it. The run fails at once, before any step has used time, when:

- a value has the wrong type;
- a setting you changed is not in `config/`;
- a step reads a section that does not exist;
- a dataset reference cannot be found.

A list is not a form field. Give lists a default in `config/`, and change them in the advanced field of the run form.

## What a step writes

| what | how | how big |
| --- | --- | --- |
| a few small values for the next steps | `step.result(rows=1200, accuracy=0.93)` | a few kilobytes in all |
| a model, an artifact or a dataset version | files in the folder `step.output("<name>")`, saved by `step.result()` | any size |
| metrics, parameters, the model registry | MLflow ([MLflow](mlflow.md)) | any size |
| how far the step is | one line in the log, with `kaos_lib.progress` ([Progress](progress.md)) | |
| the state of a long run | the checkpoint folder, with `kaos_lib.checkpoint` ([Long runs](checkpoint.md)) | |

`step.result()` is the last call of every step. It saves each output and hands the result on. A step with nothing
to hand on still calls `step.result()`. [Results](results.md) explains what the result holds and where a model, an
artifact and a dataset version end up.

A step that ends with a non-zero exit code has failed, and the steps that need it do not run. A step that ends
without calling `step.result()` has failed too. Exit code `85` means "I saved my state, run me again": see
[Long runs](checkpoint.md).

## What the platform does for you

| the platform... | so you do not have to |
| --- | --- |
| composes and checks your settings before any step runs | check them in every step |
| reads each dataset choice once, as one exact version, and gives it to every step that declares it | pin or compare dataset versions |
| runs steps in the order of `needs=`, and passes their results on | wire steps together |
| skips a step whose `when=` is false, and still runs the steps after it | handle a missing step |
| gives every step its run, its config, its MLflow sign-in and its data access | handle passwords and addresses |
| lets a step write exactly what it declares in `produces=` | manage write access |
| records what every step read and wrote | keep a list of versions |
| copies the checkpoint folder of a GPU step and puts it back when the step is continued | save your state somewhere |
| runs the step again after a machine failure or a reclaimed machine | retry |
| shows the step's progress and logs | build a dashboard |

## What you must never do

| never | why | instead |
| --- | --- | --- |
| choose a dataset version in code: no `latest`, no `versions()[-1]`, no version in a string | two steps could read different data; the platform refuses a dataset the run did not pin | declare it in `inputs=` and call `step.input("<name>")` |
| read a password or a token from `config/` | settings are shown on the run form and stored with the run | the platform's sign-in, used by kaos-lib |
| print or log a credential | logs are kept | log what you computed |
| keep results anywhere but the folders `step.output()` gives you | the step's disk is gone when it ends | `produces=` and `step.output()` |
| write something the step did not declare in `produces=` | the step's access does not allow it, so the step fails | declare it |
| write into the folder that `step.input()` returns | it is a shared, read-only copy on HPC (Slurm), and a cache elsewhere | copy the files you change into an output |
| hand a large value on with `step.result()` | a result holds a few kilobytes | log metrics to MLflow, or write an artifact and hand on its name |

## Where a step runs

You choose on the run form where each step runs: its own class list offers the platform's machines and, when your
project has them, the classes of HPC (Slurm). Every step of your pipeline has this choice, not only GPU steps. The
step's code is the same in both places.

| | the platform's machines | HPC (Slurm) |
| --- | --- | --- |
| which steps | every step | every step you write, when your project has HPC classes |
| inputs | the step downloads each pinned version once | the platform copies each pinned version next to the job before it starts, and `step.input()` reads that copy |
| time | `walltime=` does not apply | `walltime=` sets the longest run, and the job waits in a queue first |
| interruption | a lost machine: the step runs again, or continues from its checkpoint | the time limit: the step is told to save, and continues from its checkpoint |
| MLflow, outputs and the result | the same calls | the same calls |

Nothing in your step names a place. [Long runs](checkpoint.md) explains continuing after an interruption.

## Work on a step on your own machine

| you want to | command |
| --- | --- |
| give each step its own Python environment | `kaosctl dev` ([Set up your steps](dev.md)) |
| run one step the way the platform starts it | `kaosctl step run <step>` ([Run a step locally](step-run.md)) |
| render `pipeline.py` as the platform does | `kaosctl render` ([Render locally](render.md)) |
| check the pipeline for mistakes | `kaosctl lint` ([Check your pipeline](lint.md)) |
| build a step's image | `kaosctl build <step>` ([Build a step image](build.md)) |

Next: [The step API](step.md).
