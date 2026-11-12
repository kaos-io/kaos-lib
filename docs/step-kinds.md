# Step kinds

Every step says what it is for with `kind=`. The kind is a contract: the platform checks it when it builds the
pipeline, and `kaosctl lint` checks it as you write.

| kind | what it is for | it must | it may not | where it runs |
|---|---|---|---|---|
| `ingest` | bringing data in from outside | produce at least one dataset | | the platform's own machines |
| `transform` | turning data into something else | produce at least one thing: a dataset, a model or an artifact | | the platform's own machines or HPC (Slurm) |
| `train` | training a model | produce at least one model | | the platform's own machines or HPC (Slurm) |
| `evaluate` | measuring a model or a dataset | | produce a dataset or a model: it writes reports (artifacts) only | the platform's own machines or HPC (Slurm) |
| `publish` | delivering a result | | produce anything | the platform's own machines |
| `control` | steering the run | | take `inputs=`, or produce anything | the platform's own machines |

A step that breaks its kind is refused when the pipeline is built, with one sentence that names the step and says what
to add or which kind it should have ([the sentences](when-something-goes-wrong.md#refused-when-the-pipeline-is-built)).
Every step, whatever its kind, can set `walltime=`, the longest it may run ([Long jobs](long-jobs.md)), and `when=`, or
end itself with `step.skip("reason")` ([Conditions and skipping](conditions-and-skipping.md)). A step that produces a dataset
runs on the cluster, whatever its kind ([Produce a dataset](produce-a-dataset.md#where-it-runs)).

What a step hands on is the same for all kinds: the values of `step.result(...)` reach the steps that need it
(`step.upstream("name")`), and what it wrote into its `produces=` folders is saved when `step.result()` runs. The
sections below say what that is for each kind.

## ingest

**For** a step that brings data in from outside: a download, a copy from a source you own. It writes the new files into
a dataset, so it must produce one.

```python title="pipeline.py"
--8<-- "examples/flows/ingest/pipeline.py"
```

```python title="steps/fetch/app/entry.py"
--8<-- "examples/flows/ingest/steps/fetch/app/entry.py"
```

```yaml title="config/source.yaml"
--8<-- "examples/flows/ingest/config/source.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/ingest/config/config.yaml"
```

**It hands on** a new version of the dataset `raw`, and the values you give `step.result(...)`. The steps after it read the
dataset with `step.input("raw")` ([Bring data in](bring-data-in.md)).

## transform

**For** a step that turns data into other data: preprocess, filter, split, convert. It must produce something; most
transforms produce a dataset.

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py"
```

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py"
```

**It hands on** a new version of the dataset `clean`, and `files` and `dropped` as values. The steps after it read the
dataset with `step.input("clean")` and the values with `step.upstream("prepare")`.

## train

**For** a step that trains a model. It must produce a model. It is the step that most often needs a time limit and
checkpoints, so that a run cut short continues instead of starting over ([Long jobs](long-jobs.md)).

```python title="pipeline.py"
--8<-- "examples/first-pipeline/long-job/pipeline.py"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/first-pipeline/long-job/steps/train/app/entry.py"
```

**It hands on** the model, a folder of files saved with the run, and values such as the number of epochs. A later step
reads the model with `step.input("model")`.

## evaluate

**For** a step that measures: a model, a dataset, a result of an earlier step. It writes reports as artifacts, and may
not produce a dataset or a model. A step that makes a dataset is a `transform`; one that makes a model is a `train`.

```python title="steps/hello_world/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/hello_world/app/entry.py"
```

**It hands on** the artifact (a report, files that belong to this run) and the values, such as a score. Nothing
it writes changes what other pipelines read.

## publish

**For** a step that delivers a result: registers a model, calls a service, copies files out. It writes nothing the
platform keeps, so it produces nothing. It reads what the step before it made and hands on what was delivered. The
record of the delivery (an address, an id) goes in the values of `step.result(delivered=...)`, not in a file. A `publish`
step is often run only when the evaluation passed: `when="evaluate.passed == true"` ([Conditions and skipping](conditions-and-skipping.md)).

```python title="pipeline.py"
--8<-- "examples/flows/publish/pipeline.py"
```

```python title="steps/register/app/entry.py"
--8<-- "examples/flows/publish/steps/register/app/entry.py"
```

```python title="steps/train/app/entry.py"
--8<-- "examples/flows/publish/steps/train/app/entry.py"
```

```yaml title="config/registry.yaml"
--8<-- "examples/flows/publish/config/registry.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/publish/config/config.yaml"
```

**It hands on** values only, such as the name it delivered under. It has no `produces=`, so nothing is saved for it.

## control

**For** a step that steers the run and handles no data: it checks the settings, or decides something the next steps
depend on. It has no `inputs=` and no `produces=`. A step that fails here ends the run before any machine is spent on
the steps after it.

```python title="pipeline.py"
--8<-- "examples/flows/control/pipeline.py"
```

```python title="steps/check/app/entry.py"
--8<-- "examples/flows/control/steps/check/app/entry.py"
```

```python title="steps/work/app/entry.py"
--8<-- "examples/flows/control/steps/work/app/entry.py"
```

```yaml title="config/check.yaml"
--8<-- "examples/flows/control/config/check.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/control/config/config.yaml"
```

**It hands on** values only. The next step reads them with `step.upstream("check")`; a step that needs a conditional
step waits for it either way ([Between steps](flow-between-steps.md)).
