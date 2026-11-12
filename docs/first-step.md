# 2. Your first step

You have the template's `steps/hello_world/app/entry.py`. It is 17 lines, and every step has the same three parts:
start, do something, hand back a result.

```python title="steps/hello_world/app/entry.py" hl_lines="6 7 9 11 13"
--8<-- "examples/first-pipeline/template/steps/hello_world/app/entry.py"
```

- `step.start()` (line 6) is the first call. It reads what the platform gives the step and returns it: the run, the
  step, the experiment and the settings of the step.
- The middle is yours. `step.input("clean")` returns a folder with the dataset `clean` that `prepare` wrote in this run.
  `step.output("report")` returns an empty folder for a file the step makes. `step.upstream("prepare")` returns what
  `prepare` handed on.
- `step.result(files=files)` (line 13) saves the output folders and hands the values on. It is the last call of the
  step. A step that ends without it fails, because the next step would start with nothing.

The platform runs the step as `python -m app.entry`, with no arguments. Your code reads no environment variable:
`step.start()` gives you everything.

## The six kinds

Every step in `pipeline.py` says what it does with `kind=`. The kind is a label you choose by what the step does:

| kind | for a step that |
|---|---|
| `ingest` | brings data in from outside ([Bring data in](bring-data-in.md)) |
| `transform` | turns data into other data: preprocess, filter, split, convert (like `prepare`) |
| `train` | trains a model |
| `evaluate` | measures a model or a dataset (like `hello-world`) |
| `publish` | registers or delivers a result |
| `control` | decides or coordinates, and does no data work itself |

Three kinds have rules. `ingest`, `publish` and `control` steps always run on the platform's own machines and may not set
`walltime=`, and a `control` step has no `inputs=` and no `produces=`. A step without a `kind=` is refused. The rules are
in [What you must and what you can](must-and-can.md#you-must).

## Change the step

Hand on the size of the files as well as their number. Four lines change:

```python title="steps/hello_world/app/entry.py" hl_lines="8 9 11 14"
--8<-- "examples/first-pipeline/first-step/steps/hello_world/app/entry.py"
```

## Send the change in

A change reaches the platform through a pull request into `dev`:

```bash
git checkout -b report-the-size
git add steps/hello_world
git commit -m "hello-world: report the size"
git push -u origin report-the-size
```

Open the pull request on GitHub with the base `dev`. The platform checks the pipeline on the pull request: the
same checks as `kaosctl lint` ([Try it locally](try-it-locally.md)), and a render of `pipeline.py`. When the
checks pass, merge the pull request. The merge builds the changed steps. A step is rebuilt only when its own folder
changed.

The later pages say "send it in" for these steps.

## Run it again

Run the pipeline as on [page 1](run-it.md#run-the-pipeline). The log of `hello-world` has the new numbers:

```text
[hello-world] my-experiment-v1: 2 files (12 bytes) in clean, 1 dropped by prepare
```

You changed one step and ran it. Next: [Settings](settings.md) puts a value on the run form.
