# 6. Produce a dataset

You have a step that produces a dataset. `prepare` declares it, and writes the files into its folder:

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:19:20"
```

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:10:10"
```

`step.output("clean")` is an empty folder. What it holds when `step.result()` is called becomes the dataset.

`dataset("clean")` in the app `myapp` is the dataset `dataset-myapp-clean`: the app's name in the middle, so two apps
of a project never write the same dataset. Code uses the short name, `clean`, everywhere. Run `kaosctl step run` in a
folder named `myapp` and the step says so ([Try it locally](try-it-locally.md)):

```text
  read    clean: dataset-myapp-clean at b2e7b6573672
```

## What a run does with it

- **It seals a version.** When `step.result()` runs, the files of the folder become one version of the dataset. A
  version never changes afterwards, and the steps after `prepare` in the same run read exactly that version.
- **Only the difference is stored.** The folder is compared with the last version. A run that writes the same
  content makes no new version. A run that changes one file uploads one file. Keep each file at the same path from
  run to run.
- **The newest version moves only when the run asks.** Until the run form has a field for it, the run's advanced
  config holds the request, with the name from `produces=`:

```yaml title="advanced config of the run"
--8<-- "examples/first-pipeline/produce/runs/promote.yaml"
```

  A run without it still seals its version, and `latest` stays where it is. An experiment does not change what other
  pipelines read. When two runs ask at once, the second one writes its version again on top of the first and then
  moves `latest`: `latest` is always one run's complete version.
- **A step that fails leaves no version.** The next attempt writes it once.
- **Only the app that declares the dataset in `produces=` writes it.** People and other pipelines read it.

A step that produces a dataset runs on the platform's own machines for now. Its neighbours may run on HPC
([page 9](hpc.md)).

## Read it from another pipeline

A second pipeline reads the dataset like any dataset: a setting holds the repository name, and the step declares it.

```yaml title="config/config.yaml"
--8<-- "examples/second-pipeline/config/config.yaml"
```

```yaml title="config/clean.yaml"
--8<-- "examples/second-pipeline/config/clean.yaml"
```

```python title="pipeline.py" hl_lines="7"
--8<-- "examples/second-pipeline/pipeline.py"
```

```python title="steps/evaluate/app/entry.py" hl_lines="7"
--8<-- "examples/second-pipeline/steps/evaluate/app/entry.py"
```

On the run form of the second pipeline the field `clean` offers your project's datasets and their versions,
`dataset-myapp-clean` among them. `latest` is the version a run of `myapp` promoted last.

## Rules

- A dataset has one producing step in one pipeline. Two steps producing `dataset("clean")` fail the check.
- Names use lowercase letters, digits and hyphens, at most 40 characters, and do not start with `kaos-`.
- A folder named `.kaos/` is the platform's. A dataset output may not hold files in it.
- `step.check("clean", min_files=10)` makes `step.result()` fail, and save nothing, when the folder holds fewer files.

Next: [Bigger machines](bigger-machines.md).
