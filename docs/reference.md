# Reference

Terse and complete. The generated pages: [Commands](generated/cli.md), [Python API](api.md), [Lint checks](lint.md).

## Step API: `kaos_lib.step`

Every failure is a `kaos_lib.errors.StepError`; the step fails and hands no result on.

The calls, what each gives you, what you must do and what happens if you do not are in
[What a step receives and must return](contract.md#what-a-step-receives-and-must-return). The signatures are on the
[cheat sheet](cheat-sheet.md#the-step-api-from-kaos_lib-import-step) and the [Python API](api.md).

`step.input(name)` takes `name` from `inputs=`, or from `produces=` of a step in `needs=`: a dataset, a model or an
artifact. A step never reads another dataset: reading one by name in code is refused.

### Test a step: `kaos_lib.testing.running(tmp_path, **kwargs)`

| argument | meaning | the step reads it with |
|---|---|---|
| `kind`, `name`, `app`, `experiment` | the step's own fields; defaults `train`, `step`, `app`, `test` | `step.start()` |
| `params` | what `step.start().params` holds, for example `{"prepare": {"min_bytes": 1}}` | `step.start().params` |
| `inputs` | input name to a folder | `step.input("dataset")` |
| `upstream` | step name to the values it handed on, or `None` for a step that did not run | `step.upstream("prepare").values` |
| `upstream_skipped` | step name to the reason that step gave to `step.skip()` | `step.skipped("prepare")`, `step.upstream("prepare", optional=True)` |
| `upstream_writes` | step name to `{output name: folder}`, or `{output name: {"folder": ..., "type": "model" or "artifact" or "dataset", "commit": ...}}` | `step.input("clean")` |
| `upstream_reads` | step name to `{input name: "repository@version"}` or `{"repo": ..., "ref": ..., "commit": ...}` | `step.upstream("prepare").reads` |
| `upstream_matrix` | the name of a step with `matrix=` to the list of its items, in index order: `{"matrix": {"lr": 0.01}, "values": {...}, "writes": {...}, "reads": {...}, "status": "ok" or "failed" or "skipped", "reason": "..."}`, every part optional | `step.upstream("train")`, `step.input("model", item=0)` |
| `matrix`, `matrix_index`, `matrix_of` | the values of the step's own item (`{"lr": 0.01}`), its number from 0, and the number of items (default: the number plus one) | `step.start().params["lr"]`, `step.start().matrix` |
| `produces` | list of `("model" or "artifact" or "dataset", name)`, the outputs the step declares | `step.output("clean")`; `run.output("model", item=2)` for an item |

It yields a run: `run.result` (what the step handed on, or `None`) and `run.output(name)` (the folder it saved).

### The result

`{"version": 1, "status": "ok", "values": {...}, "reads": [...], "writes": [...]}`. A step that ended itself with `step.skip(reason)` has `{"version": 1, "status": "skipped", "reason": "..."}` instead. `reads` names every declared input,
opened or not, and each dataset of an earlier step that the step read: `name`, `repo`, `ref`, `commit`. `writes` names
every output: `name`, `type`, `repo`, `commit`.

## `pipeline.py`

`from kubecore.authoring import artifact, dataset, model, pipeline, step` gives `pipeline(name)` and
`step(name, *, kind, reads, inputs, needs, produces, gpu, when, walltime, resumable, checkpoint_every, idle_timeout, matrix, matrix_allow_failed)`.

| keyword | meaning | the platform refuses |
|---|---|---|
| `name` | lowercase letters, digits, hyphens | a name over the limit or one that is kept ([the limits](contract.md#the-limits)); a name starting with `kaos-`; a repeated name |
| `kind=` | `ingest`, `transform`, `train`, `evaluate`, `publish` or `control`. Required. Each kind has a contract: [Step types](step-types.md) | a missing or unknown kind; a step that breaks its kind's contract |
| `reads=` | sections of `config/` the step gets in `params` | a section that is not in `config/` |
| `inputs=` | top-level `config/` values (text) that hold a dataset reference | a name that is not in `config/` or not text; a name that starts with `kaos-`; `control` steps |
| `needs=` | earlier steps (the variables) | more steps than the limit; a step defined below; an input and a needed output of one name; two needed steps producing one name; more readable datasets than the limit |
| `produces=` | `model("n")`, `artifact("n")`, `dataset("n")` | a dataset with two producing steps; `dataset(n, of=...)`; a type that may not produce what is listed ([Step types](step-types.md)) |
| `gpu=True` | the step is offered the GPU classes. On the platform's own machines it gets the GPU of its class; on HPC (Slurm) it gets one GPU when node sharing is on, and the whole node's GPUs when it is off ([GPUs on HPC (Slurm)](gpus-on-hpc.md)) | |
| `when="..."` | a name compared with a text, written `"<name> == text"` or with `!=`. The name is a field of the run form (`"mode != off"`) or a value of a step in `needs=` (`"evaluate.passed == true"`: the keyword of that step's `step.result(passed=...)`). Join comparisons with `and` / `or` (`and` first, no parentheses, no `<` or `>`); a text with spaces is quoted. A value that was never set stops the run, and a value of a skipped step makes the condition false ([Conditions and skipping](conditions-and-skipping.md)) | a `when=` that is not written that way; a field the run form does not have; a value of a step that is not in `needs=` |
| `walltime=` | the longest the step may run, wherever it runs: `"90m"`, `"12h"`, `"720"` (minutes). It is the default of the run-form field `<step>-walltime` ([the limits](contract.md#the-limits)) | a wrong form |
| `resumable=` | `True` (stop signal 10 minutes before the limit), a lead time `"20m"`, or `False` | a wrong form |
| `checkpoint_every=` | how often the platform copies the checkpoint your step saved: `"20m"`, `"1h"`, `20`, `False`; GPU steps default to ten minutes. It is the default of the run-form field `<step>-checkpoint-every` (a `resumable=True` step has the field too, with ten minutes as the default), and the form value wins over `register(checkpoint_every=...)` in code ([the table](long-jobs.md#the-time-limit)). On HPC (Slurm) copies are at least five minutes apart | a wrong form |
| `idle_timeout=` | minutes without GPU use and log lines before a GPU step ends as idle: `"40m"`, `40`, `0` for never; the default is in [the limits](contract.md#the-limits) | a wrong form |
| `matrix=` | values to try, `{"lr": [0.01, 0.001], "batch": [16, 32]}`: the step runs once for each combination, at most 32; it reads a value as `params["lr"]`, and the step after it gets a list ([Sweeps](sweeps.md)). It is the default of the run-form field `<step>-matrix` | not a dictionary of non-empty lists; a name that is not `[a-z][a-z0-9_]*` or is also a section in `reads=`; a value that is not a number, a boolean or a short text; more than 32 combinations; the kinds `ingest`, `publish`, `control`; a dataset in `produces=`; a whole number beyond 2^53; more than 4 things in `inputs=` and `produces=` together; a step that needs a step with `matrix=`, two of them, or more than 4 steps in all when one has `matrix=`; a `when=` that reads a value of a step with `matrix=`. The limits are in [Sweeps](sweeps.md#limits) |
| `matrix_allow_failed=` | `True` on a step with `matrix=`: the step after it runs when some items failed and sees which ([Sweeps](sweeps.md#pick-the-best)) | not `True` or `False`; without `matrix=` |

Refused at render, as well: `outputs=`, `hpc_time_limit=` and `disk=`; a step that produces a dataset and is pinned to
a Slurm class; a `plan` or `pipeline-version` in `config/`; a step definition over 24 KiB; an app name over the limit;
a copy of the platform's pipeline code in the app; the `platform` group in `config/config.yaml`. An app from before the current pipelines
is created again from the template.

## What `produces=` makes, and dataset references

What a step makes and where it is kept are in [What a step writes](data-writes.md#what-a-step-writes). The forms of an
address, such as `dataset-<name>@v1`, are in [Names and addresses](data-contract.md#names-and-addresses).

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
| `kaosctl render --engine-wheel 'URL#sha256=...'` (or `--context FILE`) | renders `pipeline.py`, as the check on a pull request does. It needs the platform's engine release, which your platform team gives you: without one, the check of your pull request renders it for you |
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
| its machine was lost (reclaimed, failed, drained) | continues from the newest good copy | runs again from the start, as often as the limit allows ([the limits](contract.md#the-limits)) |
| the time limit was reached, on the platform's own machines or on HPC ([Long jobs](long-jobs.md#the-time-limit)) | continues in a new run | ends |
| a GPU step showed no GPU use and no new log line for the idle time ([the limits](contract.md#the-limits)) | ends as idle, and is not run again | ends as idle |
| your code failed (non-zero exit) | ends as failed | ends as failed |

A copy is used only after the platform verified it.

## Versions and upgrades

Keep the line `ARG KAOS_LIB_PACKAGE` in each step's `Dockerfile`: the platform builds your images with the kaos-lib version
it chooses by replacing its value. `.kaos/compat.yaml` holds the range of versions your code works with, for example
`kaos-lib: ">=0.5.0rc1,<0.6"`. `kaosctl --version` shows your version and the one your platform recommends, and
`kaosctl upgrade` installs it.
