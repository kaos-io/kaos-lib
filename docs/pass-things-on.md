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

A value is small: text, numbers, booleans, lists and objects. The whole result has a size limit
([the limits](must-and-can.md#the-limits)), and a bigger one fails the step with `the result costs ...`. Metrics and
curves belong in MLflow ([See your results](see-your-results.md)), and files belong in an output.

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

## A step that runs only sometimes

A step can run only when a choice on the run form says so. `when=` holds the condition, and the value of a run-form
field is written `{{workflow.parameters.<field>}}`, where `<field>` is the field's name (the path of the setting with
dashes, see [Settings](settings.md)):

```python title="pipeline.py"
--8<-- "examples/flows/skip/pipeline.py:8:10"
```

`extra` runs unless the field `extra-mode` is `off`. A skipped step leaves no result, and a step that needs it asks with
`optional=True` and gets `None`. [A step that may be skipped](flow-between-steps.md#a-step-that-may-be-skipped) shows all
the code.

`step.input("name")` returns the folder of any output of a step that you name in `needs=`. The three kinds of output,
`artifact`, `model` and `dataset`, and where each is kept are in the [Reference](reference.md#what-produces-makes), and the rules for outputs are in [What you must and what you can](must-and-can.md#you-must).

Next: [Produce a dataset](produce-a-dataset.md).
