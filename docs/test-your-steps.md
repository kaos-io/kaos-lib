# Test your steps

**You want** to know that a step does what you think before you push it. You call its `main()` from a test, with the
settings, inputs and earlier results you choose. Nothing is uploaded, no login is needed, and no cluster is involved.

## The shape of a test

`kaos_lib.testing.running` gives the step what the platform gives it. You call `main()`, then read what the step
handed on (`run.result`) and what it wrote (`run.output(name)`).

Save the file as `step_tests/test_prepare.py` in your app. Install pytest once, in the Python environment where you
installed kaos-lib: `pip install pytest`.

```python title="step_tests/test_prepare.py"
--8<-- "examples/first-pipeline/try-locally/step_tests/test_prepare.py"
```

```bash
python -m pytest step_tests
```

## What you give it

`running` takes `params`, `inputs`, `upstream`, `upstream_writes` and `produces`, and the fields `kind`, `name`, `app` and
`experiment`. Each argument, and the call of the step that reads it, is in the
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

A step that was skipped by `step.skip()` has a reason. Give it with `upstream_skipped={"evaluate": "the reason"}`: the
step then finds `step.skipped("evaluate")` set. A step that ends itself with `step.skip(...)` raises `SystemExit` with
code 0: call it inside `pytest.raises(SystemExit)`, and read `run.result` for `{"status": "skipped", "reason": ...}`
([Conditions and skipping](conditions-and-skipping.md)).

## A step that stops and continues

Ask the step to stop after the second pass, check that it ended with exit code 85, and run it again with the same
checkpoint folder. Save it as `step_tests/test_train.py`.

```python title="step_tests/test_train.py"
--8<-- "examples/first-pipeline/long-job/step_tests/test_train.py"
```

## Run the steps one after the other

To run a step the way the platform does, with `python -m app.entry` and the result kept for the next step, use
`kaosctl step run`. [Try it locally](try-it-locally.md#run-steps-the-way-the-platform-does) shows it. To check the
pipeline file without running anything, use `kaosctl lint`.
