# Datasets

## The model

- A **dataset** is its own lakeFS repository `dataset-<name>` (3 to 48 characters of `a-z0-9-` after the prefix).
  Every project has one already: `dataset-default`.
- **Versions** are tags `v1`, `v2`, … on `main`; `latest` is the head of `main`. A run reads
  `<dataset-repo>@<version>`, resolved to one commit, so a result always points back to its data.
- Changes reach `main` only through a **pull request**. The only direct commit is the starter layout `create` writes.
- Each ML app writes its results to `outputs-<app>` ([Outputs](outputs.md)), never to a dataset.

## Where you work with datasets

| place | what you do there |
| --- | --- |
| the KAOS console, **Datasets** page | see every dataset of your organisation, its versions and where it is; share a dataset with another project; open a project's lakeFS to create one |
| lakeFS (your project's data store), **Datasets** page | **New dataset**, upload files on a branch, open and merge pull requests, edit `data.yaml`, **Release version** |
| `kaosctl` on your computer | the same from a terminal: [create, push, validate, release, download](#commands) |
| a pipeline step | read the version the run picked ([How steps use datasets](steps-and-datasets.md)) |

People create datasets, push changes, merge pull requests and release versions. A pipeline only reads datasets: no
step can write to one, and nobody writes to a dataset's `main` directly.

## In the browser

- **Create.** Open your project's lakeFS and go to **Datasets** (from the KAOS console: **Datasets** → **Create in
  project**). Click **New dataset**, type the name and a short description, and choose the layout: **No layout**
  (chosen until you pick another) takes any files; **yolo** asks for the class names, one per line, in label-id
  order (the first one is id `0`).
- **Add or change files.** This suits a few files; for many, use `kaosctl dataset push`. Open the dataset →
  **Branches** → create a branch from `main`, upload your files to that branch, and open a **pull request** into
  `main`. To change the class names of a `yolo` dataset, open `data.yaml` and use **Edit** (Edit classes): it writes
  `data.yaml` again from the names you typed, so its class count always matches, and saves the change as a pull
  request.
- **Merge.** Open the pull request, look at the change, and **Merge**. Until then `main` is unchanged.
- **Release.** Open the dataset on the **Datasets** page and click **Release version**. A few minutes later the run
  form of every pipeline offers the version in its `dataset` dropdown (`dataset-cats@v1`, `dataset-cats@latest`); if
  it is not there yet, open the form again.

## Any repository works

`DatasetRef.parse` accepts any lakeFS repository (`my-repo@main`) and a ref that is `vN` (a version tag), `latest`
(the head of the default branch), a branch, a tag or a commit id. The pipeline's `dataset` dropdown lists only
`dataset-*` repositories.

```python
from kaos_lib import datasets

ref = datasets.DatasetRef.parse("dataset-default@v2")    # also "my-repo@main", "@latest", "@<tag>", "@<commit>"
ref = ref.with_commit(commit)                            # read one specific commit on purpose (the platform pins the run's data)
commit = datasets.resolve(ref)                           # a pinned commit as is, else the tag or main's head
data = datasets.materialize(ref, dest=None)              # yolo: the path of data.yaml; raw: the folder (prefix= for one folder)
datasets.list_datasets(); datasets.versions("dataset-x"); datasets.release("dataset-x")   # release returns "vN"
```

`materialize` downloads what the dataset's layout names at the pinned commit and caches it by (repository, commit)
in `$KUBECORE_CACHE_DIR` (default `~/.cache/kubecore/datasets`), so a second call is free. When
`$KUBECORE_STAGED_DIR` holds that commit (an HPC (Slurm) job with pre-staged data), it is used in place and nothing is downloaded. A commit
with no files raises `EmptyDataset` (a `DatasetError`), so a step can tell "no data yet" from other failures.

## Layouts

A **layout** says what a dataset holds: the files `create` starts it with, the rules `validate` and `push` check,
and what a pull downloads. Two are built in:

| layout | holds | checked |
| --- | --- | --- |
| `yolo` | images, one YOLO `.txt` label file per image, and a `data.yaml` with the splits and class names | detection (`cls x y w h`), segmentation (`cls x1 y1 …`, an even count of at least 6), pose (`kpt_shape: [K, D]`) |
| `raw` | any files | nothing; published as is |

`materialize` uses the layout named by the repository's `kaos.template` label, and otherwise `raw`. Your team can
add its own: [Make your own dataset layout](make-your-own-layout.md).

```bash
kaosctl layout list                              # built-in, installed and your project's layouts
kaosctl layout show yolo                         # its spec
kaosctl dataset validate ./my-folder --layout yolo
```

## Commands

```bash
kaosctl dataset create <name> [--layout <name|path|none>] [--classes a,b,c] [--param key=value] [--description ...]
kaosctl dataset push <dir> <repo> -m "message" [--no-validate]   # validates, then opens a pull request
kaosctl dataset release <repo>                                    # tags main as the next version
kaosctl dataset versions <repo>
kaosctl dataset pull [<owner>/]<repo>@<version> [dest]
kaosctl dataset list [--shared]
```

`push` makes the dataset look exactly like your folder: it uploads new and changed files and removes the files you
deleted, on a draft branch, and opens the pull request; a dataset that does not exist yet is created. `pull`
without `dest` keeps the copy by repository and commit and prints where it is, so pulling the same commit again is
instant; `--prefix folder/` downloads one folder, and the ref can be a version, `latest`, a branch, a tag or a
commit id. A copy you pulled is yours to change: `push` the folder to send the changes back.

`create` makes an empty dataset unless you name a layout (`--layout yolo`, or `--layout none` to say so); the
platform lists an empty dataset once its first commit lands. `--classes` and `--param` need a named layout. `validate` uses the
`yolo` layout unless you name another. Every command prints the next step and the lakeFS link. Exit codes:
`0` ok, `1` a user error (one `ERROR:` line), `2` an invalid dataset.

## Rights each call needs

| call | needs |
| --- | --- |
| `resolve`, `materialize`, `versions`, `list_datasets` | read on `dataset-*` (an app key can) |
| the same on `<owner>/dataset-*` | a bearer token the owner accepts ([shared datasets](shared-datasets.md)) |
| `outputs.run(...)` / `write_run` | write on that app's `outputs-<app>` (an app key can) |
| `release` | tag creation on the dataset: people or admins, not an app key |
| `create_dataset`, `Layout.publish` / `publish_tree` | people or admins, not an app key |
| `kaosctl layout publish` | people who may create datasets |
