# Test your steps

**You want** to know that a step does what you think before you push it. You call its `main()` from a test, with the
settings, inputs and earlier results you choose. Nothing is uploaded, no login is needed, and no cluster is involved.

## The shape of a test

`kaos_lib.testing.running` gives the step what the platform gives it. You call `main()`, then read what the step
handed on (`run.result`) and what it wrote (`run.output(name)`).

```python title="step_tests/test_prepare.py"
--8<-- "examples/first-pipeline/try-locally/step_tests/test_prepare.py"
```

```bash
python -m pytest step_tests
```

## What you give it

| argument | gives the step | it reads it with |
|---|---|---|
| `params={"prepare": {"min_bytes": 1}}` | the settings of the sections in `reads=` | `step.start().params` |
| `inputs={"dataset": folder}` | the folder of a dataset input | `step.input("dataset")` |
| `upstream={"prepare": {"files": 2}}` | the values an earlier step handed on | `step.upstream("prepare").values` |
| `upstream_writes={"prepare": {"clean": folder}}` | the files an earlier step wrote | `step.input("clean")` |
| `produces=[("dataset", "clean")]` | the outputs the step declares in `produces=` | `step.output("clean")` |

`kind`, `name`, `app` and `experiment` set the step's own fields. Every argument is in the
[Reference](reference.md#test-a-step-kaos_libtestingrunningtmp_path-kwargs).

## What to assert

- `run.result["values"]`: what the step handed to the next one.
- `run.output("name")`: the folder the step wrote. List it, read a file.
- `run.result["reads"]` and `run.result["writes"]`: what the step recorded as read and written.

A step that breaks a rule raises `kaos_lib.errors.StepError`; assert it with `pytest.raises`. A step that ends without
`step.result()` fails the test run with exit code 1, as it would on the platform.

## A step that copes with a skipped step

Give an earlier step the value `None`: it did not run. The step must work with and without it.

```python title="step_tests/test_final.py"
--8<-- "examples/flows/skip/step_tests/test_final.py:15:40"
```

## A step that stops and continues

Ask the step to stop after the second pass, check that it ended with exit code 85, and run it again with the same
checkpoint folder.

```python title="step_tests/test_train.py"
--8<-- "examples/first-pipeline/long-job/step_tests/test_train.py"
```

## Run the steps one after the other

`kaosctl step run <step>` starts a step as the platform does, with `python -m app.entry`, and keeps its result for the
next step. It needs the settings from a file, `--params-file`:

```yaml title="params.yaml"
--8<-- "examples/first-pipeline/try-locally/params.yaml"
```

```bash
kaosctl step run prepare --params-file params.yaml --input dataset=./toy
kaosctl step run hello-world --params-file params.yaml --input reference=./reference
```

[Try it locally](try-it-locally.md) shows the output line by line. To check the pipeline file without running
anything, use `kaosctl lint`.
