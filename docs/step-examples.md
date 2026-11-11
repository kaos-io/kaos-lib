# Step examples

One complete, small step for each job a step does. Each example has the `step(...)` line, the whole `app/entry.py`, the
`Dockerfile`, and what the step reads, writes and does with datasets. At the end, one `pipeline.py` wires five of them
together. How a step is started and what it may do: [How a step works](steps.md).

| # | the job | example step |
| --- | --- | --- |
| 1 | [Data consumer](#1-a-data-consumer): read the dataset and compute something small | `data-check` |
| 2 | [Data preparation](#2-data-preparation): derive files that later steps reuse | `data-prepare` |
| 3 | [Dataset producer](#3-a-dataset-producer): build the files of a new dataset | `dataset-draft` |
| 4 | [Training](#4-training): GPU, MLflow, progress, checkpoints, a model | `train` |
| 5 | [Evaluation](#5-evaluation): score the model on the same data | `evaluate` |
| 6 | [Model transform](#6-a-model-transform): export or quantize a model | `export-model` |
| 7 | [Publish](#7-publish-a-model): register the model in MLflow | `register-model` |
| 8 | [Conditional step](#8-a-conditional-step): run only on a choice from the run form | `export-model` |

## The example app

The examples share one small app. Its dataset has two files, `train.csv` and `val.csv`, each with the columns `x` and
`y`. A dataset like this uses the `raw` layout ([Datasets](datasets.md)). Make one to try the examples:

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

The settings, one file each in `config/`:

`config/config.yaml`:

```yaml
defaults:
  - _self_
  - experiment
  - dataset
  - train
  - evaluate
  - export
  - registration
  - platform: live # platform-owned group; keep this line as it is
```

`config/dataset.yaml`:

```yaml
# The run's dataset: <dataset>@<version>, or <owner-project>/<dataset>@<version> for a shared one.
dataset: "dataset-default@v1"
```

`config/evaluate.yaml`:

```yaml
evaluate:
  max_mse: 0.5 # the verdict is "pass" when the error on the validation split is at most this
```

`config/experiment.yaml`:

```yaml
experiment:
  name: "my-experiment-v1" # names the MLflow experiment and the folders of your results
```

`config/export.yaml`:

```yaml
export:
  format: "none" # "none" skips the export step; "fp16" exports a half-precision copy
```

`config/registration.yaml`:

```yaml
registration:
  model_name: "my-model"
  promote_to: "" # empty = no alias; for example "champion"
```

`config/train.yaml`:

```yaml
train:
  epochs: 20
  learning_rate: 0.1
```

Every step below starts the same way. It reads `--params`, and writes each result as one JSON file with this helper:

```python
def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))
```

Each step image needs kaos-lib. Copy the `ARG KAOS_LIB_PACKAGE=...` line from your template's Dockerfile: the platform's
build replaces its value, so every example keeps the line as it is.

## 1. A data consumer

**Use it** to look at the data before anything expensive runs: count rows, check columns, find missing values. A step
that fails here stops the run before training starts.

```python
check = step("data-check", reads=["dataset"], outputs=["data-stats"])
```

`app/entry.py`:

```python
"""data-check: reads the run's dataset and writes small statistics."""
import argparse
import csv
import json
import statistics
from pathlib import Path

import yaml
from kaos_lib import datasets, progress


def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)

    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref)         # the commit the platform pinned for this run
    ref = ref.with_commit(commit)          # read exactly that commit, even if "latest" moves meanwhile
    folder = datasets.materialize(ref)     # a raw dataset: the folder with its files

    stats = {"dataset": cfg["dataset"], "dataset_commit": commit, "splits": {}}
    for i, split in enumerate(("train", "val"), start=1):
        rows = list(csv.DictReader((folder / f"{split}.csv").open()))
        if not rows:
            raise SystemExit(f"{split}.csv has no rows")
        try:
            xs = [float(r["x"]) for r in rows]
            ys = [float(r["y"]) for r in rows]
        except (KeyError, ValueError) as exc:
            raise SystemExit(f"{split}.csv: every row needs numeric x and y ({exc!r})")
        stats["splits"][split] = {"rows": len(rows), "x_mean": statistics.fmean(xs),
                                  "y_mean": statistics.fmean(ys)}
        progress.report(i, 2, unit="file")

    write_output("data-stats", stats)
    print(f"[data-check] {cfg['dataset']} @ {commit}: {stats['splits']}")


if __name__ == "__main__":
    main()
```

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# kaos-lib: copy this ARG line from your template's Dockerfile. The platform's build replaces its value.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

| | |
| --- | --- |
| reads | the setting `dataset`, and the files of the run's dataset |
| writes | `/work/output/data-stats.json` |
| datasets | `resolve` gives the commit the platform pinned. `materialize` gives the files of exactly that commit |
| on the platform's machines | the step downloads the files into its own disk |
| on HPC (Slurm) | the run form can place it on an HPC class too. The code is the same, and the data is copied next to the job |

`reads=["dataset"]` matters: the platform pins the dataset for a run only when a step lists `dataset` there.

Wrong data should end the step with a message, as `raise SystemExit("val.csv has no rows")` does. A dataset with no
files at all raises `kaos_lib.errors.EmptyDataset`, so a step can tell "no data yet" from other failures.

## 2. Data preparation

**Use it** when the next steps would all repeat the same work: scaling, resizing, converting, splitting. The step
reads the dataset once and saves the result in your outputs repository.

```python
prepare = step("data-prepare", reads=["experiment", "dataset"], outputs=["prepared-data"])
```

`app/entry.py`:

```python
"""data-prepare: standardises x and y with the train statistics and saves the result for later steps."""
import argparse
import csv
import json
import statistics
import tempfile
from pathlib import Path

import yaml
from kaos_lib import datasets, outputs, progress, runtime


def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))


def read(path):
    return [(float(r["x"]), float(r["y"])) for r in csv.DictReader(path.open())]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)
    ctx = runtime.context()                # run id and outputs repository, set by the platform

    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref)
    folder = datasets.materialize(ref.with_commit(commit))

    train, val = read(folder / "train.csv"), read(folder / "val.csv")
    mean_x, mean_y = (statistics.fmean(c) for c in zip(*train))
    std_x, std_y = (statistics.pstdev(c) or 1.0 for c in zip(*train))

    with tempfile.TemporaryDirectory() as tmp:
        for name, rows in (("train", train), ("val", val)):
            with (Path(tmp) / f"{name}.csv").open("w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["x", "y"])
                for i, (x, y) in enumerate(rows, start=1):
                    writer.writerow([(x - mean_x) / std_x, (y - mean_y) / std_y])
                    progress.report(i, len(rows), unit="row")
        (Path(tmp) / "scaling.json").write_text(json.dumps(
            {"x": [mean_x, std_x], "y": [mean_y, std_y]}))

        with outputs.run(ctx.outputs_repo, cfg["experiment"]["name"], ctx.run_id, kind="prepared") as r:
            r.save(tmp)
            out_commit = r.finish({"dataset_ref": cfg["dataset"], "dataset_commit": commit})

    write_output("prepared-data", {
        "repo": outputs.outputs_repo(ctx.outputs_repo),
        "commit": out_commit,
        "prefix": outputs.run_prefix(cfg["experiment"]["name"], ctx.run_id, "prepared"),
        "dataset_commit": commit,
        "rows": {"train": len(train), "val": len(val)},
    })


if __name__ == "__main__":
    main()
```

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# kaos-lib: copy this ARG line from your template's Dockerfile. The platform's build replaces its value.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

| | |
| --- | --- |
| reads | the run's dataset, and `experiment.name` |
| writes | the files `train.csv`, `val.csv` and `scaling.json` in your outputs repository, under `prepared/<experiment>/<run>/`. And `/work/output/prepared-data.json`: where they are, and which dataset commit they came from |
| datasets | the dataset is read at the pinned commit. The result is not a dataset: it lives in the outputs repository and is tied to one run |
| on the platform's machines | the same code |
| on HPC (Slurm) | the run form can place it on an HPC class too. The code is the same |

`r.save(tmp)` is durable at once on the run's own branch. `r.finish(...)` makes it one commit in your outputs
repository and returns the commit id. If the step is run again, it continues on the same branch ([Outputs](outputs.md)).

A later step reads the files back at that commit. The `download` helper in [example 5](#5-evaluation) does it for one
file. For a whole folder, list it first:

```python
from pathlib import Path
from kaos_lib.lakefs import LakeFS

client = LakeFS.connect()
for obj in client.list_objects(result["repo"], result["commit"], result["prefix"]):
    client.download_object(result["repo"], result["commit"], obj["path"],
                           Path("prepared") / obj["path"][len(result["prefix"]):])
```

## 3. A dataset producer

**Use it** to build the files of a new dataset or a new version: cleaned rows, a re-labelled set, merged sources.

What a step can do today, and what it cannot:

| | can a step do it? |
| --- | --- |
| build the files, and check them with the dataset's layout (`layouts.load("<layout>").validate(folder)`) | yes |
| save them in your outputs repository | yes |
| create a dataset (`datasets.create_dataset`), open a pull request (`Layout.publish`) or release a version (`datasets.release`) | no: these need the rights of a person or an administrator, and a step runs with your app's access ([Datasets](datasets.md#rights-each-call-needs)) |
| merge the pull request | no: a person merges it in lakeFS |

So the step prepares the files, and a person publishes them. A step must not try to publish by itself: it would fail.

```python
draft = step("dataset-draft", reads=["experiment", "dataset"], outputs=["dataset-draft"])
```

`app/entry.py`:

```python
"""dataset-draft: builds a cleaned copy of the run's dataset and saves it for a person to publish."""
import argparse
import csv
import json
import tempfile
from pathlib import Path

import yaml
from kaos_lib import datasets, layouts, outputs, runtime


def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)
    ctx = runtime.context()

    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref)
    source = datasets.materialize(ref.with_commit(commit))

    with tempfile.TemporaryDirectory() as tmp:
        kept = {}
        for split in ("train", "val"):
            with (source / f"{split}.csv").open() as fh:
                rows = [r for r in csv.DictReader(fh) if r["x"] and r["y"]]    # drop incomplete rows
            with (Path(tmp) / f"{split}.csv").open("w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["x", "y"])
                writer.writeheader()
                writer.writerows(rows)
            kept[split] = len(rows)

        report = layouts.load("raw").validate(tmp)       # the checks `kaosctl dataset push` will run
        if not report.ok:
            raise SystemExit(report.format())

        with outputs.run(ctx.outputs_repo, cfg["experiment"]["name"], ctx.run_id, kind="datasets") as r:
            r.save(tmp)
            out_commit = r.finish({"derived_from": cfg["dataset"], "dataset_commit": commit})

    prefix = outputs.run_prefix(cfg["experiment"]["name"], ctx.run_id, "datasets")
    repo = outputs.outputs_repo(ctx.outputs_repo)
    write_output("dataset-draft", {"repo": repo, "commit": out_commit, "prefix": prefix,
                                   "derived_from": cfg["dataset"], "dataset_commit": commit, "rows": kept})
    print(f"[dataset-draft] saved in {repo} at {out_commit}, under {prefix}")


if __name__ == "__main__":
    main()
```

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# kaos-lib: copy this ARG line from your template's Dockerfile. The platform's build replaces its value.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

| | |
| --- | --- |
| reads | the run's dataset |
| writes | the new files in your outputs repository under `datasets/<experiment>/<run>/`, and `/work/output/dataset-draft.json` with their commit and the dataset commit they came from |
| datasets | reads one pinned version. Creates none |
| on the platform's machines | the same code |
| on HPC (Slurm) | the run form can place it on an HPC class too. The code is the same |

When the run is done, a person with the rights downloads the folder and publishes it. `<commit>` and `<prefix>` are in
`dataset-draft.json`:

```bash
kaosctl dataset pull outputs-myapp@<commit> ./draft --prefix <prefix>
kaosctl dataset push ./draft dataset-clean -m "cleaned rows"      # validates, creates dataset-clean if needed, opens a pull request
kaosctl dataset release dataset-clean                              # after the pull request is merged
```

The same in Python, from your own machine after `kaosctl login`:

```python
from kaos_lib import datasets, layouts

result = layouts.load("raw").publish("./draft", "dataset-clean", "cleaned rows")   # validates, then opens a pull request
print(result.pull_url)                  # merge it there
print(datasets.release("dataset-clean"))   # after the merge: prints v1
```

## 4. Training

**Use it** to fit a model. A training step is a GPU step that reads the dataset and your settings, logs to MLflow, tells
the platform how far it is, saves its state so an interruption does not lose hours, and writes the model.

```python
train = step("train", gpu=True, needs=[check], hpc_time_limit="2h",
             reads=["experiment", "dataset", "train"], outputs=["training-result"])
```

`needs=[check]` makes training wait for the data check. `hpc_time_limit` is the longest run on HPC (Slurm): size it to
the longest training you expect.

`app/entry.py`, a plain PyTorch loop that works with any framework's training code:

```python
"""train: a PyTorch loop that logs to MLflow, reports progress and survives an interruption."""
import argparse
import csv
import json
import tempfile
from pathlib import Path

import mlflow
import torch
import yaml
from kaos_lib import checkpoint, datasets, outputs, progress, runtime
from kaos_lib.mlflow import mlflow as connect_mlflow


def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))


def load_split(path, device):
    rows = [(float(r["x"]), float(r["y"])) for r in csv.DictReader(path.open())]
    x, y = zip(*rows)
    return torch.tensor(x, device=device).unsqueeze(1), torch.tensor(y, device=device).unsqueeze(1)


def on_cpu(weights):
    return {k: v.cpu() for k, v in weights.items()}     # saved files then load on any machine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)
    ctx = runtime.context()

    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref)
    folder = datasets.materialize(ref.with_commit(commit))
    device = "cuda" if torch.cuda.is_available() else "cpu"   # a gpu=True step has a GPU
    x_train, y_train = load_split(folder / "train.csv", device)
    x_val, y_val = load_split(folder / "val.csv", device)

    connect_mlflow()                                      # tracking address and sign-in come from the platform
    mlflow.set_experiment(cfg["experiment"]["name"])

    model = torch.nn.Linear(1, 1).to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=cfg["train"]["learning_rate"])
    epochs = cfg["train"]["epochs"]

    # On a continued step the checkpoint folder already holds the last state; on a first run this is the default.
    state = checkpoint.load("state", default={"epoch": 0, "mlflow_run_id": None})
    if state["epoch"]:
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])

    with mlflow.start_run(run_id=state["mlflow_run_id"], run_name=ctx.run_id) as run:   # a continued step logs into the same run
        state["mlflow_run_id"] = run.info.run_id
        mlflow.log_params({"dataset": cfg["dataset"], "dataset_commit": commit, **cfg["train"]})

        for epoch in range(state["epoch"], epochs):
            optimizer.zero_grad()
            loss = torch.nn.functional.mse_loss(model(x_train), y_train)
            loss.backward()
            optimizer.step()

            mlflow.log_metric("train_loss", loss.item(), step=epoch)
            progress.report(epoch + 1, epochs, unit="epoch")
            state.update(epoch=epoch + 1, model=on_cpu(model.state_dict()), optimizer=optimizer.state_dict())
            checkpoint.save(state)                         # small state; large files go into checkpoint.dir()
            if checkpoint.stop_requested():                # the platform asks us to stop: we are saved, so end
                checkpoint.exit_for_restart()

        with torch.no_grad():
            val_mse = torch.nn.functional.mse_loss(model(x_val), y_val).item()
        mlflow.log_metric("val_mse", val_mse)

        with tempfile.TemporaryDirectory() as tmp:
            torch.save(on_cpu(model.state_dict()), Path(tmp) / "model.pt")
            mlflow.log_artifact(str(Path(tmp) / "model.pt"), artifact_path="model")   # for the model registry
            with outputs.run(ctx.outputs_repo, cfg["experiment"]["name"], ctx.run_id, kind="models") as r:
                r.save(tmp)
                out_commit = r.finish({"dataset_ref": cfg["dataset"], "dataset_commit": commit,
                                       "mlflow_run_id": run.info.run_id})

    write_output("training-result", {
        "model": {"repo": outputs.outputs_repo(ctx.outputs_repo), "commit": out_commit,
                  "path": outputs.run_prefix(cfg["experiment"]["name"], ctx.run_id, "models") + "model.pt"},
        "dataset": cfg["dataset"], "dataset_commit": commit,
        "val_mse": val_mse, "mlflow_run_id": run.info.run_id,
    })


if __name__ == "__main__":
    main()
```

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# The platform's GPU machines mount the NVIDIA driver here; keep these two lines so the image also works elsewhere.
ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/nvidia/lib
ENV PATH=/usr/local/nvidia/bin:${PATH}
# kaos-lib: copy this ARG line from your template's Dockerfile. The platform's build replaces its value.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}" "torch==2.5.1" "mlflow-skinny>=3,<4"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

| | |
| --- | --- |
| reads | the run's dataset, `experiment` and `train` |
| writes | to MLflow: parameters, `train_loss` per epoch, `val_mse` and the model file. The platform adds the dataset commit when the run ends. To your outputs repository: `models/<experiment>/<run>/model.pt`. `/work/output/training-result.json`: where the model is, the dataset commit, the key metric and the MLflow run id |
| datasets | one pinned commit, recorded on the MLflow run when it ends, by the platform ([How steps use datasets](steps-and-datasets.md#what-is-recorded)) |
| progress | `progress.report(epoch + 1, epochs, unit="epoch")` |
| interruption | `checkpoint.save(state)` after each epoch, `checkpoint.load("state", default=...)` at the start, `exit_for_restart()` when the platform asks |

**Three frameworks need no code at all.** Ultralytics (YOLO), PyTorch Lightning and the Hugging Face `Trainer` report
their progress by themselves, and kaos-lib saves and restores their checkpoints. You only point them at the checkpoint
folder:

```python
from kaos_lib import checkpoint
YOLO("yolo11n.pt").train(data="data.yaml", project=str(checkpoint.dir()), name="run", exist_ok=True)
```

With one of them, drop the `progress` and `checkpoint.save` lines of the loop above. Keep `mlflow()`,
and the outputs and `training-result` code. See [Progress](progress.md) and [Long runs](checkpoint.md).

| | on the platform's machines | on HPC (Slurm) |
| --- | --- | --- |
| where it runs | a GPU class chosen on the run form | an HPC class chosen on the run form |
| the data | downloaded by the step | copied next to the job before it starts |
| the time | until the step ends | at most `hpc_time_limit`. A step that saved a checkpoint is continued, in another job |
| an interruption | the step runs again, or continues from its checkpoint | the step is told to stop shortly before the limit: it saves and exits with code 85 |
| cores | the whole machine | on a shared node, size worker pools with `runtime.usable_cpus()` ([Run context](runtime.md)) |

## 5. Evaluation

**Use it** to judge a model on data it did not train on, and to write the verdict that later steps check.

```python
evaluate = step("evaluate", needs=[train], reads=["experiment", "dataset", "evaluate"],
                outputs=["evaluation-result"])
```

`app/entry.py`:

```python
"""evaluate: scores the trained model on the validation split of the same pinned dataset."""
import argparse
import csv
import json
import tempfile
from pathlib import Path

import torch
import yaml
from kaos_lib import datasets, outputs, runtime
from kaos_lib.lakefs import LakeFS
from kaos_lib.mlflow import mlflow as connect_mlflow


def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))


def download(repo, commit, path, dest):
    """One file of the outputs repository, at exactly the commit the earlier step reported."""
    LakeFS.connect().download_object(repo, commit, path, dest)
    return dest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    parser.add_argument("--training-result", default="{}")
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)
    result = json.loads(args.training_result)
    ctx = runtime.context()

    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref)
    if commit != result["dataset_commit"]:                 # cannot happen with the platform's pin; say so if it does
        raise SystemExit(f"this step reads {commit}, training read {result['dataset_commit']}")
    folder = datasets.materialize(ref.with_commit(commit))

    with tempfile.TemporaryDirectory() as tmp:
        model_file = download(result["model"]["repo"], result["model"]["commit"], result["model"]["path"],
                              Path(tmp) / "model.pt")
        model = torch.nn.Linear(1, 1)
        model.load_state_dict(torch.load(model_file, map_location="cpu"))

    rows = [(float(r["x"]), float(r["y"])) for r in csv.DictReader((folder / "val.csv").open())]
    x, y = zip(*rows)
    with torch.no_grad():
        mse = torch.nn.functional.mse_loss(model(torch.tensor(x).unsqueeze(1)), torch.tensor(y).unsqueeze(1)).item()
    verdict = "pass" if mse <= cfg["evaluate"]["max_mse"] else "fail"

    client = connect_mlflow()
    client.log_metric(result["mlflow_run_id"], "eval_mse", mse)
    client.set_tag(result["mlflow_run_id"], "eval_verdict", verdict)

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "metrics.json").write_text(json.dumps({"mse": mse, "verdict": verdict, "rows": len(rows)}))
        with outputs.run(ctx.outputs_repo, cfg["experiment"]["name"], ctx.run_id, kind="evaluation") as r:
            r.save(tmp)
    write_output("evaluation-result", {"mse": mse, "verdict": verdict, "dataset_commit": commit})
    print(f"[evaluate] mse={mse:.4f} verdict={verdict}")


if __name__ == "__main__":
    main()
```

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# kaos-lib: copy this ARG line from your template's Dockerfile. The platform's build replaces its value.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}" "torch==2.5.1" "mlflow-skinny>=3,<4"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

| | |
| --- | --- |
| reads | `--training-result` (where the model is and the commit it trained on), the model file, the run's dataset |
| writes | `eval_mse` and the tag `eval_verdict` on the training run in MLflow, `metrics.json` in your outputs repository under `evaluation/<experiment>/<run>/`, and `/work/output/evaluation-result.json` |
| datasets | the same commit as training. The step checks it: `resolve` must give `training-result`'s `dataset_commit`, and with the platform's pin it always does |
| on the platform's machines | the same code |
| on HPC (Slurm) | the run form can place it on an HPC class too. The code is the same |

`download` reads one file at exactly the commit that `training-result` names, so the model cannot change under the
step. The step ends with exit code `0` even when the verdict is `fail`: the verdict is a result, and the next step
decides what to do with it.

## 6. A model transform

**Use it** to turn one model into another: export, quantize, convert, compress. The step reads a model from your outputs
repository and writes a new file next to it.

```python
export = step("export-model", needs=[train], reads=["experiment", "export"],
              when="{{workflow.parameters.export-format}} != none", outputs=["export-result"])
```

`app/entry.py`:

```python
"""export-model: turns the trained model into a half-precision copy and saves it."""
import argparse
import json
import tempfile
from pathlib import Path

import torch
import yaml
from kaos_lib import outputs, runtime
from kaos_lib.lakefs import LakeFS


def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    parser.add_argument("--training-result", default="{}")
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)
    result = json.loads(args.training_result)
    ctx = runtime.context()

    if cfg["export"]["format"] != "fp16":
        raise SystemExit(f"export.format {cfg['export']['format']!r} is not supported here: use fp16")

    src = result["model"]
    with tempfile.TemporaryDirectory() as tmp:
        LakeFS.connect().download_object(src["repo"], src["commit"], src["path"], Path(tmp) / "in.pt")
        weights = torch.load(Path(tmp) / "in.pt", map_location="cpu")
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        torch.save({k: v.half() for k, v in weights.items()}, out_dir / "model-fp16.pt")
        with outputs.run(ctx.outputs_repo, cfg["experiment"]["name"], ctx.run_id, kind="exports") as r:
            r.save(out_dir)
            commit = r.finish({"exported_from": src["commit"], "format": "fp16"})

    write_output("export-result", {
        "format": "fp16", "repo": src["repo"], "commit": commit,
        "path": outputs.run_prefix(cfg["experiment"]["name"], ctx.run_id, "exports") + "model-fp16.pt",
    })


if __name__ == "__main__":
    main()
```

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# kaos-lib: copy this ARG line from your template's Dockerfile. The platform's build replaces its value.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}" "torch==2.5.1"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

| | |
| --- | --- |
| reads | `--training-result`, the model file, `export.format` |
| writes | `model-fp16.pt` in your outputs repository under `exports/<experiment>/<run>/`, and `/work/output/export-result.json` |
| datasets | none. It does not read data, so it does not list `dataset` in `reads=` |
| on the platform's machines | the same code |
| on HPC (Slurm) | the same as above. A transform that needs a GPU declares `gpu=True` and runs the same code |

A model that is big or needs scratch space asks for it with `disk="20Gi"` on the `step(...)` line.

## 7. Publish a model

**Use it** as the last step: put the model in the MLflow model registry, so people and other systems find it by name and
version.

```python
register = step("register-model", needs=[train, evaluate, export], reads=["registration"],
                outputs=["registration-result"])
```

`app/entry.py`:

```python
"""register-model: puts the trained model in the MLflow model registry, if it passed evaluation."""
import argparse
import json
from pathlib import Path

import yaml
from kaos_lib.mlflow import mlflow as connect_mlflow
from mlflow.exceptions import MlflowException


def write_output(name, value):
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    parser.add_argument("--training-result", default="{}")
    parser.add_argument("--evaluation-result", default="{}")
    parser.add_argument("--export-result", default="{}")          # "{}" when the export step was skipped
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)
    training, evaluation, export = (json.loads(a) for a in
                                    (args.training_result, args.evaluation_result, args.export_result))

    if evaluation.get("verdict") != "pass":
        write_output("registration-result", {"registered": False, "reason": "the evaluation did not pass"})
        return

    name = cfg["registration"]["model_name"]
    client = connect_mlflow()
    try:
        client.create_registered_model(name)
    except MlflowException as exc:
        if exc.error_code != "RESOURCE_ALREADY_EXISTS":
            raise

    run_id = training["mlflow_run_id"]
    version = client.create_model_version(
        name, source=f"runs:/{run_id}/model", run_id=run_id,
        tags={"dataset": training["dataset"], "dataset_commit": training["dataset_commit"],
              "model_commit": training["model"]["commit"], "eval_mse": str(evaluation["mse"]),
              "fp16_copy": export.get("path", "none")})
    if cfg["registration"]["promote_to"]:
        client.set_registered_model_alias(name, cfg["registration"]["promote_to"], version.version)

    write_output("registration-result", {"registered": True, "name": name, "version": version.version})
    print(f"[register-model] {name} version {version.version}")


if __name__ == "__main__":
    main()
```

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
# kaos-lib: copy this ARG line from your template's Dockerfile. The platform's build replaces its value.
ARG KAOS_LIB_PACKAGE="kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/50aee081e1bb031ef199eefe68e62ee35e6281d7.zip"
RUN pip install --no-cache-dir "${KAOS_LIB_PACKAGE}" "mlflow-skinny>=3,<4"
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.entry"]
```

| | |
| --- | --- |
| reads | `--training-result`, `--evaluation-result`, `--export-result` and `registration` |
| writes | a registered model version in MLflow, tagged with the dataset, its commit, the model's commit in your outputs repository and the evaluation result. `/work/output/registration-result.json` |
| datasets | none read. The version carries the dataset commit as a tag, so the model always points back to its data |
| on the platform's machines | the same code |
| on HPC (Slurm) | the run form can place it on an HPC class too. The code is the same |

The step does not register a model that did not pass. It writes `{"registered": false, ...}` and ends with exit code `0`.
`promote_to` sets an alias such as `champion` on the new version. Leave it empty to set none.

## 8. A conditional step

**Use it** for work that only some runs need: export, quantization, an extra report. The condition is a value from the run
form, and the step is skipped when it is false.

```python
export = step("export-model", needs=[train], reads=["experiment", "export"],
              when="{{workflow.parameters.export-format}} != none", outputs=["export-result"])
```

The name inside `{{workflow.parameters.…}}` is the setting's path in `config/` with `.` written as `-`: the setting
`export.format` is `export-format`. A form choice is any setting: here `export.format` is `"none"` by default, so a
run exports only when someone chooses `fp16`. Compare with `==` or `!=`:

```python
when="{{workflow.parameters.export-format}} == fp16"
```

What happens when the step is skipped:

| | |
| --- | --- |
| the step | is shown as skipped. Its code does not run |
| steps that need it | still run |
| their argument `--export-result` | is `{}` |

So a step that needs a conditional step must accept `{}`. The register step above does: `export.get("path", "none")`,
and `--export-result` defaults to `"{}"`. The code of the conditional step itself is [example 6](#6-a-model-transform).

## One pipeline

The five steps wired together: check the data, train, evaluate, export only when asked, then register.

`pipeline.py`:

```python
from pathlib import Path

from kubecore.authoring import pipeline, step  # the platform's engine provides this

HERE = Path(__file__).parent

with pipeline("ml-pipeline") as p:
    check = step("data-check", reads=["dataset"], outputs=["data-stats"])
    train = step("train", gpu=True, needs=[check], hpc_time_limit="2h",
                 reads=["experiment", "dataset", "train"],
                 outputs=["training-result"])
    evaluate = step("evaluate", needs=[train],
                    reads=["experiment", "dataset", "evaluate"],
                    outputs=["evaluation-result"])
    export = step("export-model", needs=[train],
                  reads=["experiment", "export"],
                  when="{{workflow.parameters.export-format}} != none",
                  outputs=["export-result"])
    register = step("register-model", needs=[train, evaluate, export],
                    reads=["registration"],
                    outputs=["registration-result"])

if __name__ == "__main__":
    p.write(HERE / "out" / "raw-workflow-template.yaml")
```

The settings it uses are the ones shown in [The example app](#the-example-app). A step runs after every step in its
`needs=`, and the steps `evaluate` and `export-model` both wait for `train`, so they can run side by side.

Next: [How steps use datasets](steps-and-datasets.md).
