# Several pipelines

An app has one pipeline: the file `pipeline.py`. The platform builds one pipeline from it. A second `pipeline.py`-like
file in the same app is not built.

## Two pipelines are two apps

When you need two pipelines, make two apps. The second app reads what the first one makes. The first makes a dataset, and
the second names it in a setting:

```python title="the first app: pipeline.py"
--8<-- "examples/first-pipeline/template/pipeline.py"
```

```python title="the second app: pipeline.py"
--8<-- "examples/second-pipeline/pipeline.py"
```

```yaml title="the second app: config/clean.yaml"
--8<-- "examples/second-pipeline/config/clean.yaml"
```

The value `dataset-myapp-clean@latest` names the dataset `clean` of the app `myapp`. The run form of the second app offers
the datasets of your project and their versions. Only the first app writes the dataset. The second only reads it
([how](flow-datasets.md#a-second-pipeline-reads-the-dataset)). Pin a version to read the same data in every run
([Re-running](rerun.md)).

## What the apps do not share

- **Steps.** A step belongs to one app. To use the same code in two apps, copy it, or put it in a package both install
  ([Add packages](add-packages.md#share-code-between-steps)).
- **Settings.** Each app has its own `config/` and its own run form.
- **Runs.** Starting the first pipeline does not start the second. Start each one yourself.

Next: [Re-running](rerun.md).
