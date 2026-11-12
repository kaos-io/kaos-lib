# 5. Pass things on

You already pass a value. `prepare` hands one on, and `hello-world` reads it:

```python title="in prepare"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:18:18"
```

```python title="in hello-world"
--8<-- "examples/first-pipeline/template/steps/hello_world/app/entry.py:9:9"
```

`hello-world` has `needs=[prepare]` in `pipeline.py`. That makes it start after `prepare`, and it is what lets it
call `step.upstream("prepare")`.

A value is small: text, numbers, booleans, lists and objects, 8 KiB for the whole result. Anything bigger fails the
step with `the result costs ...; the limit is 8192`. Metrics and curves belong in MLflow
(`from kaos_lib.mlflow import mlflow`), and files belong in an output.

## Hand on a file

A file goes through an output. `prepare` lists a second thing it makes, and writes it:

```python title="pipeline.py" hl_lines="20"
--8<-- "examples/first-pipeline/pass-on/pipeline.py"
```

```python title="steps/prepare/app/entry.py" hl_lines="17 18 19 21"
--8<-- "examples/first-pipeline/pass-on/steps/prepare/app/entry.py"
```

`artifact("dropped-files")` declares the output, and `step.output("dropped-files")` is its folder. `hello-world` reads
the folder with the same name:

```python title="steps/hello_world/app/entry.py" hl_lines="13 15"
--8<-- "examples/first-pipeline/pass-on/steps/hello_world/app/entry.py"
```

[Send it in](first-step.md#send-the-change-in) and run. The log of `hello-world`:

```text
[hello-world] hello (my-experiment-v1): 2 files (12 bytes) in clean, 3 in the reference, 1 dropped by prepare: empty.txt
```

## What each output is

| declared as | what it is | where it is kept |
|---|---|---|
| `artifact("name")` | files of one run: a report, plots, a table | the repository `outputs-<app>`, under `<name>/<experiment>/<run>/` |
| `model("name")` | files of one run: weights | the same place |
| `dataset("name")` | a version of a dataset | the dataset `dataset-<app>-<name>` ([page 6](produce-a-dataset.md)) |

`step.input("name")` returns the folder of any of the three, for a step that names the producer in `needs=`.

## Rules

- A step's output may not have the name of one of its inputs. `prepare` could not name its output `dataset`.
- Every declared output must be written, and must hold a file. Otherwise `step.result()` fails and saves nothing:
  `output 'dropped-files' was not written` or `output 'dropped-files' is empty`.
- A step that is skipped (a `when=` that is false) leaves no result. A step that needs it gets
  `step 'x' did not run, so it left no result`, unless it asks with `step.upstream("x", optional=True)` or
  `step.input("name", optional=True)`: it then gets `None`.
- Define a step above the steps that need it. `needs=` takes at most ten steps.

Next: [Produce a dataset](produce-a-dataset.md).
