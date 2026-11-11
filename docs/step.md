# The step API (`kaos_lib.step`)

Six calls are everything a step needs from the platform.

```python
from kaos_lib import step

ctx = step.start()                 # first: the run, the app, the step and the config (ctx.params)
data = step.input("raw")           # a folder: what the run pinned for the input "raw"
prev = step.upstream("prepare")    # an earlier step's result: prev.values
out = step.output("report")        # a folder to write into
step.check("report", min_files=1)  # a condition the output must meet before it is saved
step.result(rows=1200)             # last: save the outputs, hand the result on
```

A complete step:

```python
"""count-files: count the files of the run's dataset and hand the count on."""
from kaos_lib import step


def main() -> None:
    ctx = step.start()
    data = step.input("dataset")
    files = sum(1 for p in data.rglob("*") if p.is_file())
    report = step.output("report")
    (report / "count.txt").write_text(f"{files} files, experiment {ctx.experiment}\n")
    step.result(files=files)


if __name__ == "__main__":
    main()
```

with this line in `pipeline.py`:

```python
step("count-files", kind="evaluate", reads=["experiment"], inputs=["dataset"], produces=[artifact("report")])
```

## `step.start()`

Call it once, before anything else. It returns the step:

| field | what it is |
| --- | --- |
| `params` | your composed `config/` for this run, a dictionary |
| `run` | the run's name, the same in every step of the run |
| `app`, `project` | your app and its project |
| `step`, `kind` | this step's name and its kind |
| `experiment` | the experiment the run belongs to |
| `produces` | what this step declared in `produces=` |

A second call returns the same step. Outside a pipeline run it raises: start the step with
[`kaosctl step run`](step-run.md) to try it on your machine.

## `step.input(name)`

Returns a folder (`pathlib.Path`). `name` is one of two things, and nothing else:

| the name is | you get |
| --- | --- |
| in the step's `inputs=` | the dataset version the run pinned for that setting |
| a dataset, model or artifact that a step in `needs=` produced | what that step wrote in this run |

- It takes a name and nothing else. There is no version argument: the version was chosen when the run was
  submitted (on the run form, or the default in `config/`) and reached the step as one exact version.
- The files are downloaded once and kept; a second call, or a second step on the same machine, downloads
  nothing. On HPC (Slurm) the platform copies each input next to the job before it starts, and `input()` returns
  that copy.
- For a dataset with the `yolo` layout the folder holds a `data.yaml` whose `path:` points at the files; use
  `step.input("dataset") / "data.yaml"`.
- Never write into the folder. Copy what you change into an output.
- A dataset with no files yet raises `kaos_lib.errors.EmptyDataset`.

## `step.upstream(step_name, required=True)`

Returns the result of a step named in `needs=`:

```python
prev = step.upstream("train")
prev.values["accuracy"]        # what that step passed to step.result(...)
prev.reads, prev.writes        # the dataset versions it read, and what it wrote
```

A step that was skipped (its `when=` was false) left no result. Asking for it raises, naming the step, so a
missing result can never pass as an empty one. A step that can work without it asks so:

```python
export = step.upstream("export", required=False)     # None when "export" did not run
```

## `step.output(name)`

Returns an empty local folder for something the step declared in `produces=`. Write files into it. Nothing is
saved until `step.result()`; every declared output must hold at least one file by then.

| declared as | saved as |
| --- | --- |
| `model("name")`, `artifact("name")` | the files of this run, in your app's outputs repository under `<name>/<experiment>/<run>/` |
| `dataset("name")` | a new version of the dataset `name` |

[Results](results.md) says where each ends up and how a later step or run reads it.

## `step.check(name, layout=None, min_files=1)`

Sets a condition on an output. It is checked inside `step.result()`, before anything is saved; when it fails,
nothing is saved and the step fails with every problem listed.

- `min_files`: the least number of files the output must hold.
- `layout`: the name of a [dataset layout](make-your-own-layout.md) (`"yolo"`, `"raw"`, one of your project's)
  whose rules the folder must pass.

For any other condition, raise an error in your code before `step.result()`.

## `step.result(**values)`

The last call of every step. It checks the outputs, saves each one, and hands the result on.

- `values` are small JSON values (text, numbers, booleans, lists, dictionaries) for the steps that need this
  one. They are also shown on the run page.
- A result holds a few kilobytes: its limit is 8 KiB. Log metrics to MLflow, and write anything larger into an
  artifact and hand on its name.
- Call it exactly once. A step with nothing to hand on calls `step.result()`.
- A step that ends without it fails, even with exit code 0: otherwise the next step would start with nothing.

## What goes wrong, and what the message says

Every failure is a `kaos_lib.errors.StepError` with one message that says what to change. The step fails and
hands nothing on.

| when | message starts with |
| --- | --- |
| the step is started outside a pipeline run | `this is not a pipeline step` |
| another call comes before `start()` | `call step.start() first` |
| `input()` of a name that is neither an input nor produced by a needed step | `'<name>' is not an input of step '<step>'. Its inputs are: ...` |
| code asks for a dataset the run did not pin | `<dataset> is not an input of step '<step>'` |
| the pinned version was deleted | `input '<name>': commit ... does not exist any more` |
| `upstream()` of a step that is not in `needs=` | `step '<x>' is not upstream of '<step>'` |
| `upstream()` of a step that left no result | `step '<x>' wrote no result` |
| `output()` of a name that is not in `produces=` | `'<name>' is not produced by step '<step>'. It produces: ...` |
| an output is declared and was never written | `output '<name>' was not written`, `output '<name>' is empty` |
| a `check()` fails | `output '<name>' failed its check:` |
| a value is not JSON | `result value '<key>' is a <type>` |
| the result is too large | `the result costs ...; the limit is 8192` |
| `result()` is called twice | `step.result() was already called` |
| the step may not write a repository | `this app may not write <repository>` |
| the step ends without `result()` | `step '<step>' ended without step.result()` |

## Tracking and long runs

`kaos_lib.step` does not replace the rest of kaos-lib:

- [MLflow](mlflow.md): `kaos_lib.mlflow.mlflow()` signs in for you. What the step read and wrote is recorded on
  its MLflow run automatically.
- [Long runs on HPC (Slurm)](checkpoint.md): `kaos_lib.checkpoint` saves and restores the step's state. A step
  that is ended to be continued (exit code 85) has no result yet, and that is not a failure.
- [Progress](progress.md): `kaos_lib.progress.report(done, total)`.
- [Run context](runtime.md): `kaos_lib.runtime.usable_cpus()` and the step's share of a shared HPC node.
