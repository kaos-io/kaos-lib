# The data contract

The third part of [the contract](contract.md): what a dataset is, how it is named, what a run reads, what it writes, and
what the platform keeps. Four pages:

| page | it says |
|---|---|
| this page | the three kinds of dataset, names and addresses, versions and hashes |
| [What a run reads](data-reads.md) | how a run fixes versions at its start, and how a step asks for data |
| [What a run writes](data-writes.md) | what is saved and when, when `latest` moves, models and artifacts |
| [What is kept, and for how long](data-retention.md) | what is removed by itself, and what never is |

## What a dataset is

A dataset is a named set of files in your project. You meet it in one of three kinds.

| | uploaded | produced by a step | shared from another project |
|---|---|---|---|
| name | `dataset-<name>` | `dataset-<app>-<name>`, from `dataset("<name>")` in the app `<app>` | `<project>/dataset-<name>` |
| made by | you, with `kaosctl dataset push`. It changes only through a merged pull request | one step of one pipeline, when it calls `step.result()` | the project that owns it |
| versions | `v1`, `v2`, ... that you make with `kaosctl dataset release`; and `latest` | one for each run that changes its files; and `latest` | the versions the owner made |
| who writes | the people of the project | only the app that declares it | only the owner. You read it |

In code you use the short name: `dataset("clean")`, `step.output("clean")`, `step.input("clean")`. A pipeline reads a
dataset of the second kind in a setting, like any other ([a second pipeline reads it](flow-datasets.md#a-second-pipeline-reads-the-dataset),
[Share a dataset](share-a-dataset.md)).

## Names and addresses

An address says which dataset and which version. It is `<repository>@<version>`, and a dataset of another project has the
owner's project in front.

| address | meaning |
|---|---|
| `dataset-<name>` | the same as `@latest` |
| `dataset-<name>@v1` | a named version |
| `dataset-<name>@latest` | the version the name `latest` points to |
| `dataset-<name>@<id>` | one exact version, by its id |
| `dataset-<app>-<name>` | a dataset the app `<app>` produces with `dataset("<name>")` |
| `<project>/dataset-<name>@<version>` | a dataset another project shares with yours (read-only) |

The address does not name a folder inside the dataset. `kaosctl dataset pull <repository>@<version> ./here --prefix
folder/` downloads one folder. The setting that holds an address is the same for every kind: a top-level value of
`config/` that a step names in `inputs=`.

## What a version is

A version is a snapshot of all the files of a dataset at one moment. It never changes after it is made. It has up to
three names.

- **The version id**, a long hex string of 64 characters, for example
  `37592accd6a211f20307af0db7fceebf98c50367442b65eb1391ac0e6d6d3e96`. It is the exact name: one id is one set of files.
  Logs show the first 12 characters, `37592accd6a2`.
- **`vN`**, a label such as `v2`, on an uploaded dataset. `kaosctl dataset release dataset-x` gives the version `latest`
  points to the next number. It refuses when that state already has one: `nothing new to release`. How: [Release a dataset version](release-a-version.md).
- **`latest`**, the name that points to the dataset's current version. For an uploaded dataset it moves when a pull
  request is merged. For a produced dataset it moves at the end of a run whose steps all went well, when the run has its
  `promote-<name>` field set to `true` ([when `latest` moves](data-writes.md#when-latest-moves)). `latest` can be newer
  than the newest `vN`, because nobody has released the change yet.

A version that a run sealed without asking is newer than `latest` in time, but it is not `latest`: nothing reads it unless
you name its id.

### Where you see an id

| where | what you see |
|---|---|
| the log of a step that makes a dataset | `output 'clean': sealed dataset-myapp-clean at b2e7b6573672 (kept as ...). It becomes the latest when the whole run has ended well, if the run form's promote-clean is ticked.` |
| the last task of the run | `dataset 'clean': dataset-myapp-clean is now at 91c0e0aa1f3d (latest), the version step 'prepare' sealed (b2e7b6573672).` |
| the result of a step | the full id, 64 characters, in `reads` and `writes` ([what a run records](data-reads.md#what-a-run-records)) |
| `kaosctl step run` on your laptop | `read    clean: dataset-myapp-clean at b2e7b6573672` |
| the MLflow run of a step that uses MLflow | the file `ledger/<step>.json` and the tags `kaos_lib.data.<dataset>.commit` |

On your laptop an id is a fingerprint of the files: the same files give the same id. On the platform it is the id the data
store gives the version.

## What does not exist

- A version that is edited. A new version is made instead.
- A step that picks a version in code. The form picks it (`kaosctl lint` warns when step code writes one: `L-W03`).
- A partial version. [What a failed step can leave behind](data-writes.md#what-is-saved-and-when) is a version no one
  reads, never half of one.

Next: [What a run reads](data-reads.md).
