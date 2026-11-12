# The step API (`kaos_lib.step`)

Seven calls are everything a step needs from the platform.

```python
from kaos_lib import step

ctx = step.start()                 # first: the run, the app, the step and the config (ctx.params)
data = step.input("raw")           # a folder: what the run pinned for the input "raw"
prev = step.upstream("prepare")    # an earlier step's result: prev.values
out = step.output("report")        # a folder to write into
scratch = step.workdir()           # a folder for tool caches and run folders: not an input, never saved
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
| `params` | the sections of your composed `config/` that the step names in `reads=`, a dictionary |
| `run` | the run's name, the same in every step of the run |
| `app`, `project` | your app and its project |
| `step`, `kind` | this step's name and its kind |
| `experiment` | the experiment the run belongs to |
| `produces` | what this step declared in `produces=` |

A second call returns the same step. When the step cannot start (it was not started by the platform, or what
the platform handed it cannot be read), the process ends with one line that names the cause and exit code 1.
To try a step on your machine, start it with [`kaosctl step run`](step-run.md).

## `step.input(name, optional=False)`

Returns a folder (`pathlib.Path`). `name` is one of two things, and nothing else:

| the name is | you get |
| --- | --- |
| in the step's `inputs=` | the dataset version the run pinned for that setting |
| a dataset, model or artifact that a step in `needs=` produced | what that step wrote in this run |

- The folder holds only the files of the dataset or of what the step before it wrote. Nothing of the platform's is in
  it, so `folder.rglob("*")` counts your files and a copy loop copies only them.
- It takes a name and nothing else. There is no version argument: the version was chosen when the run was
  submitted (on the run form, or the default in `config/`) and reached the step as one exact version.
- The files are downloaded once and kept; a second call, or a second step on the same machine, downloads
  nothing. On HPC (Slurm) the platform copies each input next to the job before it starts, and `input()` returns
  that copy.
- For a dataset with the `yolo` layout the folder holds a `data.yaml` whose `path:` points at the files; use
  `step.input("dataset") / "data.yaml"`.
- Never write into the folder. Copy what you change into an output. A tool that writes beside its input (label
  caches, an export next to the weights) gets `step.input("name", writable=True)`: a private full copy that you may
  write into. It costs the input's size in disk and time; it never changes the input and is never saved.
- When the name is missing because a step in `needs=` did not run (its `when=` was false), `input()` raises and
  names the input and the step. A step that can work without it asks with `step.input("name", optional=True)`
  and gets `None`.
- A dataset with no files yet raises `kaos_lib.errors.EmptyDataset`.

## `step.upstream(step_name, optional=False)`

Returns the result of a step named in `needs=`:

```python
prev = step.upstream("train")
prev.values["accuracy"]        # what that step passed to step.result(...)
prev.reads, prev.writes        # the dataset versions it read, and what it wrote
```

A step that did not run (its `when=` was false) left no result. Asking for it raises, naming the step, so a
missing result can never pass as an empty one. A step that can work without it asks so:

```python
export = step.upstream("export", optional=True)     # None when "export" did not run
```

## `step.output(name)`

Returns a local folder for something the step declared in `produces=`. It is empty each time the step starts, also
on a retry on the same machine, so it never holds a file of an earlier attempt. Write files into it, and only your
own: the platform keeps its records beside the folder, never in it. Nothing is saved until `step.result()`; every
declared output must hold at least one file by then. The name of an output must differ from the name of every input of the same step, and the folder must be a real folder, not a link: `step.start()` and `step.output()` refuse otherwise.

| declared as | saved as |
| --- | --- |
| `model("name")`, `artifact("name")` | the files of this run, in your app's outputs repository under `<name>/<experiment>/<run>/` |
| `dataset("name")` | a new version of the dataset `dataset-<app>-<name>`: exactly the files of the folder |

Names in `produces=` use lowercase letters, digits and hyphens, at most 40 characters. A dataset may not hold a
file in a folder called `.kaos/`: the platform keeps it for itself.

[Results](results.md) says where each ends up and how a later step or run reads it.

## `step.workdir()`

Returns a scratch folder for files that are neither an input nor an output, such as the run folders and caches of ML
tools. It is empty at each attempt and is never saved.

## `step.check(name, layout=None, min_files=1)`

Sets a condition on an output. It is checked inside `step.result()`, before anything is saved; when it fails,
nothing is saved and the step fails with every problem listed.

- `min_files`: the least number of files the output must hold.
- `layout`: the name of a [dataset layout](make-your-own-layout.md) (`"yolo"`, `"raw"`, one of your project's)
  whose rules the folder must pass.

For any other condition, raise an error in your code before `step.result()`.

## `step.result(**values)`

The last call of every step. It checks the outputs, saves each one, and hands the result on.

It works in order, so that a step that fails moves nothing that other pipelines read:

1. It checks everything it can without saving: the values, the size of the result, that every declared output
   was written, and your `check()`s.
2. It saves every output, but moves no dataset's `latest`.
3. Only when all of them are saved, it moves `latest` of the datasets the run asked to move
   (`plan: {promote: {<name>: true}}` in the run's advanced config).
4. It writes the result.

A step that fails in 1 or 2 leaves no new version that anyone reads by default. One case cannot be avoided: when a
step moves `latest` of two datasets, these are two separate changes, and the second can fail after the first
has happened. A retry of the step then finds the first already done and completes the second.

- `values` are small JSON values (text, numbers, booleans, lists, dictionaries) for the steps that need this
  one. They are also shown on the run page.
- A result holds a few kilobytes: its limit is 8 KiB. Log metrics to MLflow, and write anything larger into an
  artifact and hand on its name.
- Call it exactly once. A step with nothing to hand on calls `step.result()`.
- Value names that start with `kaos-` are the platform's.
- A step that ends without it fails, even with exit code 0 (or 256, which a process cannot report as anything but 0): otherwise the next step would start with nothing.

## Test a step in your own tests

`kaos_lib.testing.running` prepares what the platform hands a step, in the same process, so a test calls the
step's `main()` directly. Nothing is uploaded and nothing needs a login:

```python
from kaos_lib import testing
from app import entry

def test_count_files(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.txt").write_text("a")
    with testing.running(tmp_path, kind="evaluate", inputs={"dataset": data},
                         produces=[("artifact", "report")]) as run:
        entry.main()
    assert run.result["values"] == {"files": 1}
    assert (run.output("report") / "count.txt").exists()
```

| argument | meaning |
| --- | --- |
| `params` | what `step.start().params` holds |
| `inputs` | input name to a folder of files |
| `upstream` | step name to the values it handed on, or to `None` for a step that did not run |
| `upstream_writes` | step name to what it wrote, `{"train": {"checkpoints": folder}}`: `step.input("checkpoints")` returns that folder and `step.upstream("train").writes` names it |
| `produces` | a list of `("model" or "artifact" or "dataset", name)` |
| `kind`, `name`, `app`, `experiment` | the step's own fields |

`run.result` is what the step handed on (`None` when it wrote none) and `run.output(name)` the folder it saved.
Several steps one after the other on your machine: [`kaosctl step run`](step-run.md).

## What goes wrong, and what the message says

Every failure is a `kaos_lib.errors.StepError` with one message that says what to change. The step fails and
hands nothing on.

| when | message starts with |
| --- | --- |
| the step is started outside a pipeline run (one line, exit code 1) | `ERROR: this is not a pipeline step` |
| what the platform handed the step cannot be read (one line, exit code 1) | `ERROR: the step context ...` |
| another call comes before `start()` | `call step.start() first` |
| `input()` of a name that is neither an input nor produced by a needed step | `'<name>' is not an input of step '<step>'. Its inputs are: ...` |
| code asks for a dataset the run did not pin | `<dataset> is not an input of step '<step>'` |
| the pinned version was deleted | `input '<name>': commit ... does not exist any more` |
| `upstream()` of a step that is not in `needs=` | `step '<x>' is not upstream of '<step>'` |
| `upstream()` of a step that did not run | `step '<x>' did not run, so it left no result` |
| `input()` of something a step that did not run would have produced | `input '<name>' of step '<step>' is not there, and <x> did not run` |
| `output()` of a name that is not in `produces=` | `'<name>' is not produced by step '<step>'. It produces: ...` |
| an output is declared and was never written | `output '<name>' was not written`, `output '<name>' is empty` |
| a `check()` fails | `output '<name>' failed its check:` |
| a value is not JSON | `result value '<key>' is a <type>` |
| the result is too large | `the result costs ...; the limit is 8192` |
| `result()` is called twice | `step.result() was already called` |
| the step may not write a repository | `this app may not write <repository>` |
| the step ends without `result()` | `step '<step>' ended without step.result()` |
| an input has no files | `input '<name>': <dataset> holds no files at the version this run read` |
| a dataset output holds a file in `.kaos/` | `output '<name>' holds a file in .kaos/` |
| lakeFS rejected the step's credential | `lakeFS rejected the credential this step was given` |

## Tracking and long runs

`kaos_lib.step` does not replace the rest of kaos-lib:

- [MLflow](mlflow.md): `kaos_lib.mlflow.mlflow()` signs in for you. What the step read and wrote is recorded on
  its MLflow run automatically.
- [Long runs on HPC (Slurm)](checkpoint.md): `kaos_lib.checkpoint` saves and restores the step's state. A step
  that is ended to be continued (exit code 85) has no result yet, and that is not a failure.
- [Progress](progress.md): `kaos_lib.progress.report(done, total)`.
- [Run context](runtime.md): `kaos_lib.runtime.usable_cpus()` and the step's share of a shared HPC node.
