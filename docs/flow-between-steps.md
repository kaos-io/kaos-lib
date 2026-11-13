# Data flow: between steps

Scenarios for handing things from one step to the next in a run.

## Values to the next step

**You want** the next step to know a number or a short text.

The first step ends with the values. The second names the first in `needs=` and reads them.

```python title="in prepare"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:18:18"
```

```python title="in hello-world"
--8<-- "examples/first-pipeline/template/steps/hello_world/app/entry.py:9:9"
```

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:21:21"
```

**The run records** the values in the result of the first step. A value is text, a number, a boolean, a list or an
object. The whole result has a size limit ([the limits](contract.md#the-limits)): bigger things go in a file
([next scenario](#files-to-the-next-step)) or in MLflow ([See your results](see-your-results.md)).

## Files to the next step

**You want** the next step to get files: a report, a table, plots.

Declare an artifact in `produces=`, write into its folder, and read the folder by the same name in the next step.

```python title="pipeline.py"
--8<-- "examples/first-pipeline/pass-on/pipeline.py:19:22"
```

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/pass-on/steps/prepare/app/entry.py"
```

```python title="steps/hello_world/app/entry.py"
--8<-- "examples/first-pipeline/pass-on/steps/hello_world/app/entry.py"
```

**The run records** a write of type `artifact` named `dropped-files`. The files are kept with the run, under
`<name>/<experiment>/<run>/`. A model works the same way with `model("name")`.

## A step that may be skipped

**You want** a step to run only when the run form asks for it, and the steps after it to work either way.

`when=` holds the name of a run-form field, compared with a value: `when="extra-mode != off"` (or a value of a needed step: `"evaluate.passed == true"`, see [Conditions and skipping](conditions-and-skipping.md)). The field is named
as in [Settings](settings.md): `extra.mode` is the field `extra-mode`. Join comparisons with `and` or `or` (`and` is
taken first; no parentheses), and put a value with spaces in quotes. A step that is skipped leaves no result and no
files. The step after it asks for them with `optional=True` and gets `None` when they are not there. Without
`optional=True` it fails with `step 'x' did not run, so it left no result`.

```python title="pipeline.py"
--8<-- "examples/flows/skip/pipeline.py"
```

```yaml title="config/extra.yaml"
--8<-- "examples/flows/skip/config/extra.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/skip/config/config.yaml"
```

```python title="steps/base/app/entry.py"
--8<-- "examples/flows/skip/steps/base/app/entry.py"
```

```python title="steps/extra/app/entry.py"
--8<-- "examples/flows/skip/steps/extra/app/entry.py"
```

```python title="steps/final/app/entry.py"
--8<-- "examples/flows/skip/steps/final/app/entry.py"
```

[Test your steps](test-your-steps.md#a-step-that-copes-with-a-skipped-step) runs `final` both ways. A step can also
leave itself out while it runs, with `step.skip("the reason")`, and `when=` can test a value an earlier step handed on:
[Conditions and skipping](conditions-and-skipping.md).

**The run records** nothing for `extra` when it is skipped, and its result and files when it ran.
`optional=True` does not make a declared input optional: an input named in `inputs=` is always there.

## One step needs several steps

**You want** one step to gather the work of several others, for example to keep the better of two models.

`needs=[small, large]` gives `pick-best` the result of both, and lets it read the model each one made. A step may need
at most ten steps ([limits](contract.md#the-limits)).

```python title="pipeline.py"
--8<-- "examples/flows/fan-in/pipeline.py"
```

```yaml title="config/train.yaml"
--8<-- "examples/flows/fan-in/config/train.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/fan-in/config/config.yaml"
```

```python title="steps/train_small/app/entry.py"
--8<-- "examples/flows/fan-in/steps/train_small/app/entry.py"
```

```python title="steps/train_large/app/entry.py"
--8<-- "examples/flows/fan-in/steps/train_large/app/entry.py"
```

```python title="steps/pick_best/app/entry.py"
--8<-- "examples/flows/fan-in/steps/pick_best/app/entry.py"
```

Two needed steps may not make an output of the same name, so each model here has its own name.

**The run records** in the result of `pick-best` a write named `winner`; the two models stay where their steps saved
them.

Next: [Train, checkpoint and resume](flow-training.md).
