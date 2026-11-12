# Reference

Terse and complete. The generated pages: [Commands](generated/cli.md), [Python API](api.md), [Lint checks](lint.md).

## Step API: `kaos_lib.step`

Every failure is a `kaos_lib.errors.StepError`; the step fails and hands no result on.

| call | returns | fails when |
|---|---|---|
| `start()` | the step: `run`, `app`, `project`, `step`, `kind`, `experiment`, `params`, `produces` | outside a run: `ERROR: this is not a pipeline step`; a context that cannot be read: `ERROR: the step context ...` (one line, exit code 1) |
| `input(name, optional=False, writable=False)` | a folder (`pathlib.Path`), read-only | `'<name>' is not an input of step '<step>'. Its inputs are: ...`; `input '<name>' of step '<step>' is not there, and <x> did not run`; `input '<name>': commit ... does not exist any more`; `input '<name>': <dataset> holds no files at the version this run read`. `optional=True` returns `None` for a step that did not run. `writable=True` returns a private full copy |
| `upstream(step, optional=False)` | `Upstream`: `values`, `reads`, `writes` | `step '<x>' is not upstream of '<step>'`; `step '<x>' did not run, so it left no result`. `optional=True` returns `None` |
| `output(name)` | an empty folder, emptied the first time it is asked for in an attempt | `'<name>' is not produced by step '<step>'. It produces: ...`; the folder is a link |
| `workdir()` | a scratch folder, emptied at each attempt, never saved | |
| `check(name, layout=None, min_files=1)` | nothing; checked inside `result()` | `output '<name>' failed its check:` |
| `result(**values)` | nothing; saves every output, then writes the result. Call it once, last | `output '<name>' was not written`; `output '<name>' is empty`; `output '<name>' holds a file in .kaos/`; `result value '<key>' is a <type>`; names starting with `kaos-`; `the result costs ...; the limit is 8192`; `step.result() was already called`; `this app may not write <repository>` |

Other failures: a call before `start()` is `call step.start() first`; a step that ends without `result()` fails with
`step '<step>' ended without step.result()`, whatever its exit code; a step that has an input and an output of one name
fails in `start()`.

`step.input(name)` takes `name` from `inputs=`, or from `produces=` of a step in `needs=`: a dataset, a model or an
artifact. A step never reads another dataset: reading one by name in code is refused.

### Test a step: `kaos_lib.testing.running(tmp_path, **kwargs)`

| argument | meaning | the step reads it with |
|---|---|---|
| `kind`, `name`, `app`, `experiment` | the step's own fields; defaults `train`, `step`, `app`, `test` | `step.start()` |
| `params` | what `step.start().params` holds, for example `{"prepare": {"min_bytes": 1}}` | `step.start().params` |
| `inputs` | input name to a folder | `step.input("dataset")` |
| `upstream` | step name to the values it handed on, or `None` for a step that did not run | `step.upstream("prepare").values` |
| `upstream_writes` | step name to `{output name: folder}`, or `{output name: {"folder": ..., "type": "model" or "artifact" or "dataset", "commit": ...}}` | `step.input("clean")` |
| `upstream_reads` | step name to `{input name: "repository@version"}` or `{"repo": ..., "ref": ..., "commit": ...}` | `step.upstream("prepare").reads` |
| `produces` | list of `("model" or "artifact" or "dataset", name)`, the outputs the step declares | `step.output("clean")` |

It yields a run: `run.result` (what the step handed on, or `None`) and `run.output(name)` (the folder it saved).

### The result

`{"version": 1, "status": "ok", "values": {...}, "reads": [...], "writes": [...]}`. `reads` names every declared input,
opened or not, and each dataset of an earlier step that the step read: `name`, `repo`, `ref`, `commit`. `writes` names
every output: `name`, `type`, `repo`, `commit`.

## `pipeline.py`

`from kubecore.authoring import artifact, dataset, model, pipeline, step` gives `pipeline(name)` and
`step(name, *, kind, reads, inputs, needs, produces, gpu, when, walltime, resumable, checkpoint_every, idle_timeout)`.

| keyword | meaning | the platform refuses |
|---|---|---|
| `name` | lowercase letters, digits, hyphens | a name over the limit or one that is kept ([the limits](must-and-can.md#the-limits)); a name starting with `kaos-`; a repeated name |
| `kind=` | `ingest`, `transform`, `train`, `evaluate`, `publish` or `control`. Required | a missing or unknown kind |
| `reads=` | sections of `config/` the step gets in `params` | a section that is not in `config/` |
| `inputs=` | top-level `config/` values (text) that hold a dataset reference | a name that is not in `config/` or not text; a name that starts with `kaos-`; `control` steps |
| `needs=` | earlier steps (the variables) | more steps than the limit; a step defined below; an input and a needed output of one name; two needed steps producing one name; more readable datasets than the limit |
| `produces=` | `model("n")`, `artifact("n")`, `dataset("n")` | a dataset with two producing steps; `dataset(n, of=...)`; `control` steps |
| `gpu=True` | one GPU | |
| `when="..."` | a condition on the value of a run-form field `<field>`, written `"{{workflow.parameters.<field>}} == value"` or with `!=` | |
| `walltime=` | the run limit on a Slurm class: `"90m"`, `"12h"`, `"720"` (minutes); without it the default of [the limits](must-and-can.md#the-limits) | a wrong form; `ingest`, `publish`, `control` steps |
| `resumable=` | `True` (stop signal 10 minutes before the limit), a lead time `"20m"`, or `False` | a wrong form |
| `checkpoint_every=` | how often the platform copies the checkpoint folder: `"20m"`, `"1h"`, `20`, `False`; GPU steps default to ten minutes | a wrong form |
| `idle_timeout=` | minutes without GPU use and log lines before a GPU step ends as idle: `"40m"`, `40`, `0` for never; the default is in [the limits](must-and-can.md#the-limits) | a wrong form |

Refused at render, as well: `outputs=`, `hpc_time_limit=` and `disk=`; a step that produces a dataset and is pinned to
a Slurm class; a `plan` or `pipeline-version` in `config/`; a step definition over 24 KiB; an app name over the limit;
a copy of the platform's pipeline code in the app; the `platform` group in `config/config.yaml`. An app from before the current pipelines
is created again from the template.

## What `produces=` makes

| declared as | what it is | where it is kept |
|---|---|---|
| `artifact("name")` | files of one run: a report, plots, a table | the repository `outputs-<app>`, under `<name>/<experiment>/<run>/` |
| `model("name")` | files of one run: weights | the same place |
| `dataset("name")` | a version of a dataset | the dataset `dataset-<app>-<name>` ([page 6](produce-a-dataset.md)) |

## Dataset references

| form | meaning |
|---|---|
| `dataset-<name>` | the same as `@latest` |
| `dataset-<name>@v1` | a named version |
| `dataset-<name>@latest` | the version the name `latest` points to ([Datasets, versions and hashes](datasets-versions-hashes.md#what-a-version-is)) |
| `dataset-<name>@<commit>` | a commit |
| `dataset-<app>-<name>` | a dataset the app `<app>` produces with `dataset("<name>")` |
| `<owner>/dataset-<name>@<version>` | a dataset another project shares with yours (read-only) |

`kaosctl dataset pull` also takes `<repository>@<branch or tag>`. `latest` of a produced dataset moves only when the run
asks ([Move `latest`](flow-datasets.md#move-latest)).

## Run tools

| call | does |
|---|---|
| `checkpoint.dir()`, `load(name="state", default=None)`, `save(obj, name="state")`, `progress(n)`, `stop_requested()`, `exit_for_restart()` | [Long jobs](long-jobs.md); exit code 85 means saved, run again |
| the hooks for Ultralytics, PyTorch Lightning and Hugging Face | importing `kaos_lib` attaches them. The environment variable `KAOS_CHECKPOINT_HOOKS=0` turns them off |
| `progress.report(done, total=None, unit="step")` | one line the run page reads from the log, at most one every ten seconds; never fails |
| `mlflow.mlflow(tracking_uri=None, token=None)` | signs the step in to the project's MLflow and returns an `MlflowClient` |
| `runtime.usable_cpus()`, `runtime.context()`, `runtime.run_id()` | the cores the step may use (its share of a shared Slurm node); where the step runs |
| `datasets.list_datasets()`, `versions(repo)`, `release(repo)` | the datasets you can read, their versions, a new version, outside a step |

## Dataset layouts

A layout says what a dataset holds: the files `create` starts it with, the rules `validate` and `push` check, and what a
pull downloads.

| layout | holds | checked |
|---|---|---|
| `raw` | any files | nothing |
| `yolo` | images, one `.txt` label file per image, and a `data.yaml` with the splits and class names | detection, segmentation and pose label formats |

`kaosctl layout list` shows the built-in layouts and your project's. A dataset without a layout is `raw`.

To make a layout of your own, see [Make a dataset layout](make-a-layout.md).

## Commands

Every option is on the [generated commands page](generated/cli.md).

| command | does |
|---|---|
| `kaosctl login` | signs you in through the browser, inside your app folder |
| `kaosctl dataset create <name> [--layout L] [--classes a,b]` | a new dataset |
| `kaosctl dataset push <dir> <repo> -m "message"` | uploads a folder and opens a pull request |
| `kaosctl dataset release <repo>` | gives the version `latest` points to the next version number |
| `kaosctl dataset pull <repo>@<ref> [dest] [--prefix folder/]` | downloads a version |
| `kaosctl dataset list [--shared]`, `versions <repo>`, `validate <dir>` | lists, lists versions, checks a folder |
| `kaosctl layout list`, `show`, `init`, `validate`, `publish` | dataset layouts (above) |
| `kaosctl lint` | checks `pipeline.py` ([Lint checks](lint.md)) |
| `kaosctl dev` | a Python environment for each step |
| `kaosctl step run <step>` | runs a step on your machine ([page 10](try-it-locally.md), [flags](#kaosctl-step-run)) |
| `kaosctl render --context FILE` | renders `pipeline.py`, as the check on a pull request does |
| `kaosctl build [step]` | builds a step's image with your container engine |
| `kaosctl run --lock <mlflow run> -- <command>` | runs a command on the data a past run read |
| `kaosctl upgrade [--dry-run]`, `kaosctl vscode install`, `kaosctl --version` | version and editor tools |

Exit codes and error messages: [When something goes wrong](when-something-goes-wrong.md#datasets-and-commands).

### `kaosctl step run`

| flag | does |
|---|---|
| `--params-file FILE` | the settings the step reads: a section for each config file, with the values you want |
| `--context FILE` | a context file of your project that the platform keeps; you do not make it yourself. Without `--params-file` the settings need it |
| `--input NAME=FOLDER` | gives an input a folder as it is. Folders alone work offline |
| `--input NAME=dataset-x@v1` | downloads a small sample of that version with your own sign-in; `--sample-mb` sets the most |
| `--python INTERPRETER` | runs the step with a Python you already have, for a step with heavy dependencies; a relative path is taken from the folder you run the command in |

A step that needs an earlier step finds that step's last local result. Nothing is uploaded: outputs stay in
`.kaos/local/staged/<name>/` and results in `.kaos/local/results/`, and the version shown for them is a fingerprint of the
content: the same files give the same one. The step runs with a short list of your environment variables, and the
addresses and tokens the platform gives a running step are not passed, even if your shell has them.

## When a step ends

| the step ended because | with a checkpoint | without one |
|---|---|---|
| its machine was lost (reclaimed, failed, drained) | continues from the newest good copy | runs again from the start, as often as the limit allows ([the limits](must-and-can.md#the-limits)) |
| the time limit of a Slurm job was reached ([page 9](hpc.md)) | continues in a new job | ends |
| a GPU step showed no GPU use and no new log line for the idle time ([the limits](must-and-can.md#the-limits)) | ends as idle, and is not run again | ends as idle |
| your code failed (non-zero exit) | ends as failed | ends as failed |

A copy is used only after the platform verified it.

## Versions and upgrades

Keep the line `ARG KAOS_LIB_PACKAGE` in each step's `Dockerfile`: the platform builds your images with the kaos-lib version
it chooses by replacing its value. `.kaos/compat.yaml` holds the range of versions your code works with, for example
`kaos-lib: ">=0.5.0rc1,<0.6"`. `kaosctl --version` shows your version and the one your platform recommends, and
`kaosctl upgrade` installs it.
