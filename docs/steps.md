# How a step works

A pipeline is a list of steps. Each step is a small program that you write. The platform starts it, gives it its
inputs, collects its results and decides where it runs. This page is the whole contract between a step and the
platform. [Step examples](step-examples.md) shows one complete step for every common job, and
[How steps use datasets](steps-and-datasets.md) explains how a run reads its data.

## What your app holds

| you write | what it is |
| --- | --- |
| `pipeline.py` | the steps and their order |
| `config/` | every setting of a run, with its default |
| `steps/<name>/app/entry.py` | the code of one step, and anything else it imports from `steps/<name>/app/` |
| `steps/<name>/Dockerfile` | the step's image: Python, kaos-lib and your libraries |

The platform owns everything else: how a run is started, how steps are connected, where they run, and how their
settings and data reach them. You never copy platform files into your app.

A step's name is its folder name with `-` instead of `_`: the step `data-check` lives in `steps/data_check/`.

## What you declare

You declare a step with one line in `pipeline.py`:

```python
from kubecore.authoring import pipeline, step

with pipeline("ml-pipeline") as p:
    check = step("data-check", reads=["dataset"], outputs=["data-stats"])
    train = step("train", gpu=True, needs=[check], reads=["experiment", "dataset", "train"],
                 outputs=["training-result"])
```

| option | meaning |
| --- | --- |
| `name` | lowercase letters, digits and `-`, no `-` at the start or end. Unique in the pipeline. |
| `reads=[...]` | the top-level sections of `config/` that the step uses. A name that is not in `config/` fails the check. |
| `needs=[...]` | steps that must finish first. Define a step above the steps that need it. Their outputs reach this step as arguments. |
| `outputs=[...]` | the names of the small JSON results the step writes. |
| `gpu=True` | the step gets one GPU. |
| `when="..."` | a condition on a run-form value. When it is false the step is skipped. See [conditional steps](step-examples.md#8-a-conditional-step). |
| `disk="20Gi"` | more scratch disk than the default, as a size: digits and an optional unit (`Ki`, `Mi`, `Gi`, `Ti`, `K`, `M`, `G`, `T`). Use it for big datasets or big temporary files. |
| `hpc_time_limit="12h"` | the longest this GPU step may run on HPC (Slurm): minutes or hours, such as `"90m"`, `"12h"` or `"720"`. Only with `gpu=True`. |
| `resumable=` | GPU steps only. `True`, or a lead time such as `"20m"`: how long before the time limit the step is told to save. `False` turns continuing off. See [Long runs](checkpoint.md). |
| `checkpoint_every=` | how often the platform copies the step's checkpoint folder: `"20m"`, `"1h"`, `20` (minutes), or `False` for never. |
| `idle_timeout=` | how long a step may show no GPU use and no new log line before it is ended: `"40m"`, `"1h"`, `40`, or `0` for never. |

[Check your pipeline](lint.md) (`kaosctl lint`) reads `pipeline.py` and tells you about mistakes before you push.

## What a step receives

The platform starts every step the same way:

```text
python -m app.entry --params <the composed config as YAML text> --<output-name> <json> ...
```

| argument | what it holds |
| --- | --- |
| `--params` | your whole `config/` for this run, with the values from the run form, as YAML **text** (not a file name). Read it with `yaml.safe_load`. |
| `--<name>` | one for every output of every step in `needs=`: the JSON that step wrote. It is `{}` when that step was skipped or wrote nothing. |

A step reads both with the standard library and PyYAML:

```python
import argparse, json
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("--params", required=True)
parser.add_argument("--training-result", default="{}")      # an output of a step in needs=
args, _ = parser.parse_known_args()                          # ignores the outputs you do not use
cfg = yaml.safe_load(args.params)
result = json.loads(args.training_result)
```

The platform also puts these in the step's environment. Read them with `kaos_lib.runtime.context()`
([Run context](runtime.md)), not by hand:

| what | where it shows |
| --- | --- |
| the run id | `context().run_id` |
| your results repository | `context().outputs_repo` (`outputs-<app>`) |
| the lakeFS address and your app's access to it | read by `kaos_lib.datasets` and `kaos_lib.outputs` for you |
| the MLflow address and sign-in | used by `kaos_lib.mlflow.mlflow()` for you ([MLflow](mlflow.md)) |
| the folder for checkpoints | `kaos_lib.checkpoint.dir()` ([Long runs](checkpoint.md)) |
| the run's data lock | read by `kaos_lib.datasets` for you ([Data lock](data-lock.md)) |

Take the dataset from `--params`, not from the run context: the platform does not fill `context().dataset_ref` in
every step.

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

| what | where | how big |
| --- | --- | --- |
| a small result for the next step | `/work/output/<name>.json`, one file for each name in `outputs=` | a few kilobytes: it travels as an argument |
| models and files | your outputs repository, with `kaos_lib.outputs` ([Outputs](outputs.md)) | any size |
| metrics, parameters, the model registry | MLflow ([MLflow](mlflow.md)) | any size |
| how far the step is | one line in the log, with `kaos_lib.progress` ([Progress](progress.md)) | |
| the state of a long run | the checkpoint folder, with `kaos_lib.checkpoint` ([Long runs](checkpoint.md)) | |

Create the folder first: `Path("/work/output").mkdir(parents=True, exist_ok=True)`. A name in `outputs=` with no file
becomes `{}`.

A step that ends with a non-zero exit code has failed. Exit code `85` means "I saved my state, run me again": see
[Long runs](checkpoint.md).

## How a step uses datasets

The run's dataset is the setting `dataset: "<dataset>@<version>"`. For a dataset of another project it is
`<owner-project>/<dataset>@<version>`. The platform turns it into one exact commit before any step starts. Every step
that reads it gets that commit.

```python
from kaos_lib import datasets

ref = datasets.DatasetRef.parse(cfg["dataset"])
data = datasets.materialize(ref)          # the files of the run's commit
commit = datasets.resolve(ref)            # the commit itself, to record in your results
```

A step that lists `dataset` in `reads=` is covered. [How steps use datasets](steps-and-datasets.md) has the details.

## What the platform does for you

| the platform... | so you do not have to |
| --- | --- |
| composes and checks your settings before any step runs | check them in every step |
| reads your dataset choice once, as one commit, and gives it to every step | pin or compare dataset versions |
| runs steps in the order of `needs=`, and passes their outputs on | wire steps together |
| skips a step whose `when=` is false, and still runs the steps after it | handle a missing step |
| gives every step its run id, results repository, MLflow sign-in and data access | handle passwords and addresses |
| copies the checkpoint folder of a GPU step and puts it back when the step is continued | save your state somewhere |
| runs the step again after a node failure or a reclaimed machine | retry |
| shows the step's progress and logs | build a dashboard |

## What you must never do

| never | why | instead |
| --- | --- | --- |
| choose or pin the dataset version yourself: no `latest`, no `versions()[-1]`, no copy of a version in your code | two steps could read different data | `materialize(DatasetRef.parse(cfg["dataset"]))` |
| read a password or a token from `config/` | settings are shown on the run form and stored with the run | the platform's sign-in, used by kaos-lib |
| print or log a credential | logs are kept | log what you computed |
| write results anywhere but `/work/output` and your outputs repository | the step's disk is gone when it ends | [Outputs](outputs.md) |
| write into a dataset or into another app's outputs repository | a step's access does not allow it, so the step fails | write to your outputs repository |
| write into the folder that `materialize` returns | it is a shared, read-only copy on HPC (Slurm), and a cache elsewhere | copy the files you change |

## Where a step runs

You choose on the run form where each step runs: its own class list offers the platform's machines and, when your
project has them, the classes of HPC (Slurm). Every step of your pipeline has this choice, not only GPU steps. The step's code is the same in both places.

| | the platform's machines | HPC (Slurm) |
| --- | --- | --- |
| which steps | every step | every step you write, when your project has HPC classes |
| dataset | the step downloads the run's commit | the platform copies the run's commit next to the job before it starts, and kaos-lib reads that copy |
| time | `hpc_time_limit=` does not apply | `hpc_time_limit=` sets the longest run, and the job waits in a queue first |
| interruption | a lost machine: the step runs again, or continues from its checkpoint | the time limit: the step is told to save, and continues from its checkpoint |
| MLflow and results repository | the same calls | the same calls |

Nothing in your step names a place. [Long runs](checkpoint.md) explains continuing after an interruption.

## Work on a step on your own machine

| you want to | command |
| --- | --- |
| give each step its own Python environment | `kaosctl dev` ([Set up your steps](dev.md)) |
| run one step the way the platform starts it | `kaosctl step run <step>` ([Run a step locally](step-run.md)) |
| render `pipeline.py` as the platform does | `kaosctl render` ([Render locally](render.md)) |
| check the pipeline for mistakes | `kaosctl lint` ([Check your pipeline](lint.md)) |
| build a step's image | `kaosctl build <step>` ([Build a step image](build.md)) |

Next: [Step examples](step-examples.md).
