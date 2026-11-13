# evaluate

## What it is for

An `evaluate` step measures: a model, a dataset, the result of an earlier step. It writes reports as artifacts. It may
not produce a dataset or a model: a step that makes a dataset is a `transform`, and one that makes a model is a `train`.

## The contract

| | |
|---|---|
| **Must** | nothing about what it produces |
| **May** | produce artifacts (reports, plots, tables); read datasets (`inputs=`) and earlier steps (`needs=`); hand on values such as a score; set `gpu=True`, `walltime=` (the default of the run form's time limit), `when=` |
| **Must not** | produce a dataset or a model |

## Where it runs

On the platform's own machines or on HPC (Slurm).

## What the platform does

- Checks, when the pipeline is built, that `produces=` holds no dataset and no model.
- Keeps each artifact in its own folder for the run, `<name>/<experiment>/<run>/`. Nothing an `evaluate` step writes
  changes what other pipelines read ([models and artifacts](data-writes.md#models-and-artifacts)).
- Gives later steps the values it hands on. A later step can run only when a value says so, with
  `when="evaluate.passed == true"` ([Conditions and skipping](conditions-and-skipping.md)).

## A complete minimal example

```python title="pipeline.py"
--8<-- "examples/kinds/evaluate/pipeline.py:6:8"
```

```python title="steps/evaluate/app/entry.py"
--8<-- "examples/kinds/evaluate/steps/evaluate/app/entry.py"
```

```yaml title="config/evaluate.yaml"
--8<-- "examples/kinds/evaluate/config/evaluate.yaml"
```

```python title="steps/train/app/entry.py (the step before it)"
--8<-- "examples/kinds/evaluate/steps/train/app/entry.py"
```

```yaml title="config/config.yaml"
--8<-- "examples/kinds/evaluate/config/config.yaml"
```

`step.input("model")` is the folder of the model `train` wrote, found by its name in `produces=` because `evaluate` has
`needs=[train]`. The report is an artifact, and `score` and `passed` reach the steps that need `evaluate`.

## Common mistakes

| the mistake | what you get |
|---|---|
| a dataset or a model in `produces=` | `kaosctl lint`: `L-E07`, `Step 'score': an evaluate step writes reports only, so it may not produce a dataset or a model. Use kind="transform" for a step that makes a dataset, kind="train" for one that makes a model.` The platform's check says the same with a small `s` |
| reading the model without `needs=` | `'model' is not an input of step 'evaluate'. Its inputs are: none. Add it to inputs=[...] in pipeline.py.` Name the step that makes it in `needs=` |
| the step before it was skipped | `step 'train' was skipped (reason), so it left no result, and 'evaluate' needs it.` Read it with `optional=True`: [Conditions and skipping](conditions-and-skipping.md#what-a-step-that-needs-a-skipped-step-sees) |
| a `when=` on a value `evaluate` never set | `step 'evaluate' ran but gave no value 'passed' (a typo in the name, or the value was never set with step.result(passed=...))` and the run stops. If `evaluate` was skipped, the condition is false and the step that asked is skipped |

## Related

[Step types](step-types.md) · [Conditions and skipping](conditions-and-skipping.md) · [See your results](see-your-results.md) ·
[GPUs on HPC (Slurm)](gpus-on-hpc.md) · [Your contract with the platform](contract.md)
