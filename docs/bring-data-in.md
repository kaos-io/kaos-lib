# Bring data in from outside

**You want** a pipeline to start from data that is not in your project: a source outside the platform that a step
copies into a dataset.

That step has the kind `ingest`. It runs on the platform's own machines and, like any step, writes a dataset by
declaring it in `produces=`. The kind has no other requirement on the code ([the ingest type](step-type-ingest.md)).

This example copies the `.csv` files of a folder into the dataset `raw`. The folder stands in for the outside source: a
real step writes into the same output folder what it downloads, in place of the loop.

```python title="pipeline.py"
--8<-- "examples/flows/ingest/pipeline.py"
```

```yaml title="config/source.yaml"
--8<-- "examples/flows/ingest/config/source.yaml"
```

```yaml title="config/config.yaml"
--8<-- "examples/flows/ingest/config/config.yaml"
```

```python title="steps/fetch/app/entry.py"
--8<-- "examples/flows/ingest/steps/fetch/app/entry.py"
```

`step.check("raw", min_files=1)` makes the step fail when the source gave no file, and nothing is saved
([what is saved](data-writes.md#what-is-saved-and-when)). The address of the source is a setting, so it is a field on the run form.

**The run records** a write of type `dataset` named `raw`: the dataset `dataset-<app>-raw`. The steps after `fetch` read
it with `needs=` ([Make a dataset and read it in the same run](flow-datasets.md#make-a-dataset-and-read-it-in-the-same-run)).
