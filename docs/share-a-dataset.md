# Share a dataset between projects

**You want** a pipeline to read a dataset that another project of your organisation owns.

The owner shares a dataset with your project from the dataset's page in the data store. You then list what is shared
with you:

```bash
kaosctl dataset list --shared
```

Each row is `<project>/<dataset>`, its versions and a description. Without any shared dataset the command says so.
`kaosctl dataset versions <project>/dataset-cats` lists the versions of one, and `kaosctl dataset pull
<project>/dataset-cats@v1` downloads one.

A pipeline reads it in the same setting as any dataset, with the owner's project name in front:

```yaml title="config/dataset.yaml"
--8<-- "examples/flows/shared/config/dataset.yaml"
```

Everything else is as in [Read data](read-data.md): the step declares the setting in `inputs=`, the run form lists it, and
the run reads one exact version.

A shared dataset is read-only. `kaosctl dataset push`, `release` and `create` on it are refused, and the message names
the owner: ask the owner to change it. Only the project that owns a dataset writes it.
