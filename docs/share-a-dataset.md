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

## What the step reads it as

A step reads a shared dataset as its own app: nothing in the app asks for a key or a token for it, and the code is the same
as for a dataset of your project. The owner's data store gives your app read access to the datasets shared with your project and
to nothing else of the owner's. The access renews itself while a step runs, however long a download takes, and the step does not
see it. When the owner stops sharing a dataset, the next read of it is refused with a message that says the share was withdrawn
and names the owner. Every app of your project can read what is shared with the project; the
other projects' apps cannot.
