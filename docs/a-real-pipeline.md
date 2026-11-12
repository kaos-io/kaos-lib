# 11. A real pipeline

You have used every part of a step. The yolo pipeline uses them all in six steps: it trains a YOLO pose model on
labelled images, makes an INT8 version of it, and registers the result. This page reads its `pipeline.py` with
what you know. The yolo guide ([yolo pipeline guide](https://novelcore.github.io/yolo-pipelines-template/)) holds what is
specific to it: the dataset layout, every form field and the Slurm notes.

```python title="pipeline.py" hl_lines="26 28 32 37 41"
--8<-- "examples/yolo-pipeline/pipeline.py"
```

| step | kind | what it does | what you know from |
|---|---|---|---|
| `config-validation` | `control` | checks that the form values fit together, before any machine is paid for | a `control` step handles no data: no `inputs=`, no `produces=` |
| `prepare-data` | `transform` | writes the run's dataset again as the dataset `prepared`, all of it or a sample | `inputs=` and `produces=dataset(...)` ([page 4](read-data.md), [6](produce-a-dataset.md)) |
| `model-training` | `train` | trains on a GPU on exactly the version `prepare-data` wrote; logs to MLflow | `gpu=True` ([7](bigger-machines.md)), `walltime=` ([9](hpc.md)), checkpoints ([8](long-jobs.md)) |
| `qat-finetune` | `train` | goes on training in a way that prepares the model for INT8 | `when=`, below |
| `model-quantization` | `transform` | makes the INT8 model and compares it with the full one | `when=` |
| `model-registration` | `publish` | registers the best checkpoint in MLflow | `kind="publish"` runs on the platform's machines |

## The step that writes a dataset

`prepare-data` is the smallest step of the pipeline, and it is the one that writes the dataset every later step reads:

```python title="steps/prepare_data/app/entry.py" hl_lines="8 9 13 17"
--8<-- "examples/yolo-pipeline/steps/prepare_data/app/entry.py"
```

- `ctx.params["data"]` holds the section `data` of `config/`, because `reads=["data"]` names it.
- `step.input("dataset")` is the version picked on the form, and `step.output("prepared")` is the folder that becomes a
  version of `dataset-<app>-prepared`.
- `step.check("prepared", min_files=2)` makes `step.result()` save nothing when the folder holds fewer than two files.
- `SystemExit("...")` with a message ends the step as failed. The message is in the log.

## A step that runs only sometimes

`qat-finetune` and `model-quantization` have a `when=`. Its condition holds the value of a run-form field, written
`{{workflow.parameters.quantization-mode}}` ([page 5](pass-things-on.md#a-step-that-runs-only-sometimes)); the field name
is the setting's path with dashes ([page 3](settings.md)). With the default `quantization-mode` of `none`, both steps are
skipped.

A skipped step leaves no result. `model-registration` needs `model-quantization` and still runs, because it asks for
that step's result only when it exists: `step.upstream("model-quantization", optional=True)` is `None` for a step that
did not run ([page 5](pass-things-on.md)).

## Run it small first

Create a pipeline from the YOLO template and put a YOLO dataset in your project (the yolo guide shows the layout).
On the run form, pick the dataset and set `data-sample_size` to `50` and `data-seed` to any number. `prepare-data` keeps 50
images of each split, the same 50 for the same seed. The run is short. When it works, set `data-sample_size` empty and run the full dataset on a GPU or on Slurm.

You have now read a whole pipeline. Next: [Principles](principles.md) explains why everything works the way it does,
and the [Reference](reference.md) holds the look-up tables.
