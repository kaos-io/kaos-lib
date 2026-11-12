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

- `inputs=["dataset"]` names a top-level value of `config/` that holds a dataset reference.
- A reference is `dataset-<name>` or `dataset-<name>@<version>`. The version is `v1`, `v2`, ..., `latest` (what the
  dataset holds now, see [Datasets, versions and hashes](datasets-versions-hashes.md#what-a-version-is)) or a commit.
- `step.input("dataset")` takes the name and nothing else. There is no version in code, so there is no way to read a
  different version from the one the run chose.

## Pick the version on the form

The field `dataset` on the run form lists your project's datasets and their versions. You pick one when you submit.
Before the first step starts, the platform fixes the choice to one exact version, and every step of the run reads
that version. A colleague who adds files while your run is going changes nothing for it.

```bash
kaosctl dataset list
kaosctl dataset versions dataset-default
kaosctl dataset release dataset-default
```

`list` shows the datasets you can read, `versions` the versions of one, and `release` gives the newest state of a
dataset the next version number.

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

## Rules

- A step reads what it declares. `step.input("other")` for a name that is not in `inputs=` raises
  `'other' is not an input of step 'hello-world'. Its inputs are: ...`. Reading a dataset another way, by its name in
  code, is refused too.
- The folder is read-only. Copy the files you change into an output. A tool that writes beside its input gets
  `step.input("reference", writable=True)`: a private copy that costs the dataset's size in disk and time.
- A dataset with no files fails the step: `input 'reference': dataset-x holds no files at the version this run read`.
- A dataset a project shares with yours is `<owner>/dataset-<name>@<version>`, in the same field.

Next: [Pass things on](pass-things-on.md).
