# Step examples

One complete, small step for each job a step does. Each example has the `step(...)` line, the whole
`app/entry.py`, and what the step reads and writes. At the end, one `pipeline.py` wires them together. How a
step is started and what it may do: [How a step works](steps.md). Every call: [The step API](step.md).

| # | the job | example step |
| --- | --- | --- |
| 1 | [Data consumer](#1-a-data-consumer): read a dataset and compute something small | `data-check` |
| 2 | [Data preparation](#2-data-preparation-a-dataset-producer): write a dataset that later steps and runs read | `prepare` |
| 3 | [Training](#3-training): GPU, MLflow, progress, a model | `train` |
| 4 | [Evaluation](#4-evaluation): score the model and write a report | `evaluate` |
| 5 | [Conditional step](#5-a-conditional-step): run only on a choice from the run form | `export-model` |
| 6 | [Publish](#6-publish-a-model): register the model in MLflow | `register-model` |
| 7 | [Model transform](#7-a-model-transform): make another model from a model | `quantize` |

## The example app

The examples share one small app. Its dataset has two files, `train.csv` and `val.csv`, each with the columns
`x` and `y`. A dataset like this uses the `raw` layout ([Datasets](datasets.md)). Make one to try the examples:

```python
import csv, random
from pathlib import Path

Path("toy").mkdir(exist_ok=True)
for name, rows in (("train", 200), ("val", 50)):
    with open(f"toy/{name}.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["x", "y"])
        for _ in range(rows):
            x = random.uniform(-1, 1)
            writer.writerow([round(x, 4), round(2 * x + 1 + random.gauss(0, 0.05), 4)])
```

```bash
kaosctl dataset push ./toy dataset-toy -m "toy data"     # opens a pull request; merge it in lakeFS
kaosctl dataset release dataset-toy                      # tags the merged data as v1
```

The settings, in `config/`:

```yaml
# config/config.yaml
defaults:
  - _self_
  - experiment
  - dataset
  - train
  - evaluate
  - export
  - registration
```

```yaml
# config/dataset.yaml: the dataset the run reads, <dataset>@<version>
dataset: "dataset-toy@v1"
```

```yaml
# config/experiment.yaml
experiment:
  name: "my-experiment-v1" # names the MLflow experiment and the folders of your results
```

```yaml
# config/train.yaml
train:
  epochs: 20
  learning_rate: 0.1
```

```yaml
# config/evaluate.yaml
evaluate:
  max_mse: 0.5 # the verdict is "pass" when the error on the validation split is at most this
```

```yaml
# config/export.yaml
export:
  format: "none" # "none" skips the export step; "fp16" exports a half-precision copy
```

```yaml
# config/registration.yaml
registration:
  model_name: "my-model"
  promote_to: "" # empty = no alias; for example "champion"
```

Every step image is the same few lines. Copy the `ARG KAOS_LIB_PACKAGE=...` line from your template's Dockerfile:
the platform's build replaces its value.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel]>=0.5"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

## 1. A data consumer

**Use it** to look at the data before anything expensive runs.

```python
check = step("data-check", kind="evaluate", inputs=["dataset"])
```

```python
"""data-check: count the rows of each split and stop the run when a split is empty."""
import csv

from kaos_lib import step


def main() -> None:
    step.start()
    data = step.input("dataset")
    rows = {}
    for split in ("train", "val"):
        with open(data / f"{split}.csv", newline="") as fh:
            rows[split] = sum(1 for _ in csv.DictReader(fh))
        if rows[split] == 0:
            raise SystemExit(f"{split}.csv has no rows")
    step.result(**rows)


if __name__ == "__main__":
    main()
```

| | |
| --- | --- |
| reads | the dataset version the run pinned for the setting `dataset` |
| hands on | `train` and `val`, the row counts |
| on HPC (Slurm) | the same code; the data is copied next to the job before it starts |

Wrong data should end the step with a message, as `raise SystemExit(...)` does. A dataset with no files at all
raises `kaos_lib.errors.EmptyDataset`, so a step can tell "no data yet" from other failures.

## 2. Data preparation: a dataset producer

**Use it** for preprocessing whose result later steps, and later runs, read: cleaning, filtering, splitting,
converting. The step writes a dataset of its own; every run makes one version of it, and a run that changes
little stores little.

```python
prepare = step("prepare", kind="transform", needs=[check], inputs=["dataset"], produces=[dataset("clean")])
```

```python
"""prepare: drop the rows outside [-1, 1] and write the rest as the dataset "clean"."""
import csv

from kaos_lib import step


def main() -> None:
    step.start()
    data, clean = step.input("dataset"), step.output("clean")
    kept = dropped = 0
    for split in ("train", "val"):
        with open(data / f"{split}.csv", newline="") as src, open(clean / f"{split}.csv", "w", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=["x", "y"])
            writer.writeheader()
            for row in csv.DictReader(src):
                if -1 <= float(row["x"]) <= 1:
                    writer.writerow(row)
                    kept += 1
                else:
                    dropped += 1
    step.check("clean", min_files=2)
    step.result(rows=kept, dropped=dropped)


if __name__ == "__main__":
    main()
```

| | |
| --- | --- |
| reads | the dataset `dataset` |
| writes | a version of the dataset `clean`: the two files in `step.output("clean")` |
| hands on | `rows` and `dropped` |
| the next steps | read it with `step.input("clean")` |
| a later run | reads it as an input: a setting `clean: dataset-clean@latest` named in `inputs=` |
| `latest` of `dataset-clean` | moves to this run's version only when the run asks for it on the run form |

Write every file under the same path in every run. Then a run that changes one file uploads one file, and the
difference between two versions is the real change. More:
[A dataset a step produces](steps-and-datasets.md#a-dataset-a-step-produces).

## 3. Training

**Use it** for the step that makes the model.

```python
train = step("train", kind="train", gpu=True, needs=[prepare], walltime="2h",
             reads=["experiment", "train"], produces=[model("model")])
```

```python
"""train: fit y = a*x + b on the dataset "clean" and save the two numbers as the model."""
import csv
import json

from kaos_lib import progress, step
from kaos_lib.mlflow import mlflow


def main() -> None:
    ctx = step.start()
    cfg = ctx.params["train"]
    with open(step.input("clean") / "train.csv", newline="") as fh:
        points = [(float(r["x"]), float(r["y"])) for r in csv.DictReader(fh)]
    a = b = 0.0
    tracking = mlflow()                                   # signed in by the platform
    tracking.set_experiment(ctx.experiment)
    with tracking.start_run(run_name=ctx.run):
        tracking.log_params(cfg)
        for epoch in range(cfg["epochs"]):
            grad_a = sum((a * x + b - y) * x for x, y in points) / len(points)
            grad_b = sum((a * x + b - y) for x, y in points) / len(points)
            a, b = a - cfg["learning_rate"] * grad_a, b - cfg["learning_rate"] * grad_b
            loss = sum((a * x + b - y) ** 2 for x, y in points) / len(points)
            tracking.log_metric("loss", loss, step=epoch)
            progress.report(epoch + 1, cfg["epochs"], "epoch")
    (step.output("model") / "model.json").write_text(json.dumps({"a": a, "b": b}))
    step.result(loss=loss)


if __name__ == "__main__":
    main()
```

| | |
| --- | --- |
| reads | the dataset `clean` that `prepare` wrote in this run, and the settings `train` |
| writes | the model, saved in your outputs repository under `model/<experiment>/<run>/` |
| hands on | `loss` |
| MLflow | the metrics and parameters; what the step read and wrote is added to the MLflow run for you |
| long runs | add `resumable=True` and save your state with `kaos_lib.checkpoint` ([Long runs](checkpoint.md)) |

## 4. Evaluation

**Use it** to score a model on data it did not train on.

```python
evaluate = step("evaluate", kind="evaluate", needs=[prepare, train], reads=["evaluate"],
                produces=[artifact("report")])
```

```python
"""evaluate: the error of the model on the validation split, and a verdict."""
import csv
import json

from kaos_lib import step


def main() -> None:
    ctx = step.start()
    model = json.loads((step.input("model") / "model.json").read_text())
    with open(step.input("clean") / "val.csv", newline="") as fh:
        points = [(float(r["x"]), float(r["y"])) for r in csv.DictReader(fh)]
    mse = sum((model["a"] * x + model["b"] - y) ** 2 for x, y in points) / len(points)
    verdict = "pass" if mse <= ctx.params["evaluate"]["max_mse"] else "fail"
    (step.output("report") / "report.json").write_text(json.dumps({"mse": mse, "verdict": verdict}))
    step.result(mse=mse, verdict=verdict, train_loss=step.upstream("train").values["loss"])


if __name__ == "__main__":
    main()
```

| | |
| --- | --- |
| reads | the model `train` wrote and the dataset `prepare` wrote, both by name |
| writes | the artifact `report` |
| the same data | `step.input("clean")` is the same version in `train` and in `evaluate`: both read what `prepare` wrote in this run |

## 5. A conditional step

**Use it** for work that only some runs need: export, quantization, an extra report. The condition is a value
from the run form, and the step is skipped when it is false.

```python
export = step("export-model", kind="transform", needs=[train], reads=["export"],
              when="{{workflow.parameters.export-format}} != none", produces=[artifact("exported")])
```

The name inside `{{workflow.parameters.…}}` is the setting's path in `config/` with `.` written as `-`: the
setting `export.format` is `export-format`. Here `export.format` is `"none"` by default, so a run exports only
when someone chooses `fp16`. Compare with `==` or `!=`.

```python
"""export-model: a half-precision copy of the model."""
import json

from kaos_lib import step


def main() -> None:
    step.start()
    model = json.loads((step.input("model") / "model.json").read_text())
    half = {name: round(value, 3) for name, value in model.items()}
    (step.output("exported") / "model-fp16.json").write_text(json.dumps(half))
    step.result(format="fp16")


if __name__ == "__main__":
    main()
```

What happens when the step is skipped:

| | |
| --- | --- |
| the step | is shown as skipped. Its code does not run |
| steps that need it | still run |
| `step.upstream("export-model")` in such a step | raises, naming the step |
| `step.upstream("export-model", optional=True)` | returns `None` |

So a step that needs a conditional step asks with `optional=True`, as the next example does.

## 6. Publish a model

**Use it** to register the model a run made.

```python
register = step("register-model", kind="publish", needs=[train, evaluate, export], reads=["registration"])
```

```python
"""register-model: register the run's model in MLflow when the evaluation passed."""
from kaos_lib import step
from kaos_lib.mlflow import mlflow


def main() -> None:
    ctx = step.start()
    cfg = ctx.params["registration"]
    evaluation = step.upstream("evaluate").values
    export = step.upstream("export-model", optional=True)        # None when the export was skipped
    if evaluation["verdict"] != "pass":
        step.result(registered=False, reason=f"mse {evaluation['mse']}")
        return
    tracking = mlflow()
    tracking.set_experiment(ctx.experiment)
    with tracking.start_run(run_name=f"{ctx.run}-register"):
        tracking.log_artifacts(str(step.input("model")), "model")
        version = tracking.register_model(f"runs:/{tracking.active_run().info.run_id}/model", cfg["model_name"])
    step.result(registered=True, model=cfg["model_name"], version=version.version,
                exported=export.values["format"] if export else "none")


if __name__ == "__main__":
    main()
```

| | |
| --- | --- |
| reads | the results of `evaluate` and, when it ran, of `export-model`; the model `train` wrote |
| writes | nothing in `produces=`: the model goes to the MLflow registry |
| hands on | whether it registered, and the registered version |

## 7. A model transform

**Use it** to make another model from the run's model: quantize, prune, convert to another format.

```python
quantize = step("quantize", kind="transform", needs=[train], produces=[model("model-int8")])
```

```python
"""quantize: the run's model with its numbers rounded to one decimal."""
import json

from kaos_lib import step


def main() -> None:
    step.start()
    source = json.loads((step.input("model") / "model.json").read_text())
    small = {name: round(value, 1) for name, value in source.items()}
    (step.output("model-int8") / "model.json").write_text(json.dumps(small))
    step.result(parameters=len(small))


if __name__ == "__main__":
    main()
```

| | |
| --- | --- |
| reads | the model `train` wrote in this run, by its name |
| writes | a second model, `model-int8`, under `model-int8/<experiment>/<run>/` |
| the next steps | read either one: `step.input("model")` or `step.input("model-int8")` |

A transform that only some runs need is the same step with a `when=`: see
[a conditional step](#5-a-conditional-step).

## One pipeline

`pipeline.py`:

```python
from pathlib import Path

from kubecore.authoring import artifact, dataset, model, pipeline, step  # the platform provides this

HERE = Path(__file__).parent

with pipeline("ml-pipeline") as p:
    check = step("data-check", kind="evaluate", inputs=["dataset"])
    prepare = step("prepare", kind="transform", needs=[check], inputs=["dataset"], produces=[dataset("clean")])
    train = step("train", kind="train", gpu=True, needs=[prepare], walltime="2h",
                 reads=["experiment", "train"], produces=[model("model")])
    evaluate = step("evaluate", kind="evaluate", needs=[prepare, train], reads=["evaluate"],
                    produces=[artifact("report")])
    export = step("export-model", kind="transform", needs=[train], reads=["export"],
                  when="{{workflow.parameters.export-format}} != none", produces=[artifact("exported")])
    register = step("register-model", kind="publish", needs=[train, evaluate, export], reads=["registration"])

if __name__ == "__main__":
    p.write(HERE / "out" / "raw-workflow-template.yaml")
```

A step runs after every step in its `needs=`. `evaluate` and `export-model` both wait for `train`, so they can
run side by side.

Try it on your machine, one step after the other ([Run a step locally](step-run.md)):

```bash
kaosctl lint
kaosctl step run data-check --input dataset=./toy
kaosctl step run prepare --input dataset=./toy
kaosctl step run train
kaosctl step run evaluate
```

Next: [How steps use datasets](steps-and-datasets.md).
