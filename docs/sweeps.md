# Sweeps

A sweep tries one step with several settings, for example three learning rates, and keeps the best.

## What works today: a loop inside one step

Write the loop in the step. The settings come from `config/`. The step tries each one and keeps the best model.

```python title="steps/train/app/entry.py"
--8<-- "examples/flows/sweep/steps/train/app/entry.py"
```

```python title="pipeline.py"
--8<-- "examples/flows/sweep/pipeline.py"
```

```yaml title="config/train.yaml"
--8<-- "examples/flows/sweep/config/train.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/sweep/config/config.yaml"
```

One step is one folder, one image and one set of settings, however many trials it runs. The trials run one after the
other on one machine. To log every trial, log it to MLflow from the loop ([See your results](see-your-results.md)).

A setting is a text or a number, and a list is not a field of the run form. Write the values as one text,
`"0.1,0.01,0.001"`, and split it in the step.

## What does not work

**One step for each trial.** You can build steps in a Python loop in `pipeline.py`, but each one is a step with its own
folder, its own image and its own settings, a model name of its own, and at most ten of them can be needed by one step.
`kaosctl lint` cannot read steps built in a loop and says so (`L-I04`). `kaosctl step run` finds them by running `pipeline.py` to see which steps it builds. It is more work than the loop above and it gives
no parallel trials unless each step has a machine. Use it only when the trials must run on different machines at the
same time.

**A matrix on the run form.** A choice of settings that starts one trial for each combination, and gathers the results,
is planned. It is not available now.

Next: [Several pipelines](several-pipelines.md).
