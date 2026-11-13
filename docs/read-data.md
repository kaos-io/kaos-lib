# 4. Read data

You have one input. `prepare` reads a dataset, and `pipeline.py` and `config/dataset.yaml` say which setting holds it:

```python title="pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py:19:20"
```

```yaml title="config/dataset.yaml"
--8<-- "examples/first-pipeline/template/config/dataset.yaml"
```

```python title="steps/prepare/app/entry.py"
--8<-- "examples/first-pipeline/template/steps/prepare/app/entry.py:10:10"
```

`step.input("dataset")` returns a folder that holds the files of the dataset.

- `inputs=["dataset"]` names a top-level value of `config/` that holds a dataset reference, `dataset-<name>` with a
  version (the [forms of a reference](data-contract.md#names-and-addresses)).
- `step.input("dataset")` takes the name and nothing else. There is no version in code, so there is no way to read a
  different version from the one the run chose.

## Pick the version on the form

The field `dataset` on the run form lists your project's datasets and their versions. You pick one when you submit.
The platform fixes the choice to one exact version before the first step starts, and every step reads that version
([when a version is fixed](data-reads.md#fixed-when-the-run-starts)).

```bash
kaosctl dataset list
kaosctl dataset versions dataset-default
kaosctl dataset release dataset-default
```

`list` shows the datasets you can read, `versions` the versions of one, and `release` gives the version `latest` points
to the next version number ([what a version is](data-contract.md#what-a-version-is)).

## Add a second input

Let `hello-world` also count the files of a reference dataset. A second setting holds it, and the step names it:

```yaml title="config/reference.yaml (new)"
--8<-- "examples/first-pipeline/read-data/config/reference.yaml"
```

```yaml title="config/config.yaml" hl_lines="10"
--8<-- "examples/first-pipeline/read-data/config/config.yaml"
```

```python title="pipeline.py" hl_lines="21"
--8<-- "examples/first-pipeline/read-data/pipeline.py"
```

```python title="steps/hello_world/app/entry.py" hl_lines="1 11 13 14 17"
--8<-- "examples/first-pipeline/read-data/steps/hello_world/app/entry.py"
```

[Send it in](first-step.md#send-the-change-in). The run form has a field `reference` next to `dataset`. Pick a
dataset for each, submit, and read the log:

```text
[hello-world] hello (my-experiment-v1): 2 files (12 bytes) in clean, 3 in the reference, 1 dropped by prepare
```

The rules for reading are in [Your contract with the platform](contract.md#what-you-write), and what you see when a
dataset is empty is in [When something goes wrong](when-something-goes-wrong.md#a-run-fails). A dataset another project shares with yours is read in the same
field ([Share a dataset](share-a-dataset.md)).

Next: [Pass things on](pass-things-on.md).
