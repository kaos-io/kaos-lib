# 3. Settings

You have `config/prepare.yaml`, and `prepare` reads it:

```yaml title="config/prepare.yaml"
--8<-- "examples/first-pipeline/template/config/prepare.yaml"
```

`config/config.yaml` lists the files of the config tree, and `config/experiment.yaml` names the run:

```yaml title="config/config.yaml"
--8<-- "examples/first-pipeline/template/config/config.yaml"
```

```yaml title="config/experiment.yaml"
--8<-- "examples/first-pipeline/template/config/experiment.yaml"
```

Every plain value under `config/` is a field on the run form. The field's name is the path of the value with dashes
between the levels: `experiment.name` is the field `experiment-name`, `prepare.min_bytes` is `prepare-min_bytes`, and the
default is the value in the file. A list is not a field.

The comment you write next to a value is the description of its field. Write it at the end of the line, or on the lines
directly above the value (no empty line between): `experiment.name` above has the comment "experiment name (used for
tracking + artifact path prefixes)", and that is what the form shows under the field. A value without a comment has no
description.

A step gets the settings it asks for, and no others. `pipeline.py` names them with `reads=`, and the step finds them
in `step.start().params`:

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:19:20"
```

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:9:9"
```

## Add a setting

Let `hello-world` start its report with a word you choose on the form. Four places change:

```yaml title="config/hello.yaml (new)"
--8<-- "examples/first-pipeline/settings/config/hello.yaml"
```

```yaml title="config/config.yaml" hl_lines="9"
--8<-- "examples/first-pipeline/settings/config/config.yaml"
```

A file of `config/` that `config/config.yaml` does not list is not read.

```python title="pipeline.py" hl_lines="21-22"
--8<-- "examples/first-pipeline/settings/pipeline.py"
```

```python title="steps/hello_world/app/entry.py" hl_lines="7 12"
--8<-- "examples/first-pipeline/settings/steps/hello_world/app/entry.py"
```

Without `reads=["hello"]` the step gets no `hello` section, and `ctx.params["hello"]` raises a `KeyError`.

## Send it in and run it

[Send the change in](first-step.md#send-the-change-in). Open the run form: it has a new field, `hello-title`, with the
default `hello`. Change it to `greetings`, submit, and read the log of `hello-world`:

```text
[hello-world] greetings (my-experiment-v1): 2 files (12 bytes) in clean, 1 dropped by prepare
```

## If it is not there

| you see | because |
|---|---|
| the new setting is not on the form | it is in a file that `config/config.yaml` does not list, or it is a list |
| a step gets a `KeyError` for a section | the step does not name the section in `reads=` |
| the check on the pull request names a step and a section | `reads=` names a section that is not in `config/` |

The version of a dataset is not a setting you read in code.

Next: [Read data](read-data.md).
