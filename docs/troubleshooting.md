# Troubleshooting

`kaosctl` prints one `ERROR: …` line and exits `1` for a problem you can fix, and `2` for a dataset that failed
validation. In Python the same messages are the text of `kaos_lib.errors.KaosLibError` and its subclasses
(`ConfigError`, `AuthError`, `DatasetError`, `LockError`, …). The messages below are quoted from the code.

## Sign-in and configuration

| You see | Why | Do |
| --- | --- | --- |
| `cannot determine the lakeFS URL. Run inside your app clone (it carries .kaos/dataset-config.yaml), pass --url, or set LAKEFS_ENDPOINT.` | You are not inside your app folder (the one holding `.kaos/dataset-config.yaml`) and no URL is set. | `cd` into your app clone, or pass `--url`, or export `LAKEFS_ENDPOINT`. |
| `not signed in. Run `kaosctl login`, or set LAKEFS_ACCESS_KEY/LAKEFS_SECRET_KEY (or LAKEFS_BEARER_TOKEN) in the environment.` | No credential in the [chain](credentials.md). | `kaosctl login`. In a pipeline step the platform sets the key pair: if it is missing, the step was not started by the platform. |
| `browser sign-in is not configured for this app (no oidcIssuer/oidcClientId in .kaos/dataset-config.yaml)…` | `kaosctl login` outside an app clone. | Run it inside the clone, or use an access key. |
| `timed out waiting for the browser sign-in`, `sign-in failed: …` | The browser tab was closed or the sign-in was refused. | Run `kaosctl login` again. It opens a browser: there is no device-code flow. |
| `your `kaosctl login` session has expired: run `kaosctl login` again.` | The cached token ran out (MLflow calls). | `kaosctl login`. |
| `kaos_lib.mlflow needs the mlflow extra: pip install 'kaos-lib[mlflow]'.` | The `mlflow` extra is not installed. | Install it, see [Install](install.md#extras). |
| `cannot determine the MLflow tracking URI: pass tracking_uri= or set MLFLOW_TRACKING_URI.` | Not in a pipeline step. | Set `MLFLOW_TRACKING_URI`. |

## Datasets

| You see | Why | Do |
| --- | --- | --- |
| `--classes and --param fill a layout's parameters, and no layout is named (the default is none): add --layout yolo, …` | A new dataset has no layout unless you ask for one. | `kaosctl dataset create cats --layout yolo --classes cat,kitten`. |
| `unknown layout 'x'. Known: raw, yolo.` | A typo, or a project layout you cannot see. | `kaosctl layout list`; sign in so the project's layouts are looked up. |
| `<repo> has no version v3. Available: v1, v2.` | The version was never released. | `kaosctl dataset versions <repo>`; release after the pull request merges. |
| `<repo> has no version v1. Available: none yet (release one with `kaosctl dataset release`).` | Nothing was released yet. | Merge your pull request, then `kaosctl dataset release <repo>`. |
| `nothing new to release: the head of <repo> main is already v2. Merge a pull request first.` | `release` tags the head of `main`; it has not moved. | Merge the push's pull request in the lakeFS UI. |
| `<repo> already exists. Push to it with `kaosctl dataset push <dir> <repo>`.` | `create` of a name that exists. | Use `push`, or pick another name. |
| `repository <repo> does not exist. List datasets with `kaosctl dataset list`.` | A wrong name or ref. | `kaosctl dataset list`. |
| `'x' is not a dataset reference: write <repository>@<ref>, …` | A ref without `@`. | `dataset-cats@v1`. See [Datasets](datasets.md). |
| `EmptyDataset` | The commit holds no files (a new project's `dataset-default`). | Push data, release, then read the new version. |
| `dataset failed validation (N problem(s))` (exit `2`) | The layout's checks found problems; each is listed above this line. | Fix them, or `kaosctl dataset validate <dir> --layout <name>` to re-check. |
| `cannot create <owner>/dataset-x: it belongs to project <owner>, and datasets shared with your project are read-only. Ask <owner> to create it.` | `create`, `push` or `release` of `<owner>/dataset-x`. | Shared datasets are read-only: ask the owning project, see [shared datasets](shared-datasets.md). |

## Outputs and the data lock

| You see | Why | Do |
| --- | --- | --- |
| `outputs-<app> does not exist: the platform creates it for each ML app.` | The app name is wrong, or the app is not an ML app. | Use the app's name (`$CHECKPOINT_BUCKET` in a step). |
| `invalid app name 'X': use lowercase letters, digits and '-'.` | The name has other characters. | Fix the name. |
| `no MLflow run to write the data lock to: pass run_id=, start a run, or set $MLFLOW_RUN_ID.` | `lock.write()` with no run. | Call it inside `mlflow.start_run()`, or pass `run_id`. |
| `MLflow run <id> has no data.lock.json: the run did not record its data reads…` | `kaosctl run --lock` on a run that never wrote a lock. | Call `lock.write()` at the end of the original step. |

## Versions

A step that stops with `UnsupportedVersion`, or a command refused because the platform says your kaos-lib is
unsupported, needs an upgrade: `kaosctl upgrade` ([Support policy and upgrades](support-window.md)).
