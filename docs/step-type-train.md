# train

## What it is for

A `train` step trains a model. It must produce a model. It is the step that most often needs a time limit and
checkpoints, so that a run cut short continues instead of starting over.

## The contract

| | |
|---|---|
| **Must** | produce at least one model: `produces=[model("name")]`. Write at least one file into each output |
| **May** | read datasets (`inputs=`) and earlier steps (`needs=`); also produce artifacts (a log, plots) or a dataset; set `gpu=True`, `walltime=` (the default of the run form's time limit), `resumable=`, `checkpoint_every=`, `idle_timeout=`, `when=` |
| **Must not** | nothing more than every step must keep to ([the contract](contract.md#what-you-write)) |

## Where it runs

On the platform's own machines or on HPC (Slurm). A train step that also produces a dataset runs on the platform's own
machines: the run form offers it no HPC class.

## What the platform does

- Checks, when the pipeline is built, that `produces=` holds a model.
- Keeps the model of each run in its own folder, `<name>/<experiment>/<run>/`, so a later run never overwrites it
  ([models and artifacts](data-writes.md#models-and-artifacts)).
- Adds the run form's field `<step>-walltime`, where whoever starts the run chooses the time limit. `walltime=` in
  `pipeline.py` is only its default, and without it the default is 4 hours. When the step declares `checkpoint_every=`, the
  form also has `<step>-checkpoint-every`, which `checkpoint_every=` defaults.
- Runs a step that declares `resumable=` again, from its newest checkpoint, when it reaches its time limit, loses its
  machine or exits with code 85: at most 5 times after the first run ([Long jobs](long-jobs.md)).
- Ends a GPU step that shows no GPU use and no new log line for 20 minutes, as idle (`idle_timeout=` changes it).
- `kaosctl lint` warns when a `train` step sets `walltime=` and cannot continue (`L-W06`).

The platform does the same for any step that declares these keywords. The kind `train` adds the rule that the step
produces a model, and the warning `L-W06`.

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
| a time limit and no way to continue | `L-W06`: `Step 'train' is a training step with a time limit and is not resumable: a run cut by its time limit starts over. Add resumable=True and save checkpoints.` |
| a long GPU step that cannot continue | `L-W01`: `Step 'train' runs up to 12 h and is not resumable (...). An interruption (a lost machine, the time limit) loses all its work.` |
| a time limit longer than the site allows, not resumable | `L-E01` (an error) and, on the run form, the status `TooLongNotResumable` |
| the model folder is empty | `output 'model' is empty: the step wrote no files into ...` and nothing is saved |
| the run form's limit is not longer than the lead of `resumable=` | `train-walltime is 15 minutes, which is not longer than the 20 minutes before its limit that the step is told to save (resumable= in pipeline.py). Give the step more time.` The run is refused before it starts |

## Related

[Step types](step-types.md) · [Long jobs](long-jobs.md) · [Train, checkpoint and resume](flow-training.md) ·
[Bigger machines](bigger-machines.md) · [HPC (Slurm)](hpc.md) · [GPUs on HPC (Slurm)](gpus-on-hpc.md) · [Your contract with the platform](contract.md)
