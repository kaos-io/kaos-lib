# Move to kaos-lib 0.5

kaos-lib 0.5 changes how a step is written. Every app changes once. An app written for 0.4 does not run on a
platform that uses 0.5, and the pull request check tells you so before you merge.

The change in one sentence: a step no longer takes arguments or reads variables; it calls `step.start()`, names
its inputs and outputs, and ends with `step.result()`.

It takes three steps:

1. Run `kaosctl lint --fix`, then choose a `kind=` for every step.
2. Rewrite each `steps/<name>/app/entry.py` with the table below.
3. Run `kaosctl lint`, then try each step with `kaosctl step run <step>`.

## 1. `pipeline.py`

```bash
pip install --upgrade "kaos-lib>=0.5"
kaosctl lint --fix
```

`--fix` makes the changes that are the same in every app:

| before | after | done by `--fix` |
| --- | --- | --- |
| `hpc_time_limit="12h"` | `walltime="12h"` | yes |
| `outputs=["training-result"]` | removed: the step calls `step.result(...)` | yes |
| no `kind=` | `kind="choose one: ingest \| transform \| ..."`, listing the six kinds | a placeholder: you choose |

The placeholder is not a kind, so `kaosctl lint` keeps failing until you replace it. Choose what the step does:

| kind | the step |
| --- | --- |
| `ingest` | brings data in from outside |
| `transform` | turns data into other data: preprocess, filter, split, convert |
| `train` | trains a model |
| `evaluate` | measures a model or a dataset |
| `publish` | registers or delivers a result |
| `control` | decides or coordinates, and does no data work itself |

Then add by hand what `--fix` cannot know:

| add | when |
| --- | --- |
| `inputs=["dataset"]` | the step reads a dataset. Name the setting that holds the reference (`dataset: my-data@v3` in `config/`). |
| `produces=[model("model")]` | the step saves a model |
| `produces=[artifact("report")]` | the step saves other files of the run |
| `produces=[dataset("clean")]` | the step writes a dataset that later steps or runs read |

Before:

```python
load = step("load", reads=["dataset"], outputs=["dataset-info"])
train = step("train", gpu=True, needs=[load], reads=["experiment", "dataset", "train"],
             hpc_time_limit="12h", outputs=["training-result"])
```

After:

```python
from kubecore.authoring import artifact, dataset, model, pipeline, step

train = step("train", kind="train", gpu=True, reads=["experiment", "train"], inputs=["dataset"],
             walltime="12h", produces=[model("model")])
```

A step whose only job was to resolve the dataset and pass its commit on is no longer needed: delete it. The
platform pins every input before the first step starts.

## 2. Each step's `entry.py`

| before | after |
| --- | --- |
| `parser.add_argument("--params")`, `yaml.safe_load(args.params)` | `ctx = step.start()`, then `ctx.params` |
| `parser.add_argument("--training-result")`, `json.loads(...)` | `step.upstream("train").values` |
| `os.environ["KUBECORE_RUN_ID"]` | `ctx.run` |
| `os.environ["CHECKPOINT_BUCKET"]`, `OUTPUTS_REPO` | not needed: `step.output()` saves to the right place |
| `cfg["experiment"]["name"]` for a path | `ctx.experiment` |
| `datasets.DatasetRef.parse(cfg["dataset"])`, `datasets.resolve(...)`, `datasets.materialize(...)` | `step.input("dataset")` |
| `outputs.run(app, experiment, run, kind) ... r.save(folder) ... r.finish(...)` | write into `step.output("model")`; `step.result()` saves it |
| passing a path, a commit or a run name to the next step | nothing: the next step calls `step.input("model")` |
| `Path("/work/output/<name>.json").write_text(json.dumps(...))` | `step.result(key=value, ...)` |
| `lock.record(...)`, `lock.write(...)` | nothing: reads and writes are recorded for you |
| `from kubecore import ...`, the `kubecore` and `kaos-cli` commands | `from kaos_lib import ...`, `kaosctl` |

Before:

```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    parser.add_argument("--dataset-info", default="{}")
    args, _ = parser.parse_known_args()
    cfg = yaml.safe_load(args.params)
    ref = datasets.DatasetRef.parse(cfg["dataset"])
    commit = datasets.resolve(ref)
    data = datasets.materialize(ref.with_commit(commit))
    weights = train(data, cfg["train"])
    run = os.environ.get("KUBECORE_RUN_ID") or "local"
    with outputs.run(os.environ["CHECKPOINT_BUCKET"], cfg["experiment"]["name"], run) as r:
        r.save(weights)
        out_commit = r.finish({"dataset_commit": commit})
    out = Path("/work/output")
    out.mkdir(parents=True, exist_ok=True)
    (out / "training-result.json").write_text(json.dumps({"commit": out_commit, "dataset_commit": commit}))
```

After:

```python
from kaos_lib import step


def main():
    ctx = step.start()
    data = step.input("dataset")
    accuracy = train(data, ctx.params["train"], save_to=step.output("model"))
    step.result(accuracy=accuracy)
```

What changes in behaviour:

- **A step must end with `step.result()`.** A step that ends without it fails.
- **A step reads only what the run pinned.** `datasets.resolve` or `datasets.materialize` of a dataset that is
  not in the step's `inputs=` is refused inside a step.
- **A missing result is never empty.** In 0.4 a step that wrote no result handed `{}` to the next one. Now the
  next step fails and names it, unless it asks with `step.upstream("x", required=False)`.
- **A result is small.** At most 8 KiB. Log metrics to MLflow; write anything larger into an artifact.

## 3. Check and try

```bash
kaosctl lint                       # no errors: L-E06, L-E07 and L-E08 are the ones about this change
kaosctl step run train --input dataset=./a-few-files
```

| check | it finds |
| --- | --- |
| [L-E06](lint/L-E06.md) | `hpc_time_limit=` or `outputs=` still in `pipeline.py` |
| [L-E07](lint/L-E07.md) | a step without a `kind`, or with a wrong `inputs=` or `produces=` |
| [L-E08](lint/L-E08.md) | a step whose code still takes `--params` or reads a variable that is no longer set |

[Run a step locally](step-run.md) explains `kaosctl step run`.

## What else changed

| in 0.4 | in 0.5 |
| --- | --- |
| `import kubecore`, the commands `kubecore` and `kaos-cli` | removed: `import kaos_lib`, `kaosctl` |
| `kaos_lib.errors.KubecoreError` | `kaos_lib.errors.KaosLibError` |
| `runtime.context().dataset_ref`, `.dataset_commit`, `.workflow` | removed: `step.input()`, and `ctx.run` |
| `lock.write()` and the artifact `data.lock.json` on the MLflow run | one `ledger/<step>.json` per step, written for you ([Results](results.md)). `kaosctl run --lock` reads both. |
| the MLflow tags `kaos_lib.data.<repository>.commit` | unchanged |
| `outputs.run(...)`, `outputs.write_run(...)` | still there for scripts outside a pipeline; a step uses `step.output()` |
| the path of a model: `checkpoints/<experiment>/<run>/` | `<name>/<experiment>/<run>/`, where `<name>` is the name in `model("<name>")`. Name it `checkpoints` to keep the old path. |

The Dockerfile, `config/`, checkpoints ([Long runs](checkpoint.md)), progress and MLflow calls do not change.
