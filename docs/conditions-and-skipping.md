# Conditions and skipping

A step does not have to run every time. There are three ways to leave it out. Pick by what decides.

| what decides | write | when it is decided |
|---|---|---|
| a choice on the run form | `when="extra-mode != off"` | before the step starts |
| a value an earlier step computed | `when="evaluate.passed == true"` | before the step starts, once the earlier step has ended |
| the step itself, while it runs | `step.skip("the reason")` | inside the step |

## Run only if the model passed

**You want** to publish a model only when the evaluation says it is good, and to write a summary either way.

`evaluate` hands on a value with `step.result(passed=..., score=...)`. `publish` names that value in `when=`:
`evaluate.passed`. The step `evaluate` must be in `needs=` of `publish`.

```python title="pipeline.py"
--8<-- "examples/flows/conditions/pipeline.py"
```

```python title="steps/evaluate/app/entry.py"
--8<-- "examples/flows/conditions/steps/evaluate/app/entry.py"
```

`publish` has a second reason to stay out of the way. When no registry name is set, it ends itself with
`step.skip("...")`:

```python title="steps/publish/app/entry.py"
--8<-- "examples/flows/conditions/steps/publish/app/entry.py"
```

`summary` needs both. It works whether `publish` ran, skipped itself, or was never started:

```python title="steps/summary/app/entry.py"
--8<-- "examples/flows/conditions/steps/summary/app/entry.py"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/conditions/config/config.yaml"
```

```yaml title="config/registry.yaml"
--8<-- "examples/flows/conditions/config/registry.yaml"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/flows/conditions/steps/train/app/entry.py"
```

```yaml title="config/train.yaml"
--8<-- "examples/flows/conditions/config/train.yaml"
```

```yaml title="config/evaluate.yaml"
--8<-- "examples/flows/conditions/config/evaluate.yaml"
```

The guide runs this app three ways on every change: the model passes and `publish` delivers, the model passes and
`publish` skips itself, and the model does not pass.

## What `when=` can hold

One comparison is a name, then `==` or `!=`, then a text. There are two kinds of name:

| the name | means | example |
|---|---|---|
| a field of the run form | the value on the form, as text. A setting `extra.mode` is the field `extra-mode` ([Settings](settings.md)) | `when="mode != off"` |
| `<step>.<value>` | a value the step `<step>` handed on with `step.result(<value>=...)`, as text. `<step>` must be in this step's `needs=` | `when="evaluate.passed == true"` |

A value of the run form is text. A `true`, `yes` or `on` written in `config/` reaches the form as `true`, so
`when="publish-enabled == true"` works with any of them. Join comparisons with `and` and `or`. `and` is taken first. There are no parentheses, and no `<` or `>`. A text with
spaces is quoted.

**What is compared, exactly.** A value that is a string is compared with your text as text. A value that is a number or
`true` or `false` is compared by its JSON text: the way JSON writes it, without an exponent for the sizes people use.
So `evaluate.rows != 1000000` is false when `rows` is 1000000, and `1e6`, `1000000` and `1000000.0` all match the value
1000000. `1.0` matches the value 1, and `1e-5` matches 0.00001. A text that could never match is refused when the
pipeline is built, with what to write instead: a number written another way than JSON writes it (`.5`, `+1`, `01`, `5.`),
`True` or `NULL` that is not in lowercase, an integer above 9007199254740992 (a result holds a number as a double), and a
text with a line break or a tab. A value that is `null` counts as missing.

A value of a step that was skipped makes the condition false.

If you need a number comparison, compare in the step. Let `evaluate` hand on `passed=score >= 0.9`, and test
`evaluate.passed`.

## A value that was never set stops the run

`when="evaluate.passed == true"` needs the value. If `evaluate` ran well but its result has no `passed` (a typo in the
name, or the value was never set), the condition is not quietly false. The step shows an error that names the step and the
value: `step 'evaluate' ran but gave no value 'passed' (a typo in the name, or the value was never set with step.result(passed=...))`.
The run stops there. A value set to `null` counts as not set. Make the step always set the value, or test a form field
instead.

A step that was skipped is different: see [below](#what-a-step-that-needs-a-skipped-step-sees).

## What a step that needs a skipped step sees

The rule is the same for a step skipped by `when=` and for a step that skipped itself. **The steps that need it still
run.** They find it as a step that left no result:

- `step.upstream("publish")` fails with a message that names the step and, for `step.skip()`, its reason:
  `step 'publish' was skipped (no registry name is set in config/registry.yaml), so it left no result, and 'summary' needs it.`
- `step.upstream("publish", optional=True)` gives `None`.
- `step.skipped("publish")` gives the reason the step gave to `step.skip()`. It gives `""` when the step did not run at all
  (its `when=` was false), and `None` when the step ran and left a result.
- `step.input("name", optional=True)` gives `None` for an output of a step that left none.

A `when=` on the value of a skipped step is false, for `==` and for `!=` alike: the step that asked is skipped, not failed,
and the run goes on.

A skipped step makes no files. A dataset it would have made gets no new version, and
[the run does not move `latest`](flow-datasets.md#move-latest) for it.

## How it shows

A step that `when=` leaves out is shown as skipped on the run page, with the condition that was false. A step that ends
itself with `step.skip()` ends well, with exit code 0: it is not a failure, and nothing in the run turns red. Its log
says `step 'publish' skipped: <the reason>`, and the run records the reason with the step's result.

On your laptop, `kaosctl step run publish` prints `Result of publish (...): skipped. <the reason>`.

## Test it

[Test your steps](test-your-steps.md#a-step-that-copes-with-a-skipped-step) runs a step with an earlier step that was
skipped. Give `upstream_skipped={"publish": "the reason"}` to `testing.running`, and call `step.skip` inside
`pytest.raises(SystemExit)`: it ends the step with exit code 0.

## When it does not work

| you see | it means | do this |
|---|---|---|
| `when= reads a value of step 'evaluate', which this step does not need` | `evaluate` is not in `needs=` | add it to `needs=` |
| `when='score > 0.5' is not a condition the platform can read` | only `==` and `!=` exist | compare in the step and test a `passed` value |
| `step 'evaluate' ran but gave no value 'passed' (a typo in the name, or the value was never set with step.result(passed=...))` | the step ran, but its result has no such value | fix the name, or set the value in every case |
| `when= compares evaluate.rows with '.5', which cannot be matched reliably: ...` | the text looks like a number but is not written the way JSON writes numbers | write `0.5` (the message says what to write) |
| `step.skip() needs the reason, as text` | the reason is empty | write why: `step.skip("nothing to publish")` |

Next: [Several pipelines](several-pipelines.md).
