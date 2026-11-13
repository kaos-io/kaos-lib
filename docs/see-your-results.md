# See your results: metrics, files and models

**You want** to know what a run produced: a number, a curve, a report, the weights of a model.

A step has three ways to hand something on, and each ends in a different place:

| you want to keep | you write | it ends up |
|---|---|---|
| a few small values for the next step | `step.result(final_loss=0.2)` | in the result of the step, read by the steps that need it ([Values to the next step](flow-between-steps.md#values-to-the-next-step)) |
| files: a report, plots, the weights of a model | `artifact("name")` or `model("name")` in `produces=` | in the files of the run, below |
| metrics and curves, to compare runs | MLflow calls in the step | in your project's MLflow, below |

## Metrics and curves

`kaos_lib.mlflow.mlflow()` signs the step in to your project's MLflow and points the `mlflow` package at it. After that
you call `mlflow` as you always do. It fails at once, before the step has done any work, when the step has no credential.

```python title="pipeline.py"
--8<-- "examples/flows/metrics/pipeline.py"
```

```yaml title="config/train.yaml"
--8<-- "examples/flows/metrics/config/train.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/metrics/config/config.yaml"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/flows/metrics/steps/train/app/entry.py"
```

The run is in the MLflow experiment `<app>.<experiment>`, with the name of the run, `ctx.run`. The project's MLflow takes
only names that start with your app's name, so the step puts `ctx.app` in front of the experiment setting. The loss is logged once for
each epoch, so MLflow draws it as a curve. The step's image needs the MLflow client: [Add packages](add-packages.md) shows
the line. Without it the step fails with `kaos_lib.mlflow needs the mlflow extra`
([When something goes wrong](when-something-goes-wrong.md#datasets-and-commands)).

A step that uses MLflow also leaves the list of the dataset versions it read on its MLflow run:
[Which data made this model?](data-reads.md#which-data-made-this-model)

## The files of a run

The files of every artifact and model of an app are kept in one place, named `outputs-<app>` after your app, in a folder
for each run: `<name>/<experiment>/<run>/`. `<name>` is the name in `produces=`, here `model`, `<experiment>` is the
experiment setting as you wrote it (for example `my-experiment-v1`), and the run's name is on the run page and in
`ctx.run`. In MLflow the same experiment is called `<app>.<experiment>`, and a model you register is called
`<app>.<name>` in the same way. Download a run's model:

```bash
kaosctl dataset pull outputs-<app>@main ./results --prefix model/my-experiment-v1/<run>/
```

The folder `results` holds what the step wrote into `step.output("model")`. Each run has its own folder, so a later run
never overwrites it.

Next: [Add packages](add-packages.md) to a step.
