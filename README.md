# kaos-lib

The KAOS platform library (formerly `kubecore`): datasets (layouts, versions), run outputs, and the `kaos-cli`
command, over kaos-lake (lakeFS). PRD novelcore/kaos#1147 (D-15) and #1283 (D-11, F-14).

## Install

```bash
pip install kaos-lib                # once it is on PyPI
```

Until then, install from git, pinned to a commit:

```bash
pip install "kaos-lib @ https://github.com/kaos-io/kaos-lib/archive/<sha>.zip"
```

Python 3.9+. Dependencies: `requests`, `PyYAML`. Reading datasets other projects share from a pipeline step
(machine-key tokens) needs the `zitadel` extra (PyJWT, cryptography):

```bash
pip install "kaos-lib[zitadel]"
pip install "kaos-lib[zitadel] @ https://github.com/kaos-io/kaos-lib/archive/<sha>.zip"
```

Import it as `kaos_lib`; the command is `kaos-cli`.

### Formerly kubecore

Up to 0.2 this was the `kubecore` package in `novelcore/hera-pipeline-template` (`packages/kubecore`). For one
release (0.3.x) the distribution still ships:

- a `kubecore` import shim: `import kubecore` and `from kaos_lib import datasets` keep working (the very
  `kaos_lib` modules) and emit one `DeprecationWarning`. Replace `kubecore` with `kaos_lib` in your imports;
  `KubecoreError` is now `KaosLibError` (the old name stays an alias).
- a `kubecore` command: runs `kaos-cli` after a note on stderr.

Unchanged on purpose (other components and existing installs rely on them): the per-app
`.kubecore/dataset-config.yaml`, the login session in `~/.config/kubecore-ml/` (`$KUBECORE_ML_HOME`), the
dataset cache `~/.cache/kubecore/datasets` with its `.kubecore-dataset.json` markers, and the `KUBECORE_*`
environment variables.

## Any repository works

Layouts are optional. `DatasetRef.parse` accepts any lakeFS repository (`my-repo@main`) and a ref that is
`vN` (tag), `latest` (head of the default branch), a branch, a tag or a commit id. `materialize` uses the
layout the repository's `kaos.template` label names, and otherwise `raw`: the whole tree (or `prefix=`) at the
pinned commit, cached by (repo, commit, prefix), returned as a folder. `raw` checks nothing and publishes as is.
`kaos-cli dataset create <name> --layout none` makes an empty `dataset-<name>` (only `kaos.kind=dataset`);
kaos-lake lists it as a dataset once its first commit lands. The pipeline dropdown lists only `dataset-*`
repositories.

## Layouts

A layout says what a dataset holds: a declarative `layout.yaml` with its parameters, the starter files `create`
writes, the rules `validate` and `push` check, what a pull downloads, and optionally a small Python hook for
checks no rule can say. Two are built in: `yolo` (images with one YOLO txt label file per image, and a
`data.yaml`) and `raw` (any files). Your team can make its own and share it with the project, or publish it as
a package: **[Make your own dataset layout](docs/make-your-own-layout.md)**.

```
kaos-cli layout list                              # built-in, installed and your project's layouts
kaos-cli layout show yolo                         # its spec
kaos-cli layout init ./my-layout [--from yolo]    # a starter layout.yaml to edit
kaos-cli layout validate <dir> --layout <name|path>
kaos-cli layout publish ./my-layout               # a pull request into the project's `layouts` repository
```

Names are looked up built-in first, then installed packages (entry point group `kaos_lib.layouts`), then the
project's registry (kaos-lake, `GET /kaos/v1/dataset-templates`); anything with a `/` or ending in `.yaml` is
read as a path. kaos-lake checks a layout's declarative rules only and never runs its hook; kaos-lib runs both.

## Data model

- A dataset is its own lakeFS repository `dataset-<name>` (3 to 48 chars of `a-z0-9-` after the prefix);
  each project has `dataset-default`. Versions are tags `v1`, `v2`, ... on `main`; `latest` is the head of
  `main`. A run picks `<dataset-repo>@<version>`.
- Changes reach `main` only through a pull request (the only direct commit is the starter layout written by
  `create`, as the kaos-lake UI does: repo, starter files on main, then labels). New repositories are placed at `<storage_namespace_prefix kaos-lake publishes>/<repo>`, or `$KUBECORE_STORAGE_NAMESPACE_BASE`.
- Each ML app writes results to `outputs-<app>`, on `main`, one commit per step per run (a merge from
  the step's own branch `run-<run>-<kind>`, so simultaneous runs never mix), under
  `<kind>/<experiment>/<run>/` (`kind` is `checkpoints` by default). `finish()` returns the merge
  commit id on `main`.

## Python API

```python
from kaos_lib import datasets, outputs

ref = datasets.DatasetRef.parse("dataset-default@v2")      # any repository: "my-repo@main", "@latest", "@<tag>", "@<commit>"
ref = ref.with_commit(commit)                              # optional: pin the commit dataset-loading resolved
commit = datasets.resolve(ref)                             # pinned commit returned as is, else tag/main head
data_yaml = datasets.materialize(ref, dest=None)           # yolo: Path to data.yaml; raw: the folder (prefix= for one folder)
datasets.list_datasets(); datasets.versions("dataset-x"); datasets.release("dataset-x")   # -> "vN"

from kaos_lib import layouts                               # yolo: detect, segment, pose
yolo = layouts.load("yolo")                                # a name, a path, or layouts.available() for all
yolo.skeleton("dataset-pets", values={"classes": ["cat", "dog"]}); yolo.validate(dir); yolo.publish(dir, repo, "msg")
yolo.materialize(ref, dest, commit=None)

with outputs.run("myapp", "exp1", "run-7", "checkpoints") as r:    # branch run-run-7-checkpoints, reused on retry
    resume = r.latest("weights/")                          # local path of what the branch already holds, or None
    r.save("./ckpt")                                       # upload + commit on the run branch (durable)
    r.finish({"dataset_ref": "dataset-default@v2", "mlflow_run_id": "..."})  # merge into main, delete branch
outputs.write_run("myapp", "exp1", "run-7", "./ckpt")      # shortcut: open, save once, finish
```

## Datasets shared with your project

Another project of your organisation can share its `dataset-*` repositories with yours (read-only; models are
not shared). Refer to one as `<owner-project>/dataset-<name>@<version>`; `dataset-<name>@<version>` keeps
meaning your own project, and `<your-project>/dataset-x@v1` is the same as `dataset-x@v1`.

```python
ref = datasets.DatasetRef.parse("team-a/dataset-cats@v3")   # ref.owner == "team-a"; also @latest, a branch or a commit
data_yaml = datasets.materialize(ref)                       # read from team-a's lakeFS, cached apart from your own
from kaos_lib import peers
for answer in peers.shared(client):                         # per peer: answer.datasets (DatasetInfo, owner set), answer.note
    ...
```

```
kaos-cli dataset list --shared                # what other projects share with yours, with versions
kaos-cli dataset versions team-a/dataset-cats # its versions, read from team-a's lakeFS
kaos-cli dataset pull team-a/dataset-cats@v3  # read-only copy
```

- **Where**: your lakeFS lists the other projects (`GET /kaos/v1/peers`, read once per process).
  `LakeFS.for_owner(owner)` talks to the owner's in-cluster endpoint when your own lakeFS address is an
  in-cluster `.svc` one (pipeline steps), else to its public URL (laptops).
- **Who**: the owner sees a bearer token, never your project's `LAKEFS_ACCESS_KEY`/`LAKEFS_SECRET_KEY`
  (`credentials.resolve_peer`): `LAKEFS_BEARER_TOKEN`, else a short-lived Zitadel token minted from the step's
  machine key (`ZITADEL_MACHINE_KEY_FILE`, `ZITADEL_DOMAIN`, `ZITADEL_MLFLOW_PROJECT_ID`; needs
  `kaos-lib[zitadel]`), else your `kaos-cli login` session. The owner grants read on exactly the datasets it
  shares with your project.
- **Cache**: `<cache>/<owner>/<repo>/<commit>` (your own: `<cache>/<repo>/<commit>`); the copy's marker records
  the owner, so your `dataset-x` and the owner's `dataset-x` never mix, even at the same commit id. A staged copy
  (`$KUBECORE_STAGED_DIR`) is used only when its `.kaos-ready` record names the same repository and owner.
- **Read-only**: `release`, `push` and `create` of a `<owner>/...` name are refused before anything is sent.
- **Errors**: an owner that is not a project of your organisation, or a lakeFS too old to serve
  `/kaos/v1/peers`, is a one-line error. In `list --shared`, a peer that answers 401 shares nothing with you; a
  peer too old or unreachable is skipped with a `NOTE:` on stderr.

An exception inside `with outputs.run(...)` neither merges nor deletes the branch, so the retry resumes.
Leaving the block normally without calling `finish` finishes with no extra metadata. An empty commit or an
empty merge is a success and returns the existing commit.

`yolo` datasets are validated for detection (`cls x y w h`), segmentation (`cls x1 y1 x2 y2 ...`, even count >= 6) and
pose (`kpt_shape: [K, D]`, K*D values per line, visibility 0/1/2 when D=3). `nc` is optional when `names` is given.

### Rights each call needs

| call | needs |
| --- | --- |
| `resolve`, `materialize`, `Layout.materialize`, `versions`, `list_datasets`, `DatasetRef` | read on `dataset-*` (an app key can) |
| the same on `<owner>/dataset-*`, `peers.shared` | a bearer token the owner accepts (machine-key token or login session) |
| `outputs.run(...)` / `write_run` (`open`, `save`, `latest`, `finish`) | write on that app's `outputs-<app>` (an app key can) |
| `release` | tag creation on the dataset: people or admins, not an app key |
| `create_dataset`, `Layout.publish` / `publish_tree` (repository, draft branch, pull request) | people or admins, not an app key |
| `kaos-cli layout publish` (the project's `layouts` repository) | people who may create datasets, not an app key |
| `layouts.load` of a project layout | any signed-in caller (an app key can) |

`materialize` downloads what the layout's `materialize.include` names (`yolo`: `data.yaml`, `images/`,
`labels/`) at the pinned commit, lets the layout's hook finish the copy (`yolo` rewrites `path:`), and
caches by (repo, commit) (`$KUBECORE_CACHE_DIR`, default `~/.cache/kubecore/datasets`); a second call is
free. If `$KUBECORE_STAGED_DIR` holds that commit (MeluXina staging), it is used in place and nothing is
downloaded.

## Credentials (one chain, no secrets in the package)

1. `LAKEFS_ACCESS_KEY` + `LAKEFS_SECRET_KEY` (an app's key pair), endpoint `LAKEFS_ENDPOINT`
2. `LAKEFS_BEARER_TOKEN` (MeluXina jobs)
3. the browser login session of `kaos-cli login` (a person's Zitadel token), cached in
   `~/.config/kubecore-ml/lakefs-session.json`

Another project's lakeFS gets its own chain (`credentials.resolve_peer`), without step 1; see
"Datasets shared with your project".

The lakeFS URL comes from `--url`, `LAKEFS_ENDPOINT`/`LAKEFS_URL`, or `.kubecore/dataset-config.yaml`
(written into every app repo by the platform, which also carries the login settings).

## CLI

```
kaos-cli login
kaos-cli dataset create <name> [--layout <name|path>] [--classes a,b,c] [--param key=value] [--description ...]
kaos-cli dataset list [--shared]
kaos-cli dataset versions <repo>
kaos-cli dataset release <repo>
kaos-cli dataset push <dir> <repo> -m "message" [--no-validate]   # validates with the label's layout, then a pull request
kaos-cli dataset pull [<owner>/]<repo>@<version> [dest] [--layout ...]
kaos-cli dataset validate <dir> [--layout <name|path>]
kaos-cli layout list | show <name> | init <dir> | validate <dir> --layout <name|path> | publish <dir>
```

`dataset create` and `dataset validate` default to the `yolo` layout; `--layout none` creates an empty repository.

Every command prints the next step and the lakeFS link (dataset page, pull request, version).
Exit codes: 0 ok, 1 user error (one `ERROR:` line), 2 invalid dataset.

## Support window

Every release ships `release.json` (in the package as `kaos_lib/_release.json`, and as the asset `release.json`
of the GitHub release):

```json
{"version": "0.4.0", "supported": ">=0.3", "deprecated": [{"range": "<0.3", "unsupported_after": "YYYY-MM-DD"}],
 "breaking": false, "migration": "<url>"}
```

The newest release's file is the policy. `kaos_lib.support.check(installed, support_json)` returns
`{verdict, message, fix}`: `current`, `behind` (older, still supported), `deprecated` (outside `supported`, inside
a deprecated range whose `unsupported_after` has not passed, or that sets none), `unsupported` (outside
`supported` and past any deadline). Metadata that cannot be read is `unknown`: a warning, never a failure.

- Pipeline steps: when the platform sets `$KAOS_LIB_SUPPORT`, importing `kaos_lib` (or the `kubecore` shim) logs
  the verdict on stderr, tags the MLflow run `kaos_lib.support` (the active run, or `$MLFLOW_RUN_ID`), and stops
  the step only when unsupported.
- `kaos-cli`: reads the policy from the project lakeFS (`/kaos/v1/ui`, key `kaos_lib_support`), else the packaged
  `_release.json`. Reads warn; `create`, `release` and `push` are refused when the platform says unsupported.
  Offline or without platform metadata nothing is refused.

## Tests

```bash
pip install -e ".[test]" && pytest
```

A fake lakeFS (`tests/fake_lakefs.py`) runs the real client over an in-memory transport; no network.

## File map

| file | job |
| --- | --- |
| `config.py` | per-app config discovery, lakeFS URL, OIDC settings |
| `credentials.py` | the credential chain, session cache, browser login |
| `oidc.py` | PKCE browser login to Zitadel (ported from `dataset_tools`) |
| `zitadel.py` | machine-key token (JWT-profile grant), extra `kaos-lib[zitadel]` |
| `peers.py` | the other projects (`/kaos/v1/peers`) and what they share (`/kaos/v1/shared`) |
| `lakefs.py` | lakeFS REST client |
| `transfer.py` | mirror plan, upload, download of file trees |
| `datasets.py` | refs (`[<owner>/]<repo>@<ref>`), resolve, list, versions, release, create, publish via PR, materialize |
| `layouts/` | layouts: sources, spec and schema subset (`spec.py`), skeletons (`render.py`), rules (`rules.py`), the yolo hook (`yolo.py`), the cache (`local.py`), the files shared with kaos-lake (`shared/`) |
| `formats/` | the 0.3 `get_format` API over layouts |
| `outputs.py` | `outputs-<app>` writes |
| `cli.py` | the `kaos-cli` command (and the deprecated `kubecore` alias) |
| `../kubecore/` | the deprecated `kubecore` import shim (0.3.x only) |
