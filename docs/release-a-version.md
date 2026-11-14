# Release a dataset version

**You want** a fixed name for the files of an uploaded dataset as they are today, so that a pipeline reads the same files
every time.

The name is `v1`, `v2`, and so on. Only a dataset you upload has them. A dataset a step makes has no `vN`: a pipeline
reads it as `latest` or by its version id ([what a version is](data-contract.md#what-a-version-is)).

## Release it

The files must be in the dataset first: pushed, and the pull request merged
([Add or change data](add-or-change-data.md)). A pull request that is not merged is not in the release.

```bash
kaosctl dataset release dataset-cats
```

```text
Released dataset-cats v3.
```

- `release` gives the files `latest` points to now the next number: `v1` for the first, then `v2`. `v10` follows `v9`.
- It changes no file. It adds a number and moves no older one.
- It refuses when `latest` already has a number: `nothing new to release: the head of dataset-cats main is already v2.
  Merge a pull request first.`
- Two pull requests merged before you release are both in the version.

List the versions of a dataset:

```bash
kaosctl dataset versions dataset-cats
```

```text
dataset-cats: v1, v2, v3 (and latest, the head of main)
```

`latest` can be newer than the newest `vN`: nobody has released the change yet.

## Pin it in a pipeline

A pipeline reads a dataset in a setting, and the setting holds the dataset with a version:
`<repository>@<version>`.

```yaml title="config/dataset.yaml"
dataset: "dataset-cats@v3"
```

- The value is the default of the field on the run form. Whoever starts a run can pick another version of the dataset
  there.
- Before the first step starts, the platform fixes the choice to one exact version. Every step of the run reads that
  version ([what a run reads](data-reads.md#fixed-when-the-run-starts)).
- With no version, or with `@latest`, the run reads the files `latest` points to when the run starts.
- A version that does not exist refuses the run before the first step. The message names the setting and says
  `dataset-cats has no version v4. Available: v1, v2, v3.`

A dataset another project shares is read in the same way, with the owner's project in front. Only the owner releases
its versions ([Share a dataset](share-a-dataset.md)).
