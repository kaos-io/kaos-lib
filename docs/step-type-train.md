# train

## What it is for

A `train` step trains a model. It must produce a model. It is the step that most often needs a time limit and
checkpoints, so that a run cut short continues instead of starting over.

## The contract

| | |
|---|---|
| **Must** | produce at least one model: `produces=[model("name")]`. Write at least one file into each output |
| **May** | read datasets (`inputs=`) and earlier steps (`needs=`); also produce artifacts (a log, plots) or a dataset; set `gpu=True`, `idle_timeout=`, `when=` |
| **Must not** | nothing more than every step must keep to ([the contract](contract.md#what-you-write)) |

## Where it runs

On the platform's own machines or on HPC (Slurm). A train step that also produces a dataset runs on the platform's own
machines: the run form offers it no HPC class.

## What the platform does

- Checks, when the pipeline is built, that `produces=` holds a model.
- Keeps the model of each run in its own folder, `<name>/<experiment>/<run>/`, so a later run never overwrites it
  ([models and artifacts](data-writes.md#models-and-artifacts)).
- Continues a step that saved progress ([Long jobs](long-jobs.md)) from its newest checkpoint when its machine is lost or its job ends. You set no time limit.
- Ends a GPU step that shows no GPU use and no new log line for 20 minutes, as idle (`idle_timeout=` changes it).

The type `train` adds the rule that the step produces a model.

## A complete minimal example

```python title="pipeline.py"
--8<-- "examples/kinds/train/pipeline.py:6:8"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/kinds/train/steps/train/app/entry.py"
```

```yaml title="config/train.yaml"
--8<-- "examples/kinds/train/config/train.yaml"
```

```yaml title="config/dataset.yaml"
--8<-- "examples/kinds/train/config/dataset.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/kinds/train/config/config.yaml"
```

`checkpoint.load` starts a first run at the default and a continued run where the last one stopped. A later step reads
the model with `needs=[train]` and `step.input("model")`.

## Common mistakes

| the mistake | what you get |
|---|---|
| no model in `produces=` | `kaosctl lint`: `L-E07`, `Step 'train': a train step produces a model. Add produces=[model("name")], or give the step the kind of the work it does (ingest, transform, evaluate, publish, control).` The platform's check says the same with a small `s` |
| the model folder is empty | `output 'model' is empty: the step wrote no files into ...` and nothing is saved |

## Related

[Step types](step-types.md) · [Long jobs](long-jobs.md) · [Train, checkpoint and resume](flow-training.md) ·
[Bigger machines](bigger-machines.md) · [HPC (Slurm)](hpc.md) · [GPUs on HPC (Slurm)](gpus-on-hpc.md) · [Your contract with the platform](contract.md)
