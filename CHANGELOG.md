# Changelog

All notable changes to kaos-lib. Versions follow PEP 440; each release's support window is in its
`release.json`. Packages: `https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/` (stable),
`.../kaos-lib-rc/simple/` (prerelease).

## 0.4.0 (unreleased)

PRD novelcore/kaos#1147 F-05, F-07, F-18 (D-03, D-13); dataset layouts: the formats become declarative,
user-definable layouts.

### Added
- `kaos_lib.errors.EmptyDataset`, a `DatasetError`: `materialize` raises it when the commit holds no files
  (a new project's `dataset-default`), so a step can tell "no data yet" from other dataset failures.
- `kaos_lib.mlflow`: `mlflow(tracking_uri=None, token=None)` configures the `mlflow` module and returns an
  `MlflowClient`; `token()`. One credential chain: explicit token or `$MLFLOW_TRACKING_TOKEN`, the step's machine
  key (`ZITADEL_MACHINE_KEY_FILE`, `ZITADEL_DOMAIN`, `ZITADEL_MLFLOW_PROJECT_ID`; minted with the organisation
  project's audience scope and refreshed before expiry), then the `kaosctl login` session (checked for expiry and
  for the organisation project's audience). New extra `kaos-lib[mlflow]`; `mlflow` is imported lazily.
- The MLflow request-auth provider `zitadel` (entry point `mlflow.request_auth_provider`), registered by
  kaos-lib: `MLFLOW_TRACKING_AUTH=zitadel` works without the `mlflow_zitadel_auth.py` file templates copied
  into every step.
- `kaos_lib.runtime`: `context()` (frozen `Context`: run id, workflow, app, project, step, outputs repository,
  lakeFS and MLflow endpoints, dataset ref and commit, support verdict) and `run_id()`, read from the environment
  only; missing values are None.
- `kaos_lib.lock`: the data lock. `datasets.resolve` (and so `materialize`) records every read; `record`,
  `write` (MLflow tags `kaos_lib.data.<repo>.commit` / `.owner` and the artifact `data.lock.json`, merged with
  the run's), `load`, `DataLock.replay`, and `$KAOS_LIB_LOCK`. `LockError` for malformed or missing locks.
- `kaosctl run --lock <mlflow-run-id> -- <command>`: runs the command with the lock in `$KAOS_LIB_LOCK`.
- `zitadel.grant` (the whole token response, with `expires_in`) and `zitadel.env_settings`.
- `kaos_lib.layouts`: a layout is a `layout.yaml` (spec `layouts/shared/layout.schema.json`) with parameters, a
  starter skeleton (`{{placeholders}}`), declarative rules (required and allowed patterns, extensions, pairs, line
  patterns, a manifest schema), what a pull downloads, and an optional Python hook (`validate`, `materialize`).
  `layouts.load(name|path)`, `layouts.available()`, `Layout.validate/skeleton/parse/materialize/publish`.
- Sources, in lookup order: built-in (`yolo`, `raw`), installed packages (entry point group `kaos_lib.layouts`),
  the project's registry in kaos-lake (`GET /kaos/v1/dataset-templates`, from the project's `layouts`
  repository); a path is read as is.
- `kaosctl layout list|show|init|validate|publish`; `dataset create --layout <name|path> --param key=value`;
  `dataset push` validates with the layout of the repository's label.
- The schema, the built-in layouts and the test fixtures (`tests/layout_fixtures`) are shared byte for byte with
  kaos-lake, pinned by `SHA256SUMS`; both implementations pass the same fixtures.
- Guide: [Make your own dataset layout](docs/make-your-own-layout.md).

### Changed
- The command is `kaosctl` (it was `kaos-cli`, which keeps working as a hidden alias for one release, as does
  `kubecore`).
- The `yolo` format is the built-in `yolo` layout: a declarative `layout.yaml` plus a small hook
  (`kaos_lib.layouts.yolo`: class ids, value counts, coordinates, the `data.yaml` path rewrite). Some problems are
  worded differently (`data.yaml: no file matches (required)`, `images/x.jpg has no labels/x.txt`).
- `raw` creates a README; `create_dataset`'s default layout is `yolo`, as before.
- `datasets.materialize(..., layout=...)` and `datasets.layout_of`; `fmt_name=`, `format_of` and
  `kaos_lib.formats.get_format` keep working.
- The cache marker records the layout's download patterns: a copy made with other patterns is fetched again.

### Unchanged
- The `kubecore` import shim and command still ship in 0.4.0: templates still import `kubecore`. Support:
  `>=0.2`, no deprecations.

## 0.3.0 (2026-11-02)

The package is renamed and moves to its own repository, `kaos-io/kaos-lib` (it was `packages/kubecore` in
`novelcore/hera-pipeline-template`; history carried over).

### Changed
- Distribution `kubecore` → `kaos-lib` (extra `kaos-lib[zitadel]`); import `kubecore` → `kaos_lib`; command
  `kubecore` → `kaosctl`. Published by the platform's CI to public Python repositories (Artifact Registry), not
  PyPI: `pip install --index-url https://europe-west1-python.pkg.dev/kaos-dev-511509/kaos-lib/simple/
  --extra-index-url https://pypi.org/simple/ "kaos-lib[zitadel]==0.3.0"`.
- `KubecoreError` → `KaosLibError`.
- New dependency: `packaging` (PEP 440 support checks).

### Added
- `release.json` (packaged as `kaos_lib/_release.json`, published per release in the public release bucket) and
  `kaos_lib.support.check`: verdicts current / behind / deprecated / unsupported. Pipeline steps check at import
  when `$KAOS_LIB_SUPPORT` is set; `kaosctl` warns on reads and refuses writes when unsupported.
- Release channels: prerelease `X.Y.ZrcN` (repository `kaos-lib-rc`, every merge to `main`) and stable `X.Y.Z`
  (repository `kaos-lib`, promoted by the platform's release train from a passed rc, checked to hold the rc's
  code byte for byte). `kaosctl --version` shows the channel and the targeted platform's recommendation;
  `kaosctl upgrade` installs that recommendation (kaos-lib over https only), else the newest release of the
  install's channel from the public `release.json`.
- Apache-2.0 license, project URLs, this changelog.

### Deprecated (removed in the next release)
- The `kubecore` import shim: `import kubecore` / `from kubecore import datasets` still work (the same
  `kaos_lib` modules) and emit one `DeprecationWarning`.
- The `kubecore` command: runs `kaosctl` after a note on stderr.
- The `KubecoreError` alias.

### Unchanged on purpose
- `.kubecore/dataset-config.yaml`, `~/.config/kubecore-ml/` (`$KUBECORE_ML_HOME`), the dataset cache
  `~/.cache/kubecore/datasets` with its `.kubecore-dataset.json` markers, and the `KUBECORE_*` variables: other
  platform components and existing logins and caches rely on them.

Support: `>=0.2`, no deprecations.

## 0.2.0

Last release as `kubecore` inside `novelcore/hera-pipeline-template`: datasets as lakeFS repositories, raw format,
shared datasets between projects, branch-per-run outputs.
